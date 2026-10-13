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
    DEFAULT_CONNECTOR_CORNER_RADIUS,
    DEFAULT_LASER_CLEARANCE,
    DEFAULT_MALE_HEIGHT,
    DEFAULT_MALE_LOWER_BASE_WIDTH,
    DEFAULT_MALE_TOP_BASE_WIDTH,
    compensated_radii,
    generate_dxf,
    generate_piece_dxf,
    ring_layout_filename,
    rounded_connector_path,
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
        self.root.title("塑料护盒拼接件 DXF 生成器")
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
        self.male_lower_base_var = tk.StringVar(value=format_value(DEFAULT_MALE_LOWER_BASE_WIDTH))
        self.male_top_base_var = tk.StringVar(value=format_value(DEFAULT_MALE_TOP_BASE_WIDTH))
        self.male_height_var = tk.StringVar(value=format_value(DEFAULT_MALE_HEIGHT))
        self.clearance_var = tk.StringVar(value=format_value(DEFAULT_LASER_CLEARANCE))
        self.output_dir_var = tk.StringVar(value=str(default_output_directory()))
        self.output_mode_var = tk.StringVar(value="单个零件模板（推荐排版）")
        self.split_paths_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="就绪")
        self.geometry_var = tk.StringVar(value="")
        self.filename_var = tk.StringVar(value="")
        self._updating_preview = False

        self.build_ui()
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

        title = ttk.Label(controls, text="塑料护盒参数", font=("Microsoft YaHei UI", 16, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))

        row = 1
        row = self.add_length_spinbox(controls, row, "内径（毫米）", self.inner_var)
        row = self.add_length_spinbox(controls, row, "外径（毫米）", self.outer_var)
        row = self.add_length_spinbox(controls, row, "板厚（毫米）", self.plate_var)
        ttk.Label(
            controls,
            text="切割内径=输入内径+2×板厚；切割外径=输入外径−2×板厚",
            wraplength=330,
            foreground="#59636e",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 10))
        row += 1
        row = self.add_integer_spinbox(controls, row, "零件数量", self.parts_var)

        ttk.Label(controls, text="梯形公头连接", font=("Microsoft YaHei UI", 13, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(8, 4)
        )
        row += 1
        row = self.add_length_spinbox(controls, row, "公头下底宽度（毫米）", self.male_lower_base_var)
        row = self.add_length_spinbox(controls, row, "公头上底宽度（毫米）", self.male_top_base_var)
        row = self.add_length_spinbox(controls, row, "公头伸出高度（毫米）", self.male_height_var)
        row = self.add_length_spinbox(controls, row, "激光间隙（毫米）", self.clearance_var)

        ttk.Label(
            controls,
            text=f"公头三边均可按 0.1 mm 调整；四个梯形转角固定为 R{format_value(DEFAULT_CONNECTOR_CORNER_RADIUS)} mm。",
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

        ttk.Checkbutton(
            controls,
            text="内外轮廓分成两条切割路径",
            variable=self.split_paths_var,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 3))
        ttk.Label(
            controls,
            text="外弧与一侧咬合边为一条路径，内弧与另一侧咬合边为另一条路径。",
            wraplength=330,
            foreground="#59636e",
        ).grid(row=row + 1, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 2

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

        ttk.Label(controls, text="输出文件名").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(controls, textvariable=self.filename_var, width=27).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=5
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
            self.male_lower_base_var,
            self.male_top_base_var,
            self.male_height_var,
            self.clearance_var,
        ):
            variable.trace_add("write", lambda *_args: self.update_preview())

    def add_length_spinbox(
        self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar
    ) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Spinbox(
            parent,
            textvariable=variable,
            from_=0.0,
            to=100000.0,
            increment=0.1,
            format="%.1f",
            width=25,
        ).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=5
        )
        return row + 1

    def add_integer_spinbox(
        self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar
    ) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Spinbox(parent, textvariable=variable, from_=2, to=360, increment=1, width=25).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=5
        )
        return row + 1

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

        def tenth_mm(variable: tk.StringVar, label: str) -> float:
            value = number(variable, label)
            rounded = round(value * 10.0) / 10.0
            if not math.isclose(value, rounded, abs_tol=1e-8):
                raise ValueError(f"{label}必须按 0.1 mm 递增")
            return rounded

        inner = tenth_mm(self.inner_var, "内径")
        outer = tenth_mm(self.outer_var, "外径")
        plate = tenth_mm(self.plate_var, "板厚")
        parts_value = number(self.parts_var, "零件数量")
        clearance = tenth_mm(self.clearance_var, "激光间隙")
        male_lower_base = tenth_mm(self.male_lower_base_var, "公头下底宽度")
        male_top_base = tenth_mm(self.male_top_base_var, "公头上底宽度")
        male_height = tenth_mm(self.male_height_var, "公头伸出高度")
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
        if male_lower_base <= 0:
            raise ValueError("公头下底宽度必须大于 0")
        if male_top_base <= 0 or male_top_base > male_lower_base:
            raise ValueError("公头上底宽度必须大于 0 且不超过公头下底宽度")
        if male_height <= 0:
            raise ValueError("公头伸出高度必须大于 0")

        parts = int(parts_value)
        cut_inner, cut_outer = compensated_radii(inner / 2.0, outer / 2.0, plate)
        wall = cut_outer - cut_inner
        if male_lower_base > wall:
            raise ValueError("公头下底宽度不能超过补偿后的切割环宽")
        shape = "trapezoid"
        mode = "individual" if self.output_mode_var.get().startswith("单个") else "ring"
        return {
            "inner": inner,
            "outer": outer,
            "plate": plate,
            "parts": parts,
            "clearance": clearance,
            "cut_inner": cut_inner,
            "cut_outer": cut_outer,
            # The filename intentionally ignores connector parameters.  Keep
            # this compatibility value for the existing filename helpers.
            "notch": male_lower_base,
            "male_lower_base": male_lower_base,
            "male_top_base": male_top_base,
            "male_height": male_height,
            "shape": shape,
            "mode": mode,
            "split_paths": self.split_paths_var.get(),
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

    def output_filename(self) -> str:
        """Return a Windows-safe, user-entered DXF filename."""

        filename = self.filename_var.get().strip()
        if not filename:
            raise ValueError("输出文件名不能为空")
        if not filename.lower().endswith(".dxf"):
            raise ValueError("输出文件名必须以 .dxf 结尾")
        if any(character in filename for character in '<>:"/\\|?*'):
            raise ValueError("输出文件名不能包含 Windows 不支持的字符")
        if filename.endswith((".", " ")):
            raise ValueError("输出文件名不能以句点或空格结尾")
        return filename

    def update_preview(self) -> None:
        if not hasattr(self, "canvas") or self._updating_preview:
            return
        self._updating_preview = True
        try:
            values = self.values()
            # Keep the editable name simple: any parameter change refreshes
            # the suggested filename.  The user may overwrite it before
            # clicking Generate DXF.
            self.filename_var.set(self.filename_for(values))
            wall = values["cut_outer"] - values["cut_inner"]
            material_each_side = (wall - float(values["male_lower_base"])) / 2.0
            self.geometry_var.set(
                f"实际切割环宽：{format_value(wall)} mm；"
                f"公头下底：{format_value(values['male_lower_base'])} mm；"
                f"上底：{format_value(values['male_top_base'])} mm；"
                f"伸出：{format_value(values['male_height'])} mm；"
                f"R{format_value(DEFAULT_CONNECTOR_CORNER_RADIUS)}；"
                f"两侧材料：各 {format_value(material_each_side)} mm"
            )
            self.status_var.set("就绪")
            self.draw_preview(values)
        except (OSError, ValueError, TypeError) as exc:
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
            male_lower_base_width=float(values["male_lower_base"]),
            male_top_base_width=float(values["male_top_base"]),
            male_height=float(values["male_height"]),
        )

        def point(point_value: tuple[float, float], rotation: float = 0.0) -> tuple[float, float]:
            x, y = rotate(point_value, rotation)
            return cx + x * scale, cy - y * scale

        def bulge_points(start: tuple[float, float], end: tuple[float, float], bulge: float) -> list[tuple[float, float]]:
            if abs(bulge) <= 1e-10:
                return [start, end]
            dx, dy = end[0] - start[0], end[1] - start[1]
            chord = math.hypot(dx, dy)
            midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
            left_normal = (-dy / chord, dx / chord)
            offset = chord * (1.0 - bulge * bulge) / (4.0 * bulge)
            arc_center = (
                midpoint[0] + left_normal[0] * offset,
                midpoint[1] + left_normal[1] * offset,
            )
            radius = chord * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
            start_angle = math.atan2(start[1] - arc_center[1], start[0] - arc_center[0])
            sweep = 4.0 * math.atan(bulge)
            count = max(6, int(abs(math.degrees(sweep)) / 3.0))
            return [
                (
                    arc_center[0] + radius * math.cos(start_angle + sweep * index / count),
                    arc_center[1] + radius * math.sin(start_angle + sweep * index / count),
                )
                for index in range(count + 1)
            ]

        def draw_path(
            vertices: tuple[tuple[float, float], ...],
            bulges: tuple[float, ...],
            ring_colour: str,
        ) -> None:
            for index, (start, end, bulge) in enumerate(zip(vertices, vertices[1:], bulges)):
                points = bulge_points(start, end, bulge)
                canvas.create_line(
                    *(coordinate for point_value in points for coordinate in point(point_value)),
                    fill=ring_colour if index == 0 else "#f0a35b",
                    width=2,
                )

        for index in range(int(values["parts"])):
            rotation = index * sector
            arc_bulge = math.tan(math.radians(sector) / 4.0)
            outer_path, outer_bulges = rounded_connector_path(
                [rotate(piece.outer_start, rotation)]
                + [rotate(point_value, rotation) for point_value in piece.end_edge],
                [arc_bulge] + [0.0] * len(piece.end_edge),
                "trapezoid",
                DEFAULT_CONNECTOR_CORNER_RADIUS,
            )
            inner_path, inner_bulges = rounded_connector_path(
                [rotate(piece.inner_end, rotation)]
                + [rotate(point_value, rotation) for point_value in reversed(piece.start_edge)],
                [-arc_bulge] + [0.0] * len(piece.start_edge),
                "trapezoid",
                DEFAULT_CONNECTOR_CORNER_RADIUS,
            )
            draw_path(outer_path, outer_bulges, "#e8edf2")
            draw_path(inner_path, inner_bulges, "#a9b4bf")

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
            output = output_dir / self.output_filename()
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
                "male_lower_base_width": values["male_lower_base"],
                "male_top_base_width": values["male_top_base"],
                "male_height": values["male_height"],
                "connector_corner_radius": DEFAULT_CONNECTOR_CORNER_RADIUS,
                "split_paths": values["split_paths"],
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
