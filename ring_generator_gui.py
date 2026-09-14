#!/usr/bin/env python3
"""Standalone Chinese Tkinter desktop GUI for the ring DXF generator."""

from __future__ import annotations

import math
import os
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from generate_ring import (
    DEFAULT_LASER_CLEARANCE,
    DEFAULT_NOTCH_SIZE,
    DEFAULT_NOTCH_SHAPE,
    NOTCH_SHAPE_LABELS,
    auto_notch_size,
    compensated_radii,
    generate_dxf,
    generate_piece_dxf,
    ring_layout_filename,
    resized_piece,
    rotate,
    single_piece_filename,
)


def format_value(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


def default_output_directory() -> Path:
    """Use a writable folder beside the EXE, never PyInstaller's _internal."""

    application_dir = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    return application_dir / "输出"


class SingleInstance:
    """Keep accidental double-clicks from starting duplicate GUI processes."""

    def __init__(self) -> None:
        self.path = Path(tempfile.gettempdir()) / "ring_generator_tkinter.lock"
        self.handle = None

    def acquire(self) -> bool:
        try:
            self.handle = self.path.open("a+")
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                self.handle.write("0")
                self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (ImportError, OSError):
            if self.handle is not None:
                self.handle.close()
                self.handle = None
            return False

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        finally:
            self.handle.close()
            self.handle = None


class RingGeneratorApp:
    def __init__(self, root: tk.Tk, instance: SingleInstance) -> None:
        self.root = root
        self.instance = instance
        self.root.title("环形拼接件 DXF 生成器")
        self.root.geometry("1160x780")
        self.root.minsize(980, 680)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        try:
            ttk.Style(self.root).theme_use("vista")
        except tk.TclError:
            pass

        self.inner_var = tk.StringVar(value="203")
        self.outer_var = tk.StringVar(value="262")
        self.plate_var = tk.StringVar(value="0")
        self.parts_var = tk.StringVar(value="4")
        self.shape_var = tk.StringVar(value=NOTCH_SHAPE_LABELS[DEFAULT_NOTCH_SHAPE])
        self.auto_notch_var = tk.BooleanVar(value=True)
        self.notch_var = tk.StringVar(value=format_value(DEFAULT_NOTCH_SIZE))
        self.clearance_var = tk.StringVar(value=format_value(DEFAULT_LASER_CLEARANCE))
        self.output_dir_var = tk.StringVar(value=str(default_output_directory()))
        self.output_mode_var = tk.StringVar(value="单个零件模板（推荐排版）")
        self.status_var = tk.StringVar(value="就绪")
        self.geometry_var = tk.StringVar(value="")
        self.filename_var = tk.StringVar(value="")
        self._updating_preview = False

        self.build_ui()
        self.update_notch_state()
        self.update_preview()

    def build_ui(self) -> None:
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        controls = ttk.Frame(self.root, padding=16)
        controls.grid(row=0, column=0, sticky="ns")
        preview_panel = ttk.Frame(self.root, padding=(0, 16, 16, 16))
        preview_panel.grid(row=0, column=1, sticky="nsew")
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(1, weight=1)

        title = ttk.Label(controls, text="环形参数", font=("Microsoft YaHei UI", 16, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))

        row = 1
        row = self.add_entry(controls, row, "内径（毫米）", self.inner_var)
        row = self.add_entry(controls, row, "外径（毫米）", self.outer_var)
        row = self.add_entry(controls, row, "板厚（毫米）", self.plate_var)
        ttk.Label(
            controls,
            text="切割内径=输入内径+2×板厚；切割外径=输入外径−2×板厚",
            wraplength=330,
            foreground="#59636e",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 10))
        row += 1
        row = self.add_entry(controls, row, "零件数量", self.parts_var)

        ttk.Label(controls, text="缺口形状").grid(row=row, column=0, sticky="w", pady=5)
        self.shape_box = ttk.Combobox(
            controls,
            textvariable=self.shape_var,
            values=["梯形", "矩形"],
            state="readonly",
            width=25,
        )
        self.shape_box.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
        self.shape_box.bind("<<ComboboxSelected>>", lambda _event: self.update_preview())
        row += 1

        self.auto_check = ttk.Checkbutton(
            controls,
            text="根据环宽自动设计缺口（比例 25%）",
            variable=self.auto_notch_var,
            command=self.update_notch_state,
        )
        self.auto_check.grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 3))
        row += 1
        notch_row = row
        row = self.add_entry(controls, row, "缺口尺寸（毫米）", self.notch_var)
        self.notch_entry = controls.grid_slaves(row=notch_row, column=1)[0]
        row = self.add_entry(controls, row, "激光间隙（毫米）", self.clearance_var)

        ttk.Label(
            controls,
            text="默认激光间隙 0.3 mm。梯形缺口适合自定位；矩形缺口便于规则点焊。",
            wraplength=330,
            foreground="#59636e",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 12))
        row += 1

        ttk.Separator(controls).grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        row += 1
        ttk.Label(controls, text="输出", font=("Microsoft YaHei UI", 13, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        row += 1

        ttk.Label(controls, text="输出方式").grid(row=row, column=0, sticky="w", pady=5)
        self.mode_box = ttk.Combobox(
            controls,
            textvariable=self.output_mode_var,
            values=["单个零件模板（推荐排版）", "完整环形布局"],
            state="readonly",
            width=25,
        )
        self.mode_box.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
        self.mode_box.bind("<<ComboboxSelected>>", lambda _event: self.update_preview())
        row += 1

        ttk.Label(controls, text="输出文件夹").grid(row=row, column=0, sticky="w", pady=5)
        output_frame = ttk.Frame(controls)
        output_frame.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
        output_frame.columnconfigure(0, weight=1)
        ttk.Entry(output_frame, textvariable=self.output_dir_var, width=25).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(output_frame, text="选择…", command=self.choose_output_directory).grid(
            row=0, column=1, padx=(6, 0)
        )
        row += 1

        ttk.Label(controls, text="自动文件名").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Label(controls, textvariable=self.filename_var, foreground="#234e70", wraplength=260).grid(
            row=row, column=1, columnspan=2, sticky="w", pady=5
        )
        row += 1

        self.geometry_label = ttk.Label(
            controls, textvariable=self.geometry_var, wraplength=330, foreground="#59636e"
        )
        self.geometry_label.grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 12))
        row += 1

        ttk.Button(controls, text="生成 DXF", command=self.generate).grid(
            row=row, column=0, columnspan=3, sticky="ew", ipady=5, pady=(4, 8)
        )
        row += 1
        ttk.Label(controls, textvariable=self.status_var, wraplength=330).grid(
            row=row, column=0, columnspan=3, sticky="w"
        )
        for column in (1, 2):
            controls.columnconfigure(column, weight=1)

        ttk.Label(preview_panel, text="预览", font=("Microsoft YaHei UI", 16, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.canvas = tk.Canvas(
            preview_panel,
            background="#20252b",
            highlightthickness=0,
            width=720,
            height=680,
        )
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _event: self.update_preview())

        for variable in (
            self.inner_var,
            self.outer_var,
            self.plate_var,
            self.parts_var,
            self.notch_var,
            self.clearance_var,
        ):
            variable.trace_add("write", lambda *_args: self.update_preview())

    def add_entry(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=variable, width=27).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=5
        )
        return row + 1

    def update_notch_state(self) -> None:
        if hasattr(self, "notch_entry"):
            self.notch_entry.configure(state="disabled" if self.auto_notch_var.get() else "normal")
        self.update_preview()

    def choose_output_directory(self) -> None:
        current = Path(self.output_dir_var.get()).expanduser()
        initial = current if current.exists() else default_output_directory()
        selected = filedialog.askdirectory(title="选择 DXF 输出文件夹", initialdir=str(initial))
        if selected:
            self.output_dir_var.set(selected)

    def values(self) -> dict[str, object]:
        def number(variable: tk.StringVar, label: str) -> float:
            try:
                value = float(variable.get())
            except ValueError as exc:
                raise ValueError(f"{label}必须是数字") from exc
            if not math.isfinite(value):
                raise ValueError(f"{label}必须是有效数字")
            return value

        inner = number(self.inner_var, "内径")
        outer = number(self.outer_var, "外径")
        plate = number(self.plate_var, "板厚")
        parts_value = number(self.parts_var, "零件数量")
        clearance = number(self.clearance_var, "激光间隙")
        if inner <= 0:
            raise ValueError("内径必须大于 0")
        if outer <= inner:
            raise ValueError("外径必须大于内径")
        if plate < 0:
            raise ValueError("板厚不能为负数")
        if parts_value < 2 or parts_value != int(parts_value):
            raise ValueError("零件数量必须是大于等于 2 的整数")
        if clearance < 0:
            raise ValueError("激光间隙不能为负数")

        parts = int(parts_value)
        cut_inner, cut_outer = compensated_radii(inner / 2.0, outer / 2.0, plate)
        notch = (
            auto_notch_size(cut_inner, cut_outer, clearance)
            if self.auto_notch_var.get()
            else number(self.notch_var, "缺口尺寸")
        )
        if notch <= 0:
            raise ValueError("缺口尺寸必须大于 0")
        shape = "trapezoid" if self.shape_var.get() == "梯形" else "rectangular"
        mode = "individual" if self.output_mode_var.get().startswith("单个") else "ring"
        return {
            "inner": inner,
            "outer": outer,
            "plate": plate,
            "parts": parts,
            "clearance": clearance,
            "cut_inner": cut_inner,
            "cut_outer": cut_outer,
            "notch": notch,
            "shape": shape,
            "mode": mode,
        }

    def filename_for(self, values: dict[str, object]) -> str:
        function = single_piece_filename if values["mode"] == "individual" else ring_layout_filename
        return function(
            values["inner"],
            values["outer"],
            values["notch"],
            values["clearance"],
            values["parts"],
            values["shape"],
            values["plate"],
        )

    def update_preview(self) -> None:
        if not hasattr(self, "canvas") or self._updating_preview:
            return
        self._updating_preview = True
        try:
            values = self.values()
            if self.auto_notch_var.get():
                self.notch_var.set(format_value(values["notch"]))
            self.filename_var.set(self.filename_for(values))
            wall = values["cut_outer"] - values["cut_inner"]
            web_factor = 1.58 if values["shape"] == "trapezoid" else 2.0
            web = wall - web_factor * values["notch"]
            shape_label = NOTCH_SHAPE_LABELS[values["shape"]]
            self.geometry_var.set(
                f"实际切割环宽：{format_value(wall)} mm；"
                f"自动{shape_label}缺口：{format_value(values['notch'])} mm；"
                f"估算连续材料：{format_value(web)} mm"
            )
            self.status_var.set("就绪")
            self.draw_preview(values)
        except (OSError, ValueError, TypeError) as exc:
            self.filename_var.set("请输入有效参数")
            self.geometry_var.set(str(exc))
            self.status_var.set("参数需要检查")
            self.canvas.delete("all")
        finally:
            self._updating_preview = False

    def draw_preview(self, values: dict[str, object]) -> None:
        canvas = self.canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 500)
        height = max(canvas.winfo_height(), 500)
        cx, cy = width / 2.0, height / 2.0
        outer_radius = float(values["cut_outer"])
        inner_radius = float(values["cut_inner"])
        scale = min(width, height) * 0.42 / outer_radius
        sector = 360.0 / int(values["parts"])
        piece = resized_piece(
            inner_radius,
            outer_radius,
            sector,
            notch_size=float(values["notch"]),
            clearance=float(values["clearance"]),
            notch_shape=str(values["shape"]),
        )

        def point(point_value: tuple[float, float], rotation: float = 0.0) -> tuple[float, float]:
            x, y = rotate(point_value, rotation)
            return cx + x * scale, cy - y * scale

        def arc_points(radius: float, start: float, end: float) -> list[float]:
            count = max(16, int(abs(end - start) / 3.0))
            points: list[float] = []
            for index in range(count + 1):
                angle = math.radians(start + (end - start) * index / count)
                points.extend(
                    (cx + radius * math.cos(angle) * scale, cy - radius * math.sin(angle) * scale)
                )
            return points

        for index in range(int(values["parts"])):
            rotation = index * sector
            start_angle = 180.0 - sector / 2.0 + rotation
            end_angle = 180.0 + sector / 2.0 + rotation
            canvas.create_line(*arc_points(outer_radius, start_angle, end_angle), fill="#e8edf2", width=2)
            canvas.create_line(*arc_points(inner_radius, start_angle, end_angle), fill="#a9b4bf", width=2)
            for edge in (piece.start_edge, piece.end_edge):
                for start, end in zip(edge, edge[1:]):
                    canvas.create_line(
                        *point(start, rotation),
                        *point(end, rotation),
                        fill="#f0a35b",
                        width=2,
                    )

        canvas.create_text(
            14,
            18,
            anchor="w",
            fill="#cbd5df",
            font=("Microsoft YaHei UI", 12),
            text=f"{values['parts']} 片  内径 {format_value(values['inner'])}  外径 {format_value(values['outer'])}",
        )

    def generate(self) -> None:
        try:
            values = self.values()
            output_dir = Path(self.output_dir_var.get()).expanduser()
            if not str(output_dir).strip():
                raise ValueError("输出文件夹不能为空")
            output_dir.mkdir(parents=True, exist_ok=True)
            output = output_dir / self.filename_for(values)
            if output.exists() and not messagebox.askyesno(
                "文件已存在", f"文件已存在：\n{output}\n\n是否覆盖？", parent=self.root
            ):
                return

            common = {
                "parts": values["parts"],
                "inner_radius": values["cut_inner"],
                "outer_radius": values["cut_outer"],
                "notch_size": values["notch"],
                "clearance": values["clearance"],
                "notch_shape": values["shape"],
            }
            if values["mode"] == "individual":
                generate_piece_dxf(output, **common)
                message = f"单个零件模板已生成：\n{output}"
            else:
                generate_dxf(output, **common)
                message = f"完整环形布局已生成：\n{output}"
            self.status_var.set("生成成功")
            messagebox.showinfo("生成完成", message, parent=self.root)
        except (OSError, TypeError, ValueError) as exc:
            self.status_var.set("生成失败")
            messagebox.showerror("生成失败", str(exc), parent=self.root)

    def close(self) -> None:
        self.instance.release()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    root.withdraw()
    instance = SingleInstance()
    if not instance.acquire():
        messagebox.showwarning("程序已运行", "环形拼接件 DXF 生成器已经在运行中。", parent=root)
        root.destroy()
        return
    try:
        root.deiconify()
        RingGeneratorApp(root, instance)
        root.mainloop()
    finally:
        instance.release()


if __name__ == "__main__":
    main()
