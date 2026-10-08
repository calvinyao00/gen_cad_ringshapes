#!/usr/bin/env python3
"""Generate keyed annular sectors as a laser-cutter DXF.

The default geometry is measured from the supplied DXF file:

    199 266+4补.dxf

The source sector is a 90-degree annular sector with an outer radius of 131
mm and an inner radius of 101.5 mm.  Its two ends use slightly different
keyed profiles. The number of parts, connector dimensions, and laser
clearance are configurable; when the number of parts is not four, the profile
is angularly resized so all parts still close into one ring.  The plastic-box
connector is a trapezoidal male tab with independently adjustable lower base,
upper base, and protrusion height.  Its four corners are filleted at R2 mm by
default.

By default the writer emits two open R12 POLYLINE paths. Each path contains
one exact circular-arc bulge and one keyed side, so a laser cutter can run
the outer and inner portions separately. A legacy ARC/LINE mode is available
with ``split_paths=False``.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Tuple


# Use typing.Tuple here because this assignment is evaluated at import time;
# built-in generic aliases such as tuple[float, float] require Python 3.9+.
Point = Tuple[float, float]


SOURCE_INNER_RADIUS = 101.5
SOURCE_OUTER_RADIUS = 131.0
SOURCE_START_ANGLE = 135.0
SOURCE_END_ANGLE = 225.0
SOURCE_CENTER_ANGLE = 180.0
SOURCE_SECTOR_ANGLE = SOURCE_END_ANGLE - SOURCE_START_ANGLE
# Legacy controls are kept for scripts made before the plastic-box connector
# update.  New callers should use the explicit male_* dimensions below.
DEFAULT_NOTCH_SIZE = 10.0
DEFAULT_NOTCH_PERCENTAGE = 25.0
DEFAULT_TRAPEZOID_HEIGHT = 8.0
# The source profile's short base is approximately 70% of its lower base.
# Keeping this ratio makes the percentage control only the trapezoid width.
TRAPEZOID_TOP_BASE_RATIO = 0.70
# Backward-compatible name retained for callers that imported the old
# constant. It now represents the default, rather than a forced height.
TRAPEZOID_NOTCH_HEIGHT = DEFAULT_TRAPEZOID_HEIGHT
# Defaults reproduce the former 25% / 70% geometry for the original 29.5 mm
# ring wall, rounded to the 0.1 mm adjustment grid used by the desktop GUI.
DEFAULT_MALE_LOWER_BASE_WIDTH = 7.4
DEFAULT_MALE_TOP_BASE_WIDTH = 5.2
DEFAULT_MALE_HEIGHT = 8.0
DEFAULT_CONNECTOR_CORNER_RADIUS = 2.0
DEFAULT_LASER_CLEARANCE = 0.3
DEFAULT_NOTCH_SHAPE = "trapezoid"
NOTCH_SHAPES = ("trapezoid", "rectangular")
NOTCH_SHAPE_LABELS = {"trapezoid": "梯形", "rectangular": "矩形"}
DEFAULT_SPLIT_PATHS = True
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
    trapezoid_height: float = DEFAULT_TRAPEZOID_HEIGHT,
    male_lower_base_width: float | None = None,
    male_top_base_width: float | None = None,
    male_height: float | None = None,
) -> PieceGeometry:
    """Build one sector with adjustable notch size and mating clearance.

    The source end profile, expressed in radial/tangential coordinates, is:

    * trapezoid lower and upper base widths, measured along the radial ring
      wall, plus a male-tab protrusion height measured tangentially;
    * equal radial steps for a rectangular notch, with the notch height in
      millimeters;
    * a tangential key width derived from the selected control;
    * a clearance offset on the mating edge.

    The end profile is intentionally asymmetric so neighboring rotated parts
    mate with clearance rather than overlapping.
    """

    if inner_radius <= 0:
        raise ValueError("内半径必须大于 0")
    if outer_radius <= inner_radius:
        raise ValueError("外半径必须大于内半径")
    if sector_angle <= 0 or sector_angle > 360:
        raise ValueError("扇区角度必须大于 0 且不超过 360 度")
    if clearance < 0:
        raise ValueError("激光间隙不能为负数")
    notch_shape = notch_shape.lower()
    if notch_shape not in NOTCH_SHAPES:
        raise ValueError("缺口形状必须是梯形或矩形")

    wall = outer_radius - inner_radius
    if notch_shape == "trapezoid":
        # ``notch_size`` remains a legacy percentage when explicit dimensions
        # are absent.  This lets earlier command-line scripts keep working.
        if male_lower_base_width is None:
            notch_percentage = (
                DEFAULT_NOTCH_PERCENTAGE if notch_size is None else notch_size
            )
            if notch_percentage <= 0 or notch_percentage > 100:
                raise ValueError("梯形咬合下底比例必须大于 0 且不超过 100%")
            lower_base_width = wall * notch_percentage / 100.0
        else:
            lower_base_width = male_lower_base_width
        if male_top_base_width is None:
            upper_base_width = lower_base_width * TRAPEZOID_TOP_BASE_RATIO
        else:
            upper_base_width = male_top_base_width
        notch_height = trapezoid_height if male_height is None else male_height
        if lower_base_width <= 0 or lower_base_width > wall:
            raise ValueError("公头下底宽度必须大于 0 且不超过切割环宽")
        if upper_base_width <= 0 or upper_base_width > lower_base_width:
            raise ValueError("公头上底宽度必须大于 0 且不超过公头下底宽度")
        if notch_height <= 0:
            raise ValueError("公头伸出高度必须大于 0")
        base_center = (outer_radius + inner_radius) / 2.0
        radial_values = (
            outer_radius,
            base_center + upper_base_width / 2.0,
            base_center + lower_base_width / 2.0,
            base_center - lower_base_width / 2.0,
            base_center - upper_base_width / 2.0,
            inner_radius,
        )
        tangent_values = (0.0, 0.0, notch_height, notch_height, 0.0, 0.0)
    else:
        notch_height = (
            auto_notch_size(inner_radius, outer_radius, clearance)
            if notch_size is None
            else notch_size
        )
        if notch_height <= 0:
            raise ValueError("矩形缺口高度必须大于 0")
        # Preserve the original rectangular-profile proportion.
        tangent_width = 0.5 * notch_height
        if 1.58 * notch_height >= wall:
            raise ValueError("缺口高度对于当前环宽过大，请减小缺口或增大外径")
        radial_values = (
            outer_radius,
            outer_radius - notch_height,
            outer_radius - notch_height,
            inner_radius + notch_height,
            inner_radius + notch_height,
            inner_radius,
        )
        tangent_values = (0.0, 0.0, tangent_width, tangent_width, 0.0, 0.0)

    start_angle = SOURCE_CENTER_ANGLE - sector_angle / 2.0

    def basis_point(radius: float, tangent: float) -> Point:
        if abs(tangent) >= radius:
            raise ValueError("缺口切向高度对于当前半径过大")
        angle = math.radians(start_angle)
        radial = (math.cos(angle), math.sin(angle))
        # This tangent direction matches the keyed profile in the source DXF.
        tangent_axis = (math.sin(angle), -math.cos(angle))
        # Keep ``radius`` as the true distance from the ring center. Without
        # this correction, increasing tangential height also changes the
        # point's polar radius and makes the preview geometry drift.
        radial_component = math.sqrt(radius * radius - tangent * tangent)
        return (
            radial_component * radial[0] + tangent * tangent_axis[0],
            radial_component * radial[1] + tangent * tangent_axis[1],
        )

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


def automatic_notch_value(
    inner_radius: float,
    outer_radius: float,
    clearance: float = DEFAULT_LASER_CLEARANCE,
    notch_shape: str = DEFAULT_NOTCH_SHAPE,
) -> float:
    """Return the automatic control value for the selected notch shape.

    Trapezoids use a percentage because their height is fixed. Rectangles use
    the original automatic height calculation in millimeters.
    """

    notch_shape = notch_shape.lower()
    if notch_shape not in NOTCH_SHAPES:
        raise ValueError("缺口形状必须是梯形或矩形")
    if notch_shape == "trapezoid":
        return DEFAULT_NOTCH_PERCENTAGE
    return auto_notch_size(inner_radius, outer_radius, clearance)


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
        # Use the smallest R11/R12 structure.  In particular, do not write a
        # hand-authored HEADER or VPORT section: AutoCAD 2016 can reject
        # otherwise valid AC1009 files when those sections are incomplete.
        # The cutting coordinates are expressed directly in millimeters.
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

    def bulge_arc(self, start: Point, end: Point, bulge: float) -> None:
        """Write the circular arc represented by one polyline bulge."""

        if not bulge:
            self.line(start, end)
            return
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        chord = math.hypot(dx, dy)
        if chord <= 1e-9:
            raise ValueError("圆角弧的端点不能重合")
        midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        left_normal = (-dy / chord, dx / chord)
        offset = chord * (1.0 - bulge * bulge) / (4.0 * bulge)
        center = (
            midpoint[0] + left_normal[0] * offset,
            midpoint[1] + left_normal[1] * offset,
        )
        radius = chord * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
        start_angle = math.degrees(math.atan2(start[1] - center[1], start[0] - center[0]))
        end_angle = math.degrees(math.atan2(end[1] - center[1], end[0] - center[0]))
        # DXF ARC entities are always counter-clockwise.  Reverse the two
        # angles for a clockwise bulge; the geometry remains identical.
        if bulge < 0:
            start_angle, end_angle = end_angle, start_angle
        self.arc(center, radius, start_angle, end_angle)

    def line(self, start: Point, end: Point) -> None:
        self.pair(0, "LINE")
        self.pair(8, "0")
        self.pair(10, fmt(start[0]))
        self.pair(20, fmt(start[1]))
        self.pair(30, "0")
        self.pair(11, fmt(end[0]))
        self.pair(21, fmt(end[1]))
        self.pair(31, "0")

    def comment(self, value: str) -> None:
        """Write an ignored DXF comment to mark a cutting-path boundary."""

        self.pair(999, value)

    def polyline(self, vertices: Sequence[Point], bulges: Sequence[float]) -> None:
        """Write one open R12 2D polyline, including optional arc bulges."""

        if len(vertices) < 2 or len(vertices) != len(bulges):
            raise ValueError("切割路径至少需要两个点，并且点与弧度数量必须一致")
        self.pair(0, "POLYLINE")
        self.pair(8, "0")
        self.pair(66, 1)
        self.pair(70, 0)  # open 2D polyline
        self.pair(10, "0")
        self.pair(20, "0")
        self.pair(30, "0")
        for point, bulge in zip(vertices, bulges):
            self.pair(0, "VERTEX")
            self.pair(8, "0")
            self.pair(10, fmt(point[0]))
            self.pair(20, fmt(point[1]))
            self.pair(30, "0")
            if bulge:
                self.pair(42, fmt(bulge))
        self.pair(0, "SEQEND")
        self.pair(8, "0")

    def finish(self) -> str:
        self.pair(0, "ENDSEC")
        self.pair(0, "EOF")
        # Use Windows line endings; this is the most reliable form for older
        # AutoCAD releases on Windows, including AutoCAD 2016.
        return "\r\n".join(self.lines) + "\r\n"


@dataclass(frozen=True)
class Fillet:
    """Tangent points and bulge for one rounded polyline corner."""

    before: Point
    after: Point
    bulge: float
    tangent_length: float


def _fillet_at_corner(previous: Point, corner: Point, following: Point, radius: float) -> Fillet:
    """Return an exact constant-radius fillet for a directed polyline corner."""

    incoming_length = math.dist(previous, corner)
    outgoing_length = math.dist(corner, following)
    if incoming_length <= 1e-9 or outgoing_length <= 1e-9:
        raise ValueError("梯形圆角附近的边长不能为零")
    incoming = (
        (corner[0] - previous[0]) / incoming_length,
        (corner[1] - previous[1]) / incoming_length,
    )
    outgoing = (
        (following[0] - corner[0]) / outgoing_length,
        (following[1] - corner[1]) / outgoing_length,
    )
    turn = math.atan2(
        incoming[0] * outgoing[1] - incoming[1] * outgoing[0],
        incoming[0] * outgoing[0] + incoming[1] * outgoing[1],
    )
    if abs(turn) <= 1e-7 or abs(abs(turn) - math.pi) <= 1e-7:
        raise ValueError("梯形圆角需要两个不共线的相邻边")
    tangent_length = radius * math.tan(abs(turn) / 2.0)
    return Fillet(
        before=(
            corner[0] - incoming[0] * tangent_length,
            corner[1] - incoming[1] * tangent_length,
        ),
        after=(
            corner[0] + outgoing[0] * tangent_length,
            corner[1] + outgoing[1] * tangent_length,
        ),
        bulge=math.tan(turn / 4.0),
        tangent_length=tangent_length,
    )


def fillet_polyline(
    vertices: Sequence[Point],
    bulges: Sequence[float],
    corner_indices: Sequence[int],
    radius: float,
) -> tuple[tuple[Point, ...], tuple[float, ...]]:
    """Round selected corners while preserving every existing arc segment.

    DXF stores a round polyline corner as an arc bulge on its incoming tangent
    point.  This works for both cutting-path polylines and the on-screen
    preview without approximating the requested radius.
    """

    if len(vertices) != len(bulges) or len(vertices) < 2:
        raise ValueError("圆角路径的点和弧度数量必须一致")
    if radius < 0:
        raise ValueError("梯形圆角半径不能为负数")
    if radius == 0:
        return tuple(vertices), tuple(bulges)

    selected = set(corner_indices)
    if any(index <= 0 or index >= len(vertices) - 1 for index in selected):
        raise ValueError("梯形圆角位置无效")
    fillets = {
        index: _fillet_at_corner(
            vertices[index - 1], vertices[index], vertices[index + 1], radius
        )
        for index in selected
    }
    for index in range(len(vertices) - 1):
        outgoing = fillets[index].tangent_length if index in fillets else 0.0
        incoming = fillets[index + 1].tangent_length if index + 1 in fillets else 0.0
        if outgoing + incoming >= math.dist(vertices[index], vertices[index + 1]) - 1e-8:
            raise ValueError("R2 圆角对于当前公头尺寸过大，请增大尺寸或减小圆角")

    rounded_vertices: list[Point] = []
    rounded_bulges: list[float] = []
    for index, vertex in enumerate(vertices):
        if index in fillets:
            fillet = fillets[index]
            rounded_vertices.extend((fillet.before, fillet.after))
            rounded_bulges.extend((fillet.bulge, bulges[index]))
        else:
            rounded_vertices.append(vertex)
            rounded_bulges.append(bulges[index])
    return tuple(rounded_vertices), tuple(rounded_bulges)


def rounded_connector_path(
    vertices: Sequence[Point],
    bulges: Sequence[float],
    notch_shape: str,
    corner_radius: float,
) -> tuple[tuple[Point, ...], tuple[float, ...]]:
    """Apply the R2 fillets to the four trapezoid corners of one connector."""

    if notch_shape != "trapezoid":
        return tuple(vertices), tuple(bulges)
    # The first two points define the circular ring arc.  The next four
    # internal points are the trapezoid's four sharp corners.
    return fillet_polyline(vertices, bulges, (2, 3, 4, 5), corner_radius)


def write_bulge_path_as_entities(
    writer: DxfWriter, vertices: Sequence[Point], bulges: Sequence[float]
) -> None:
    """Write a bulged path as traditional LINE/ARC entities."""

    for start, end, bulge in zip(vertices, vertices[1:], bulges):
        writer.bulge_arc(start, end, bulge)


def write_piece(
    writer: DxfWriter,
    piece: PieceGeometry,
    center: Point,
    rotation: float,
    sector_angle: float,
    split_paths: bool = False,
    notch_shape: str = DEFAULT_NOTCH_SHAPE,
    connector_corner_radius: float = DEFAULT_CONNECTOR_CORNER_RADIUS,
) -> None:
    """Write one rotated sector."""

    def transform(point: Point) -> Point:
        return add(rotate(point, rotation), center)

    arc_bulge = math.tan(math.radians(sector_angle) / 4.0)
    outer_vertices = [transform(piece.outer_start)] + [
        transform(point) for point in piece.end_edge
    ]
    inner_vertices = [transform(piece.inner_end)] + [
        transform(point) for point in reversed(piece.start_edge)
    ]
    outer_vertices, outer_bulges = rounded_connector_path(
        outer_vertices,
        [arc_bulge] + [0.0] * (len(outer_vertices) - 1),
        notch_shape,
        connector_corner_radius,
    )
    inner_vertices, inner_bulges = rounded_connector_path(
        inner_vertices,
        [-arc_bulge] + [0.0] * (len(inner_vertices) - 1),
        notch_shape,
        connector_corner_radius,
    )

    if split_paths:
        # Make two independent, continuous open paths.  The outer path runs
        # from the start of the outer arc through the end-side notch to the
        # end of the inner wall.  The inner path runs back through the inner
        # arc and the start-side notch.  Together they describe the same
        # closed outline, while the cutter can process them separately.
        writer.comment("OUTER_CUT_PATH_BEGIN")
        writer.polyline(outer_vertices, outer_bulges)
        writer.comment("OUTER_CUT_PATH_END")

        writer.comment("INNER_CUT_PATH_BEGIN")
        writer.polyline(inner_vertices, inner_bulges)
        writer.comment("INNER_CUT_PATH_END")
        return

    # The legacy mode uses separate ARC and LINE entities, matching the
    # original source file.
    write_bulge_path_as_entities(writer, outer_vertices, outer_bulges)
    write_bulge_path_as_entities(writer, inner_vertices, inner_bulges)


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
    trapezoid_height: float = DEFAULT_TRAPEZOID_HEIGHT,
    male_lower_base_width: float | None = None,
    male_top_base_width: float | None = None,
    male_height: float | None = None,
    connector_corner_radius: float = DEFAULT_CONNECTOR_CORNER_RADIUS,
    plate_thickness: float = 0.0,
    rotation: float = 0.0,
    split_paths: bool = DEFAULT_SPLIT_PATHS,
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
        automatic_notch_value(inner_radius, outer_radius, clearance, notch_shape)
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
        trapezoid_height=trapezoid_height,
        male_lower_base_width=male_lower_base_width,
        male_top_base_width=male_top_base_width,
        male_height=male_height,
    )
    writer = DxfWriter()
    writer.header()
    # All individual files use the same local orientation. The nesting/CAD
    # program can rotate and place each copy wherever it fits on the plate.
    write_piece(
        writer,
        piece,
        center,
        rotation,
        sector_angle,
        split_paths=split_paths,
        notch_shape=notch_shape,
        connector_corner_radius=connector_corner_radius,
    )
    # Write bytes so Windows does not translate the already-formed CRLF
    # endings a second time into CRCRLF.
    output.write_bytes(writer.finish().encode("ascii"))


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
    trapezoid_height: float = DEFAULT_TRAPEZOID_HEIGHT,
    male_lower_base_width: float | None = None,
    male_top_base_width: float | None = None,
    male_height: float | None = None,
    connector_corner_radius: float = DEFAULT_CONNECTOR_CORNER_RADIUS,
    plate_thickness: float = 0.0,
    rotation: float = 0.0,
    step: float | None = None,
    split_paths: bool = DEFAULT_SPLIT_PATHS,
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
        automatic_notch_value(inner_radius, outer_radius, clearance, notch_shape)
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
        trapezoid_height=trapezoid_height,
        male_lower_base_width=male_lower_base_width,
        male_top_base_width=male_top_base_width,
        male_height=male_height,
    )
    writer = DxfWriter()
    writer.header()
    for index in range(parts):
        write_piece(
            writer,
            piece,
            center,
            rotation + index * step,
            step,
            split_paths=split_paths,
            notch_shape=notch_shape,
            connector_corner_radius=connector_corner_radius,
        )
    # Write bytes so Windows does not translate the already-formed CRLF
    # endings a second time into CRCRLF.
    output.write_bytes(writer.finish().encode("ascii"))


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
        help=(
            "trapezoid lower-base width as percent of ring wall; "
            "rectangular notch height in mm; omitted means automatic sizing"
        ),
    )
    parser.add_argument(
        "--trapezoid-height",
        type=float,
        default=DEFAULT_TRAPEZOID_HEIGHT,
        help=f"trapezoid height in mm (default: {DEFAULT_TRAPEZOID_HEIGHT})",
    )
    parser.add_argument(
        "--male-lower-base-width",
        type=float,
        default=None,
        help="male trapezoid lower-base width in mm; overrides --notch-size",
    )
    parser.add_argument(
        "--male-top-base-width",
        type=float,
        default=None,
        help="male trapezoid upper-base width in mm",
    )
    parser.add_argument(
        "--male-height",
        type=float,
        default=None,
        help="male trapezoid protrusion height in mm; overrides --trapezoid-height",
    )
    parser.add_argument(
        "--connector-corner-radius",
        type=float,
        default=DEFAULT_CONNECTOR_CORNER_RADIUS,
        help=f"trapezoid corner radius in mm (default: {DEFAULT_CONNECTOR_CORNER_RADIUS})",
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
    parser.add_argument(
        "--split-paths",
        dest="split_paths",
        action="store_true",
        default=DEFAULT_SPLIT_PATHS,
        help="write separate outer and inner cutting paths (default: enabled)",
    )
    parser.add_argument(
        "--no-split-paths",
        dest="split_paths",
        action="store_false",
        help="use legacy separate ARC and LINE entities",
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
        automatic_notch_value(
            effective_inner_radius,
            effective_outer_radius,
            args.clearance,
            args.notch_shape,
        )
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
            trapezoid_height=args.trapezoid_height,
            male_lower_base_width=args.male_lower_base_width,
            male_top_base_width=args.male_top_base_width,
            male_height=args.male_height,
            connector_corner_radius=args.connector_corner_radius,
            plate_thickness=args.plate_thickness,
            rotation=args.rotation,
            step=args.step,
            split_paths=args.split_paths,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"已生成：{output}（{args.parts} 片，每片 {360.0 / args.parts:g} 度）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
