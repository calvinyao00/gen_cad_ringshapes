#!/usr/bin/env python3
"""Generate keyed annular sectors as a laser-cutter DXF.

The default geometry is measured from the supplied DXF file:

    199 266+4补.dxf

The source sector is a 90-degree annular sector with an outer radius of 131
mm and an inner radius of 101.5 mm.  Its two ends use slightly different
keyed profiles.  The number of parts, notch size, and laser clearance are
configurable, as is the notch shape (trapezoid or rectangular); when the
number of parts is not four, the profile is angularly resized so all parts
still close into one ring.

The writer intentionally uses ARC and LINE entities, matching the source
DXF, so no third-party DXF package is required.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


Point = tuple[float, float]


SOURCE_INNER_RADIUS = 101.5
SOURCE_OUTER_RADIUS = 131.0
SOURCE_START_ANGLE = 135.0
SOURCE_END_ANGLE = 225.0
SOURCE_CENTER_ANGLE = 180.0
SOURCE_SECTOR_ANGLE = SOURCE_END_ANGLE - SOURCE_START_ANGLE
DEFAULT_NOTCH_SIZE = 10.0
DEFAULT_LASER_CLEARANCE = 0.3
DEFAULT_NOTCH_SHAPE = "trapezoid"
NOTCH_SHAPES = ("trapezoid", "rectangular")
NOTCH_SHAPE_LABELS = {"trapezoid": "梯形", "rectangular": "矩形"}
# Automatic notch size as a fraction of the compensated radial ring width.
# A smaller value leaves more material for spot-welded joints.
AUTO_NOTCH_RATIO = 0.25
MIN_REMAINING_WEB_RATIO = 0.45


@dataclass(frozen=True)
class PieceGeometry:
    """One sector in local coordinates, centered at (0, 0)."""

    outer_start: Point
    outer_end: Point
    inner_start: Point
    inner_end: Point
    start_edge: tuple[Point, ...]
    end_edge: tuple[Point, ...]


def rotate(point: Point, degrees: float) -> Point:
    """Rotate a point counter-clockwise around the origin."""

    angle = math.radians(degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    x, y = point
    return (x * cosine - y * sine, x * sine + y * cosine)


def add(point: Point, center: Point) -> Point:
    return (point[0] + center[0], point[1] + center[1])


def polar_radius(point: Point) -> float:
    return math.hypot(point[0], point[1])


def compensated_radii(
    inner_radius: float,
    outer_radius: float,
    plate_thickness: float = 0.0,
) -> tuple[float, float]:
    """Apply the plate-thickness compensation to both ring diameters.

    The requested finished dimensions are the input dimensions. The cutting
    geometry uses a larger inner diameter and a smaller outer diameter by
    two times the entered plate thickness.
    """

    if plate_thickness < 0:
        raise ValueError("板厚不能为负数")
    cut_inner_radius = inner_radius + plate_thickness
    cut_outer_radius = outer_radius - plate_thickness
    if cut_outer_radius <= cut_inner_radius:
        raise ValueError("板厚过大，补偿后的切割外径不大于切割内径")
    return cut_inner_radius, cut_outer_radius


def resized_piece(
    inner_radius: float,
    outer_radius: float,
    sector_angle: float,
    notch_size: float | None = None,
    clearance: float = DEFAULT_LASER_CLEARANCE,
    notch_shape: str = DEFAULT_NOTCH_SHAPE,
) -> PieceGeometry:
    """Build one sector with adjustable notch size and mating clearance.

    The source end profile, expressed in radial/tangential coordinates, is:

    * trapezoidal radial steps of approximately 0.99 and 0.79 times the
      notch size, or equal radial steps for a rectangular notch;
    * a 0.5-notch tangential key width;
    * a clearance offset on the mating edge.

    At the defaults (10 mm notch and 0.3 mm clearance), this reproduces the
    supplied DXF profile.  The end profile is intentionally asymmetric so
    neighboring rotated parts mate with clearance rather than overlapping.
    """

    if inner_radius <= 0:
        raise ValueError("内半径必须大于 0")
    if outer_radius <= inner_radius:
        raise ValueError("外半径必须大于内半径")
    if sector_angle <= 0 or sector_angle > 360:
        raise ValueError("扇区角度必须大于 0 且不超过 360 度")
    if notch_size is None:
        notch_size = auto_notch_size(inner_radius, outer_radius, clearance)
    if notch_size <= 0:
        raise ValueError("缺口尺寸必须大于 0")
    if clearance < 0:
        raise ValueError("激光间隙不能为负数")
    notch_shape = notch_shape.lower()
    if notch_shape not in NOTCH_SHAPES:
        raise ValueError("缺口形状必须是梯形或矩形")

    wall = outer_radius - inner_radius
    if 1.58 * notch_size >= wall:
        raise ValueError("缺口尺寸对于当前环宽过大，请减小缺口或增大外径")

    start_angle = SOURCE_CENTER_ANGLE - sector_angle / 2.0

    def basis_point(radius: float, tangent: float) -> Point:
        angle = math.radians(start_angle)
        radial = (math.cos(angle), math.sin(angle))
        # This tangent direction matches the keyed profile in the source DXF.
        tangent_axis = (math.sin(angle), -math.cos(angle))
        return (
            radius * radial[0] + tangent * tangent_axis[0],
            radius * radial[1] + tangent * tangent_axis[1],
        )

    # The source profile is trapezoidal. A rectangular profile keeps the two
    # shoulder pairs at constant radii, creating square transitions.
    if notch_shape == "rectangular":
        outer_shoulder = outer_radius - notch_size
        inner_shoulder = inner_radius + notch_size
    else:
        outer_shoulder = outer_radius - 0.99 * notch_size
        inner_shoulder = inner_radius + 0.99 * notch_size

    radial_values = (
        outer_radius,
        outer_shoulder,
        outer_radius - (0.79 * notch_size if notch_shape == "trapezoid" else notch_size),
        inner_radius + (0.79 * notch_size if notch_shape == "trapezoid" else notch_size),
        inner_shoulder,
        inner_radius,
    )

    tangent_values = (0.0, 0.0, 0.5 * notch_size, 0.5 * notch_size, 0.0, 0.0)
    start_edge = tuple(
        basis_point(radius, tangent)
        for radius, tangent in zip(radial_values, tangent_values)
    )

    # The opposite edge is the same key rotated to the next sector, with
    # alternating radial offsets that create the specified laser clearance.
    clearance_offsets = (0.0, clearance, clearance, -clearance, -clearance, 0.0)
    end_edge: list[Point] = []
    for point, offset in zip(start_edge, clearance_offsets):
        mating = rotate(point, sector_angle)
        radius = polar_radius(mating)
        scale = (radius + offset) / radius
        end_edge.append((mating[0] * scale, mating[1] * scale))

    outer_start = basis_point(outer_radius, 0.0)
    inner_start = basis_point(inner_radius, 0.0)

    return PieceGeometry(
        outer_start=outer_start,
        outer_end=rotate(outer_start, sector_angle),
        inner_start=inner_start,
        inner_end=rotate(inner_start, sector_angle),
        start_edge=start_edge,
        end_edge=tuple(end_edge),
    )


def auto_notch_size(
    inner_radius: float,
    outer_radius: float,
    clearance: float = DEFAULT_LASER_CLEARANCE,
) -> float:
    """Choose a notch size from the radial ring width.

    The automatic notch starts at 25% of the radial wall. The result is
    capped so the keyed profile keeps at least 45% of the radial wall as a
    continuous web, with clearance included as a small additional margin.
    """

    if inner_radius <= 0:
        raise ValueError("内半径必须大于 0")
    if outer_radius <= inner_radius:
        raise ValueError("外半径必须大于内半径")
    if clearance < 0:
        raise ValueError("激光间隙不能为负数")

    wall = outer_radius - inner_radius
    nominal = AUTO_NOTCH_RATIO * wall
    available_wall = wall - 2.0 * clearance
    maximum = available_wall * (1.0 - MIN_REMAINING_WEB_RATIO) / 1.58
    if maximum <= 0:
        raise ValueError("环宽对于当前激光间隙过薄")
    return min(nominal, maximum)


def format_value(value: float) -> str:
    """Format a measurement for use in a filename."""

    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


def default_filename(
    inner_diameter: float,
    outer_diameter: float,
    notch_size: float,
    clearance: float,
    parts: int,
    notch_shape: str = DEFAULT_NOTCH_SHAPE,
    plate_thickness: float = 0.0,
) -> str:
    """Return the requested compact filename based on ID, OD, and plate."""

    notch_shape = notch_shape.lower()
    if notch_shape not in NOTCH_SHAPES:
        raise ValueError("缺口形状必须是梯形或矩形")
    # Keep the filename limited to the requested ID, OD, and total radial
    # compensation. A 3 mm plate allowance on each side is recorded as
    # 203x262+6补 because the two-sided diameter compensation totals 6 mm.
    return (
        f"{format_value(inner_diameter)}"
        f"x{format_value(outer_diameter)}"
        f"+{format_value(plate_thickness * 2)}补.dxf"
    )


def individual_filename(
    inner_diameter: float,
    outer_diameter: float,
    notch_size: float,
    clearance: float,
    parts: int,
    piece_number: int,
    notch_shape: str = DEFAULT_NOTCH_SHAPE,
    plate_thickness: float = 0.0,
) -> str:
    """Return the filename for one independently laid-out sector."""

    base = default_filename(
        inner_diameter,
        outer_diameter,
        notch_size,
        clearance,
        parts,
        notch_shape,
        plate_thickness,
    )
    if piece_number < 1 or piece_number > parts:
        raise ValueError("零件编号超出范围")
    return f"{base[:-4]}_第{piece_number:02d}片.dxf"


def single_piece_filename(
    inner_diameter: float,
    outer_diameter: float,
    notch_size: float,
    clearance: float,
    parts: int,
    notch_shape: str = DEFAULT_NOTCH_SHAPE,
    plate_thickness: float = 0.0,
) -> str:
    """Return the filename for one reusable sector template."""

    base = default_filename(
        inner_diameter,
        outer_diameter,
        notch_size,
        clearance,
        parts,
        notch_shape,
        plate_thickness,
    )
    return base


def ring_layout_filename(
    inner_diameter: float,
    outer_diameter: float,
    notch_size: float,
    clearance: float,
    parts: int,
    notch_shape: str = DEFAULT_NOTCH_SHAPE,
    plate_thickness: float = 0.0,
) -> str:
    """Return the filename for a complete ring layout."""

    base = default_filename(
        inner_diameter,
        outer_diameter,
        notch_size,
        clearance,
        parts,
        notch_shape,
        plate_thickness,
    )
    return f"{base[:-4]}_环形布局.dxf"


def fmt(value: float) -> str:
    """Format a DXF number compactly but with enough precision for cutting."""

    return f"{value:.9f}".rstrip("0").rstrip(".") or "0"


class DxfWriter:
    """Small ASCII DXF writer for the entities used by this design."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def pair(self, code: int, value: object) -> None:
        self.lines.extend((str(code), str(value)))

    def header(self) -> None:
        self.pair(0, "SECTION")
        self.pair(2, "HEADER")
        self.pair(9, "$ACADVER")
        # R12/AC1009 is intentionally used here because AutoCAD 2016 can
        # open it without the owner dictionaries required by newer DXF
        # versions. Laser cutting only needs ARC and LINE entities.
        self.pair(1, "AC1009")
        self.pair(9, "$INSUNITS")
        self.pair(70, 4)  # millimeters
        self.pair(0, "ENDSEC")
        self.pair(0, "SECTION")
        self.pair(2, "ENTITIES")

    def arc(self, center: Point, radius: float, start_angle: float, end_angle: float) -> None:
        self.pair(0, "ARC")
        self.pair(8, "0")
        self.pair(10, fmt(center[0]))
        self.pair(20, fmt(center[1]))
        self.pair(30, "0")
        self.pair(40, fmt(radius))
        self.pair(50, fmt(start_angle % 360.0))
        self.pair(51, fmt(end_angle % 360.0))

    def line(self, start: Point, end: Point) -> None:
        self.pair(0, "LINE")
        self.pair(8, "0")
        self.pair(10, fmt(start[0]))
        self.pair(20, fmt(start[1]))
        self.pair(30, "0")
        self.pair(11, fmt(end[0]))
        self.pair(21, fmt(end[1]))
        self.pair(31, "0")

    def finish(self) -> str:
        self.pair(0, "ENDSEC")
        self.pair(0, "EOF")
        # Use Windows line endings; this is the most reliable form for older
        # AutoCAD releases on Windows, including AutoCAD 2016.
        return "\r\n".join(self.lines) + "\r\n"


