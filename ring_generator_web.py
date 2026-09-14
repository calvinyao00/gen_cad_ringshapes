#!/usr/bin/env python3
"""Local browser interface for the keyed ring DXF generator.

Uses only Python's standard library. The server binds to localhost and opens
the interface in the default browser, so it works on macOS and Windows
without Tkinter.
"""

from __future__ import annotations

import argparse
import html
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, urlparse

from generate_ring import (
    DEFAULT_LASER_CLEARANCE,
    DEFAULT_NOTCH_SIZE,
    DEFAULT_NOTCH_SHAPE,
    NOTCH_SHAPE_LABELS,
    NOTCH_SHAPES,
    SOURCE_INNER_RADIUS,
    SOURCE_OUTER_RADIUS,
    auto_notch_size,
    compensated_radii,
    default_filename,
    generate_dxf,
    generate_piece_dxf,
    ring_layout_filename,
    single_piece_filename,
)


PAGE_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>环形拼接件 DXF 生成器</title>
  <style>
    :root {
      color-scheme: light;
      font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
      color: #1f2933;
      background: #eef1f4;
    }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 24px; }
    .app {
      max-width: 1120px;
      margin: 0 auto;
      background: white;
      border: 1px solid #d8dee5;
      border-radius: 12px;
      box-shadow: 0 8px 28px rgba(31, 41, 51, .10);
      overflow: hidden;
    }
    header { padding: 22px 28px 16px; border-bottom: 1px solid #e5e9ee; }
    h1 { margin: 0; font-size: 24px; }
    header p { margin: 8px 0 0; color: #65727e; }
    .content { display: grid; grid-template-columns: 360px 1fr; gap: 24px; padding: 24px 28px 28px; }
    .panel { border: 1px solid #d8dee5; border-radius: 9px; padding: 18px; }
    .panel h2 { margin: 0 0 16px; font-size: 17px; }
    .field { margin-bottom: 13px; }
    label { display: block; font-weight: 600; font-size: 14px; margin-bottom: 5px; }
    input, select, button {
      font: inherit;
      border: 1px solid #b9c3ce;
      border-radius: 6px;
      padding: 8px 10px;
    }
    input, select { width: 100%; background: #fff; }
    input:disabled { background: #f1f3f5; color: #6b7785; }
    .check { display: flex; align-items: center; gap: 8px; font-weight: 600; margin: 12px 0; }
    .check input { width: auto; }
    .hint { color: #687684; font-size: 13px; line-height: 1.55; margin: 14px 0 0; }
    .output { margin-top: 20px; }
    .filename { background: #f4f7f9; border: 1px solid #d8dee5; border-radius: 6px; padding: 9px 10px; word-break: break-all; color: #334e68; font-size: 13px; }
    .button-row { display: flex; align-items: center; gap: 12px; margin-top: 18px; }
    button { cursor: pointer; background: #1769aa; color: white; border-color: #1769aa; font-weight: 700; }
    button:hover { background: #0f578e; }
    #status { color: #52606d; font-size: 14px; }
    #status.error { color: #b42318; }
    #status.success { color: #147d64; }
    .preview-panel { min-width: 0; }
    #preview { display: block; width: 100%; min-height: 430px; background: #20252b; border-radius: 7px; }
    .preview-note { margin: 10px 0 0; color: #687684; font-size: 13px; }
    @media (max-width: 820px) {
      body { padding: 10px; }
      .content { grid-template-columns: 1fr; padding: 16px; }
      header { padding: 18px 16px 14px; }
    }
  </style>
</head>
<body>
  <main class="app">
    <header>
      <h1>环形拼接件 DXF 生成器</h1>
      <p>本地浏览器界面 · 尺寸单位：毫米 · 输出文件直接保存到本机</p>
    </header>
    <div class="content">
      <section class="panel">
        <h2>环形参数</h2>
        <div class="field">
          <label for="inner">内径（毫米）</label>
          <input id="inner" type="number" min="0.01" step="0.1" value="203">
        </div>
        <div class="field">
          <label for="outer">外径（毫米）</label>
          <input id="outer" type="number" min="0.01" step="0.1" value="262">
        </div>
        <div class="field">
          <label for="plate-thickness">板厚（毫米）</label>
          <input id="plate-thickness" type="number" min="0" step="0.1" value="0">
          <p class="hint">板厚按单侧输入。切割内径 = 输入内径 + 2×板厚；切割外径 = 输入外径 − 2×板厚。文件名中的“板厚”记录两侧总补偿。</p>
        </div>
        <div class="field">
          <label for="parts">零件数量</label>
          <input id="parts" type="number" min="2" step="1" value="4">
        </div>
        <div class="field">
          <label for="shape">缺口形状</label>
          <select id="shape">
            <option value="trapezoid">梯形</option>
            <option value="rectangular">矩形</option>
          </select>
        </div>
        <label class="check">
          <input id="auto-notch" type="checkbox" checked>
          根据环宽自动设计缺口
        </label>
        <div class="field">
          <label for="notch">缺口尺寸（毫米）</label>
          <input id="notch" type="number" min="0.01" step="0.1" value="10" disabled>
        </div>
        <div class="field">
          <label for="clearance">激光间隙（毫米）</label>
          <input id="clearance" type="number" min="0" step="0.01" value="0.3">
        </div>
        <p id="geometry-info" class="hint"></p>
        <p class="hint">钢板较厚、切缝较大或需要更松的装配时，可以适当增大激光间隙。</p>

        <div class="output">
          <h2>输出</h2>
          <div class="field">
            <label for="output-mode">输出方式</label>
            <select id="output-mode">
              <option value="individual" selected>输出单个零件文件（推荐排版）</option>
              <option value="ring">输出完整环形布局文件</option>
            </select>
            <p class="hint">只生成一个独立 DXF 模板；零件数量用于计算扇区角度。排版时复制此文件即可。</p>
          </div>
          <div class="field">
            <label for="output-dir">输出文件夹</label>
            <input id="output-dir" type="text" value="__DEFAULT_OUTPUT_DIR__">
            <p class="hint">浏览器不能直接读取本机文件夹，请在此输入完整路径。</p>
          </div>
          <label>自动文件名</label>
          <div id="filename" class="filename"></div>
          <div class="button-row">
            <button id="generate" type="button">生成 DXF</button>
            <span id="status">就绪</span>
          </div>
        </div>
      </section>

      <section class="panel preview-panel">
        <h2>预览</h2>
        <svg id="preview" viewBox="0 0 600 600" role="img" aria-label="环形预览"></svg>
        <p class="preview-note">白色线条为圆弧，橙色线条为拼接缺口轮廓。</p>
      </section>
    </div>
  </main>
  <script>
    const AUTO_NOTCH_RATIO = 0.25;
    const MIN_WEB_RATIO = 0.45;
    const $ = id => document.getElementById(id);
    const shapeLabels = { trapezoid: "梯形", rectangular: "矩形" };

    function number(id) { return Number($(id).value); }
    function fmt(value) {
      return Number(value.toFixed(3)).toString();
    }
    function autoNotch(innerRadius, outerRadius, clearance) {
      const wall = outerRadius - innerRadius;
      const nominal = AUTO_NOTCH_RATIO * wall;
      const maximum = (wall - 2 * clearance) * (1 - MIN_WEB_RATIO) / 1.58;
      return Math.min(nominal, maximum);
    }
    function radialPoint(radius, tangent, angleDegrees) {
      const a = angleDegrees * Math.PI / 180;
      return [
        radius * Math.cos(a) + tangent * Math.sin(a),
        radius * Math.sin(a) - tangent * Math.cos(a)
      ];
    }
    function rotatePoint(point, degrees) {
      const a = degrees * Math.PI / 180;
      return [
        point[0] * Math.cos(a) - point[1] * Math.sin(a),
        point[0] * Math.sin(a) + point[1] * Math.cos(a)
      ];
    }
    function makeEdges(innerRadius, outerRadius, sector, notch, shape, clearance) {
      const startAngle = 180 - sector / 2;
      const outerShoulder = shape === "rectangular" ? outerRadius - notch : outerRadius - .99 * notch;
      const innerShoulder = shape === "rectangular" ? innerRadius + notch : innerRadius + .99 * notch;
      const outerStep = shape === "rectangular" ? notch : .79 * notch;
      const innerStep = shape === "rectangular" ? notch : .79 * notch;
      const radii = [outerRadius, outerShoulder, outerRadius - outerStep, innerRadius + innerStep, innerShoulder, innerRadius];
      const tangents = [0, 0, .5 * notch, .5 * notch, 0, 0];
      const start = radii.map((r, i) => radialPoint(r, tangents[i], startAngle));
      const offsets = [0, clearance, clearance, -clearance, -clearance, 0];
      const end = start.map((point, i) => {
        const mating = rotatePoint(point, sector);
        const radius = Math.hypot(mating[0], mating[1]);
        const scale = (radius + offsets[i]) / radius;
        return [mating[0] * scale, mating[1] * scale];
      });
      return [start, end];
    }
    function validValues() {
      const inner = number("inner");
      const outer = number("outer");
      const plate = number("plate-thickness");
      const parts = Math.trunc(number("parts"));
      const clearance = number("clearance");
      if (!(inner > 0)) throw new Error("内径必须大于 0");
      if (!(outer > inner)) throw new Error("外径必须大于内径");
      if (!(plate >= 0)) throw new Error("板厚不能为负数");
      if (!(parts >= 2)) throw new Error("零件数量至少为 2");
      if (!(clearance >= 0)) throw new Error("激光间隙不能为负数");
      const cutInner = inner + 2 * plate;
      const cutOuter = outer - 2 * plate;
      if (!(cutOuter > cutInner)) throw new Error("板厚过大，补偿后的切割外径不大于切割内径");
      let notch = number("notch");
      if ($("auto-notch").checked) notch = autoNotch(cutInner / 2, cutOuter / 2, clearance);
      if (!(notch > 0)) throw new Error("缺口尺寸必须大于 0");
      const wall = (cutOuter - cutInner) / 2;
      if (1.58 * notch >= wall) throw new Error("缺口尺寸对于当前环宽过大");
      return { inner, outer, plate, cutInner, cutOuter, parts, notch, clearance, shape: $("shape").value };
    }
    function valuesWithFilename() {
      const v = validValues();
      const base = `${fmt(v.inner)}x${fmt(v.outer)}+${fmt(v.plate * 2)}补`;
      const mode = $("output-mode").value;
      const filename = mode === "individual"
        ? `${base}.dxf`
        : `${base}_环形布局.dxf`;
      return { ...v, mode, filename, base };
    }
    function svgPoint(point, scale) {
      return `${300 + point[0] * scale},${300 - point[1] * scale}`;
    }
    function polyline(points, scale, color, width) {
      return `<polyline points="${points.map(p => svgPoint(p, scale)).join(" ")}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linejoin="round"/>`;
    }
    function drawPreview() {
      const svg = $("preview");
      try {
        const v = validValues();
        const innerRadius = v.cutInner / 2;
        const outerRadius = v.cutOuter / 2;
        const scale = 250 / outerRadius;
        const sector = 360 / v.parts;
        let markup = `<rect width="600" height="600" fill="#20252b"/>`;
        const [startEdge, endEdge] = makeEdges(innerRadius, outerRadius, sector, v.notch, v.shape, v.clearance);
        for (let i = 0; i < v.parts; i++) {
          const rotation = i * sector;
          const outer = [], inner = [];
          const start = 180 - sector / 2 + rotation;
          const samples = Math.max(12, Math.round(sector / 3));
          for (let j = 0; j <= samples; j++) {
            const angle = (start + sector * j / samples) * Math.PI / 180;
            outer.push([outerRadius * Math.cos(angle), outerRadius * Math.sin(angle)]);
            inner.push([innerRadius * Math.cos(angle), innerRadius * Math.sin(angle)]);
          }
          markup += polyline(outer, scale, "#e8edf2", 1.5);
          markup += polyline(inner, scale, "#a9b4bf", 1.3);
          markup += polyline(startEdge.map(p => rotatePoint(p, rotation)), scale, "#f0a35b", 2);
          markup += polyline(endEdge.map(p => rotatePoint(p, rotation)), scale, "#f0a35b", 2);
        }
        markup += `<text x="16" y="28" fill="#cbd5df" font-size="16">${v.parts} 片　内径 ${fmt(v.inner)}　外径 ${fmt(v.outer)}</text>`;
        svg.innerHTML = markup;
      } catch (error) {
        svg.innerHTML = `<rect width="600" height="600" fill="#20252b"/><text x="16" y="32" fill="#ffb4ab" font-size="16">${error.message}</text>`;
      }
    }
    function refresh() {
      const auto = $("auto-notch").checked;
      $("notch").disabled = auto;
      try {
        const v = valuesWithFilename();
        if (auto) $("notch").value = fmt(v.notch);
        $("filename").textContent = v.filename;
        const wall = (v.cutOuter - v.cutInner) / 2;
        const web = wall - 1.58 * v.notch;
        $("geometry-info").textContent = `环宽：${fmt(wall)} 毫米；${auto ? "自动" : "手动"}${shapeLabels[v.shape]}缺口：${fmt(v.notch)} 毫米；估算连续连接宽度：${fmt(web)} 毫米`;
        setStatus("就绪", "");
      } catch (error) {
        $("filename").textContent = "请输入有效参数";
        $("geometry-info").textContent = error.message;
        setStatus(error.message, "error");
      }
      drawPreview();
    }
    function setStatus(message, className) {
      const status = $("status");
      status.textContent = message;
      status.className = className || "";
    }
    async function generate(overwrite = false) {
      let v;
      try { v = valuesWithFilename(); }
      catch (error) { setStatus(error.message, "error"); return; }
      const data = new URLSearchParams({
        inner: v.inner,
        outer: v.outer,
        plate_thickness: v.plate,
        parts: v.parts,
        notch: v.notch,
        clearance: v.clearance,
        shape: v.shape,
        output_mode: v.mode,
        auto: $("auto-notch").checked ? "1" : "0",
        output_dir: $("output-dir").value,
        overwrite: overwrite ? "1" : "0"
      });
      setStatus("正在生成…", "");
      try {
        const response = await fetch("/generate", { method: "POST", body: data });
        const result = await response.json();
        if (result.exists) {
          const existingMessage = `文件“${result.filename}”已经存在，是否覆盖？`;
          if (confirm(existingMessage)) return generate(true);
          setStatus("已取消", "");
          return;
        }
        if (!result.ok) throw new Error(result.error || "生成失败");
        if (result.mode === "individual") {
          setStatus(`已保存单个零件模板：${result.filename}`, "success");
          alert(`已生成单个零件 DXF 模板：\n${result.path}`);
        } else {
          setStatus(`已保存：${result.filename}`, "success");
          alert(`环形布局 DXF 文件已生成：\n${result.path}`);
        }
      } catch (error) {
        setStatus(error.message, "error");
      }
    }
    ["inner", "outer", "plate-thickness", "parts", "shape", "notch", "clearance", "auto-notch", "output-mode"].forEach(id => $(id).addEventListener("input", refresh));
    $("generate").addEventListener("click", () => generate(false));
    refresh();
  </script>
</body>
</html>
"""


def make_page(default_output_dir: Path) -> bytes:
    escaped_dir = html.escape(str(default_output_dir), quote=True)
    return PAGE_TEMPLATE.replace("__DEFAULT_OUTPUT_DIR__", escaped_dir).encode("utf-8")


def first(params: Mapping[str, list[str]], name: str, default: str = "") -> str:
    values = params.get(name)
    return values[0] if values else default


def json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def make_handler(default_output_dir: Path):
    page = make_page(default_output_dir)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            # Keep the terminal output quiet while the browser is in use.
            return

        def send_bytes(self, content: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/":
                self.send_bytes(page, "text/html; charset=utf-8")
            elif path == "/favicon.ico":
                self.send_bytes(b"", "image/x-icon", status=204)
            else:
                self.send_bytes(b"Not found", "text/plain; charset=utf-8", status=404)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/generate":
                self.send_bytes(b"Not found", "text/plain; charset=utf-8", status=404)
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                params = parse_qs(body)

                inner_diameter = float(first(params, "inner"))
                outer_diameter = float(first(params, "outer"))
                plate_thickness = float(first(params, "plate_thickness", "0"))
                parts = int(first(params, "parts"))
                clearance = float(first(params, "clearance"))
                shape = first(params, "shape", DEFAULT_NOTCH_SHAPE).lower()
                output_mode = first(params, "output_mode", "individual").lower()
                if shape not in NOTCH_SHAPES:
                    raise ValueError("缺口形状必须是梯形或矩形")
                if output_mode not in ("individual", "ring"):
                    raise ValueError("输出方式无效")

                inner_radius, outer_radius = compensated_radii(
                    inner_diameter / 2.0,
                    outer_diameter / 2.0,
                    plate_thickness,
                )
                notch_text = first(params, "notch")
                notch_size = (
                    auto_notch_size(inner_radius, outer_radius, clearance)
                    if first(params, "auto", "0") == "1" or not notch_text
                    else float(notch_text)
                )
                # The browser sends the computed notch value, so automatic
                # and manual modes are both represented explicitly here.
                if inner_diameter <= 0:
                    raise ValueError("内径必须大于 0")
                if outer_diameter <= inner_diameter:
                    raise ValueError("外径必须大于内径")
                if parts < 2:
                    raise ValueError("零件数量至少为 2")

                output_dir = Path(first(params, "output_dir", str(default_output_dir))).expanduser()
                output_dir.mkdir(parents=True, exist_ok=True)

                if output_mode == "individual":
                    output = output_dir / single_piece_filename(
                        inner_diameter,
                        outer_diameter,
                        notch_size,
                        clearance,
                        parts,
                        shape,
                        plate_thickness,
                    )
                    if output.exists() and first(params, "overwrite") != "1":
                        self.send_bytes(
                            json_bytes(
                                {
                                    "ok": False,
                                    "exists": True,
                                    "mode": "individual",
                                    "filename": output.name,
                                }
                            ),
                            "application/json; charset=utf-8",
                        )
                        return

                    generate_piece_dxf(
                        output,
                        parts=parts,
                        inner_radius=inner_radius,
                        outer_radius=outer_radius,
                        notch_size=notch_size,
                        clearance=clearance,
                        notch_shape=shape,
                    )
                    payload = {
                        "ok": True,
                        "mode": "individual",
                        "filename": output.name,
                        "path": str(output),
                        "notch": notch_size,
                    }
                else:
                    output = output_dir / ring_layout_filename(
                        inner_diameter,
                        outer_diameter,
                        notch_size,
                        clearance,
                        parts,
                        shape,
                        plate_thickness,
                    )
                    if output.exists() and first(params, "overwrite") != "1":
                        self.send_bytes(
                            json_bytes(
                                {
                                    "ok": False,
                                    "exists": True,
                                    "mode": "ring",
                                    "filename": output.name,
                                    "count": 1,
                                }
                            ),
                            "application/json; charset=utf-8",
                        )
                        return

                    generate_dxf(
                        output,
                        parts=parts,
                        inner_radius=inner_radius,
                        outer_radius=outer_radius,
                        notch_size=notch_size,
                        clearance=clearance,
                        notch_shape=shape,
                    )
                    payload = {
                        "ok": True,
                        "mode": "ring",
                        "filename": output.name,
                        "path": str(output),
                        "notch": notch_size,
                    }
                self.send_bytes(json_bytes(payload), "application/json; charset=utf-8")
            except (OSError, TypeError, ValueError) as exc:
                self.send_bytes(
                    json_bytes({"ok": False, "error": str(exc)}),
                    "application/json; charset=utf-8",
                    status=400,
                )

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动环形拼接件 DXF 浏览器界面")
    parser.add_argument("--host", default="127.0.0.1", help="本地监听地址")
    parser.add_argument("--port", type=int, default=0, help="端口；0 表示自动选择")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    default_output_dir = Path(__file__).resolve().parent
    server = ThreadingHTTPServer((args.host, args.port), make_handler(default_output_dir))
    url = f"http://{args.host}:{server.server_port}/"
    print(f"环形拼接件 DXF 生成器已启动：{url}")
    print("请保持此终端窗口运行；按 Ctrl+C 停止程序。")

    if not args.no_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n程序已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