def write_piece(
    writer: DxfWriter,
    piece: PieceGeometry,
    center: Point,
    rotation: float,
    sector_angle: float,
) -> None:
    """Write one rotated sector."""

    def transform(point: Point) -> Point:
        return add(rotate(point, rotation), center)

    # The source file uses both arcs with the same increasing-angle direction.
    # Retain that convention for maximum compatibility.
    writer.arc(
        center,
        polar_radius(piece.outer_start),
        SOURCE_CENTER_ANGLE - sector_angle / 2.0 + rotation,
        SOURCE_CENTER_ANGLE + sector_angle / 2.0 + rotation,
    )
    writer.arc(
        center,
        polar_radius(piece.inner_start),
        SOURCE_CENTER_ANGLE - sector_angle / 2.0 + rotation,
        SOURCE_CENTER_ANGLE + sector_angle / 2.0 + rotation,
    )

    for edge in (piece.start_edge, piece.end_edge):
        for start, end in zip(edge, edge[1:]):
            writer.line(transform(start), transform(end))


def generate_piece_dxf(
    output: Path,
    *,
    parts: int = 4,
    center: Point = (0.0, 0.0),
    inner_radius: float = SOURCE_INNER_RADIUS,
    outer_radius: float = SOURCE_OUTER_RADIUS,
    notch_size: float | None = None,
    clearance: float = DEFAULT_LASER_CLEARANCE,
    notch_shape: str = DEFAULT_NOTCH_SHAPE,
    plate_thickness: float = 0.0,
    rotation: float = 0.0,
) -> None:
    """Generate one sector file for a ring divided into ``parts`` pieces."""

    if parts < 2:
        raise ValueError("零件数量至少为 2")
    inner_radius, outer_radius = compensated_radii(
        inner_radius,
        outer_radius,
        plate_thickness,
    )
    sector_angle = 360.0 / parts
    effective_notch_size = (
        auto_notch_size(inner_radius, outer_radius, clearance)
        if notch_size is None
        else notch_size
    )
    piece = resized_piece(
        inner_radius,
        outer_radius,
        sector_angle,
        notch_size=effective_notch_size,
        clearance=clearance,
        notch_shape=notch_shape,
    )
    writer = DxfWriter()
    writer.header()
    # All individual files use the same local orientation. The nesting/CAD
    # program can rotate and place each copy wherever it fits on the plate.
    write_piece(writer, piece, center, rotation, sector_angle)
    output.write_text(writer.finish(), encoding="ascii")


def generate_dxf(
    output: Path,
    *,
    parts: int = 4,
    center: Point = (0.0, 0.0),
    inner_radius: float = SOURCE_INNER_RADIUS,
    outer_radius: float = SOURCE_OUTER_RADIUS,
    notch_size: float | None = None,
    clearance: float = DEFAULT_LASER_CLEARANCE,
    notch_shape: str = DEFAULT_NOTCH_SHAPE,
    plate_thickness: float = 0.0,
    rotation: float = 0.0,
    step: float | None = None,
) -> None:
    """Generate a DXF containing ``parts`` sectors around one center."""

    if parts < 2:
        raise ValueError("零件数量至少为 2")
    if step is None:
        step = 360.0 / parts

    inner_radius, outer_radius = compensated_radii(
        inner_radius,
        outer_radius,
        plate_thickness,
    )
    effective_notch_size = (
        auto_notch_size(inner_radius, outer_radius, clearance)
        if notch_size is None
        else notch_size
    )
    piece = resized_piece(
        inner_radius,
        outer_radius,
        step,
        notch_size=effective_notch_size,
        clearance=clearance,
        notch_shape=notch_shape,
    )
    writer = DxfWriter()
    writer.header()
    for index in range(parts):
        write_piece(writer, piece, center, rotation + index * step, step)
    output.write_text(writer.finish(), encoding="ascii")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate keyed annular sectors as an ASCII DXF."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="output DXF path; defaults to an automatic parameterized filename",
    )
    parser.add_argument(
        "--parts",
        "--copies",
        dest="parts",
        type=int,
        default=4,
        help="number of sectors in the ring (default: 4)",
    )
    parser.add_argument(
        "--center-x",
        type=float,
        default=0.0,
        help="ring center X in drawing units (default: 0)",
    )
    parser.add_argument(
        "--center-y",
        type=float,
        default=0.0,
        help="ring center Y in drawing units (default: 0)",
    )
    parser.add_argument(
        "--inner-radius",
        type=float,
        default=SOURCE_INNER_RADIUS,
        help=f"inner radius in mm (default: {SOURCE_INNER_RADIUS})",
    )
    parser.add_argument(
        "--outer-radius",
        type=float,
        default=SOURCE_OUTER_RADIUS,
        help=f"outer radius in mm (default: {SOURCE_OUTER_RADIUS})",
    )
    parser.add_argument(
        "--notch-size",
        type=float,
        default=None,
        help="manual keyed notch size in mm; omitted means automatic sizing",
    )
    parser.add_argument(
        "--clearance",
        type=float,
        default=DEFAULT_LASER_CLEARANCE,
        help=f"laser clearance in mm (default: {DEFAULT_LASER_CLEARANCE})",
    )
    parser.add_argument(
        "--plate-thickness",
        type=float,
        default=0.0,
        help="radial wall allowance on both sides in mm (default: 0)",
    )
    parser.add_argument(
        "--notch-shape",
        choices=NOTCH_SHAPES,
        default=DEFAULT_NOTCH_SHAPE,
        help="keyed notch profile (default: trapezoid)",
    )
    parser.add_argument(
        "--rotation",
        type=float,
        default=0.0,
        help="rotation of the first sector in degrees (default: 0)",
    )
    parser.add_argument(
        "--step",
        type=float,
        default=None,
        help="angle between sectors; defaults to 360/parts",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    effective_inner_radius, effective_outer_radius = compensated_radii(
        args.inner_radius,
        args.outer_radius,
        args.plate_thickness,
    )
    effective_notch_size = (
        auto_notch_size(effective_inner_radius, effective_outer_radius, args.clearance)
        if args.notch_size is None
        else args.notch_size
    )
    output = args.output
    if output is None:
        output = Path(
            default_filename(
                args.inner_radius * 2.0,
                args.outer_radius * 2.0,
                effective_notch_size,
                args.clearance,
                args.parts,
                args.notch_shape,
                args.plate_thickness,
            )
        )
    try:
        generate_dxf(
            output,
            parts=args.parts,
            center=(args.center_x, args.center_y),
            inner_radius=args.inner_radius,
            outer_radius=args.outer_radius,
            notch_size=effective_notch_size,
            clearance=args.clearance,
            notch_shape=args.notch_shape,
            plate_thickness=args.plate_thickness,
            rotation=args.rotation,
            step=args.step,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"已生成：{output}（{args.parts} 片，每片 {360.0 / args.parts:g} 度）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
