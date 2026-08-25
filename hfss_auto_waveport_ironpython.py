# -*- coding: utf-8 -*-
"""HFSS wave-port automation - native IronPython version (no pyaedt needed).

Run this directly inside AEDT's internal scripting console
(Tools > Run Script > Run Script..., or paste into the interactive console)
with the target HFSS design (Driven Modal, 3D Modeler) open and active.

For a chosen end of a trace object, it builds a rectangular port sheet and
assigns it as a wave port:

  - width  = trace width + a margin added on *each* side (0.1 mm by
    default, matching the "x" / "y" = 0.1 mm callouts in the reference
    sketch).
  - height (z) = auto-detected: scans every solid/sheet object at the
    port's (x, y) location and finds the nearest object boundary directly
    below the trace and directly above it - the layers that "sandwich"
    (夾層) the trace. By default the port spans the *full thickness* of
    both of those layers (ground-to-ground for a stripline-like stackup).

Edit the calls at the bottom (trace names/ends) before running.
"""

import math

oProject = oDesktop.GetActiveProject()
oDesign = oProject.GetActiveDesign()
oEditor = oDesign.SetActiveEditor("3D Modeler")
oModule = oDesign.GetModule("BoundarySetup")

_MM_PER_UNIT = {
    "mm": 1.0, "cm": 10.0, "m": 1000.0, "meter": 1000.0,
    "um": 0.001, "nm": 1e-6, "in": 25.4, "mil": 0.0254,
}


def _mm_to_model_units(value_mm, units):
    factor = _MM_PER_UNIT.get(units.lower(), 1.0)
    return value_mm / factor


def _normalize(vx, vy):
    length = math.sqrt(vx * vx + vy * vy)
    if length == 0:
        raise ValueError("Direction vector must not be zero-length.")
    return vx / length, vy / length


def get_bounding_box(obj_name):
    """[xmin, ymin, zmin, xmax, ymax, zmax] in the design's model units."""
    bb = oEditor.GetObjectBoundingBox(obj_name)
    return [float(v) for v in bb]


def get_solids_and_sheets():
    names = []
    for group in ("Solids", "Sheets"):
        try:
            names.extend(list(oEditor.GetObjectsInGroup(group)))
        except Exception:
            pass
    return names


def find_sandwich_bounds(probe_x, probe_y, trace_zmin, trace_zmax, exclude_names,
                          extend_full_layer=True, z_tol=1e-6):
    """Find the Z span of the layer(s) sandwiching the trace at (probe_x, probe_y).

    Returns (z_min, z_max, lower_object_name, upper_object_name).
    """
    exclude = set(exclude_names)
    candidates = []
    for name in get_solids_and_sheets():
        if name in exclude:
            continue
        xmin, ymin, zmin, xmax, ymax, zmax = get_bounding_box(name)
        if xmin - z_tol <= probe_x <= xmax + z_tol and ymin - z_tol <= probe_y <= ymax + z_tol:
            candidates.append((zmin, zmax, name))

    lower_candidates = [c for c in candidates if c[1] <= trace_zmin + z_tol]
    upper_candidates = [c for c in candidates if c[0] >= trace_zmax - z_tol]

    lower = max(lower_candidates, key=lambda c: c[1]) if lower_candidates else (trace_zmin, trace_zmin, None)
    upper = min(upper_candidates, key=lambda c: c[0]) if upper_candidates else (trace_zmax, trace_zmax, None)

    if extend_full_layer:
        z_min_port, z_max_port = lower[0], upper[1]
    else:
        z_min_port, z_max_port = lower[1], upper[0]

    if z_max_port <= z_min_port:
        raise RuntimeError(
            "Could not resolve a valid port height at (%s, %s): z_min=%s, z_max=%s. "
            "Check exclude_names/geometry, or pass an explicit position." %
            (probe_x, probe_y, z_min_port, z_max_port)
        )
    return z_min_port, z_max_port, lower[2], upper[2]


def _create_port_sheet(sheet_name, p0, p1, p2, p3, units):
    """Create a covered, closed 4-point polygon sheet via native CreatePolyline."""
    pts = [p0, p1, p2, p3, p0]  # repeat first point to close explicitly

    polyline_points = ["NAME:PolylinePoints"]
    for p in pts:
        polyline_points.append(
            ["NAME:PLPoint",
             "X:=", str(p[0]) + units,
             "Y:=", str(p[1]) + units,
             "Z:=", str(p[2]) + units]
        )

    polyline_segments = ["NAME:PolylineSegments"]
    for i in range(4):
        polyline_segments.append(
            ["NAME:PLSegment", "SegmentType:=", "Line", "StartIndex:=", i, "NoOfPoints:=", 2]
        )

    polyline_xsection = [
        "NAME:PolylineXSection",
        "XSectionType:=", "None",
        "XSectionOrient:=", "Auto",
        "XSectionWidth:=", "0" + units,
        "XSectionTopWidth:=", "0" + units,
        "XSectionHeight:=", "0" + units,
        "XSectionNumSegments:=", "0",
        "XSectionBendType:=", "Corner",
    ]

    polyline_parameters = [
        "NAME:PolylineParameters",
        "IsPolylineCovered:=", True,
        "IsPolylineClosed:=", True,
        polyline_points,
        polyline_segments,
        polyline_xsection,
    ]

    attributes = [
        "NAME:Attributes",
        "Name:=", sheet_name,
        "Flags:=", "",
        "Color:=", "(143 175 143)",
        "Transparency:=", 0.6,
        "PartCoordinateSystem:=", "Global",
        "UDMId:=", "",
        "MaterialValue:=", "\"vacuum\"",
        "SurfaceMaterialValue:=", "\"\"",
        "SolveInside:=", True,
        "ShellElement:=", False,
        "ShellElementThickness:=", "0mm",
        "IsMaterialEditable:=", True,
        "UseMaterialAppearance:=", False,
        "IsLightweight:=", False,
    ]

    oEditor.CreatePolyline(polyline_parameters, attributes)


def _assign_wave_port(port_name, sheet_name, int_start, int_stop, units,
                       impedance=50, renormalize=True, num_modes=1):
    start = [str(int_start[0]) + units, str(int_start[1]) + units, str(int_start[2]) + units]
    stop = [str(int_stop[0]) + units, str(int_stop[1]) + units, str(int_stop[2]) + units]

    mode1 = [
        "NAME:Mode1",
        "ModeNum:=", 1,
        "UseIntLine:=", True,
        ["NAME:IntLine", "Start:=", start, "End:=", stop],
        "AlignmentGroup:=", 0,
        "CharImp:=", "Zpi",
    ]
    if renormalize:
        mode1 = mode1 + ["RenormImp:=", str(impedance) + "ohm"]

    args = [
        "NAME:" + port_name,
        "Objects:=", [sheet_name],
        "NumModes:=", num_modes,
        "UseLineModeAlignment:=", False,
        "DoDeembed:=", False,
        "RenormalizeAllTerminals:=", renormalize,
        ["NAME:Modes", mode1],
        "ShowReporterFilter:=", False,
        "ReporterFilter:=", [True],
        "UseAnalyticAlignment:=", False,
    ]
    oModule.AssignWavePort(args)


def create_auto_wave_port(trace_name, end="end", margin_mm=0.1, extend_full_layer=True,
                           direction=None, width_mm=None, position=None,
                           port_name=None, impedance=50, renormalize=True):
    """Create and assign a wave port automatically sized around a trace end.

    end : "start" or "end" - which end of the trace's bounding box to cut
        the port at. Ignored if `position` is given.
    margin_mm : extension added on *each* side of the trace width (default
        0.1 mm -> trace width + 0.1 mm on both sides).
    extend_full_layer : if True (default) the port height spans the full
        thickness of the layer below and the layer above the trace
        (ground-to-ground). If False, it stops at the trace's own
        top/bottom contact boundaries.
    direction : explicit (x, y) propagation direction, for non-axis-aligned
        traces. Default: inferred from the trace's bounding box.
    width_mm : explicit trace width in mm, for when bounding-box inference
        isn't reliable (e.g. angled trace, pad instead of straight segment).
    position : explicit (x, y) point to cut the port at, overriding `end`.
    """
    if end not in ("start", "end"):
        raise ValueError("end must be 'start' or 'end'.")

    units = oEditor.GetModelUnits()

    xmin, ymin, zmin, xmax, ymax, zmax = get_bounding_box(trace_name)
    dx, dy = xmax - xmin, ymax - ymin

    if direction is None:
        along_x = dx >= dy
        direction = (1.0, 0.0) if along_x else (0.0, 1.0)
    else:
        along_x = abs(direction[0]) >= abs(direction[1])
    dir_x, dir_y = _normalize(direction[0], direction[1])
    perp_x, perp_y = -dir_y, dir_x

    if position is None:
        if along_x:
            px = xmin if end == "start" else xmax
            py = (ymin + ymax) / 2.0
        else:
            px = (xmin + xmax) / 2.0
            py = ymin if end == "start" else ymax
    else:
        px, py = position[0], position[1]

    if width_mm is not None:
        width = _mm_to_model_units(width_mm, units)
    else:
        width = dy if along_x else dx
        if width <= 0:
            raise ValueError("Could not infer trace width from bounding box; pass width_mm explicitly.")

    margin = _mm_to_model_units(margin_mm, units)
    half_extent = width / 2.0 + margin

    z_min_port, z_max_port, lower_name, upper_name = find_sandwich_bounds(
        px, py, zmin, zmax, exclude_names=[trace_name], extend_full_layer=extend_full_layer
    )
    print("[%s/%s] port width=%g%s, height=%g%s (layer below=%s, layer above=%s)" % (
        trace_name, end, 2 * half_extent, units, z_max_port - z_min_port, units, lower_name, upper_name
    ))

    p0 = (px - perp_x * half_extent, py - perp_y * half_extent, z_min_port)
    p1 = (px + perp_x * half_extent, py + perp_y * half_extent, z_min_port)
    p2 = (px + perp_x * half_extent, py + perp_y * half_extent, z_max_port)
    p3 = (px - perp_x * half_extent, py - perp_y * half_extent, z_max_port)

    sheet_name = "%s_%s_port_sheet" % (trace_name, end)
    _create_port_sheet(sheet_name, p0, p1, p2, p3, units)

    port_name = port_name or ("%s_%s_port" % (trace_name, end))
    int_start = (px, py, z_min_port)
    int_stop = (px, py, z_max_port)
    _assign_wave_port(port_name, sheet_name, int_start, int_stop, units,
                       impedance=impedance, renormalize=renormalize)
    return port_name


def create_auto_wave_ports(trace_ends, **kwargs):
    """Batch-create wave ports for a list of traces / (trace_name, end) pairs.

    Example: create_auto_wave_ports([("Line1", "start"), ("Line1", "end")])
    """
    ports = []
    for item in trace_ends:
        if isinstance(item, (tuple, list)):
            trace_name, end = item[0], item[1]
        else:
            trace_name, end = item, "end"
        ports.append(create_auto_wave_port(trace_name, end=end, **kwargs))
    return ports


# ---------------------------------------------------------------------------
# Edit this before running: list the (trace_name, end) pairs you want ports on.
# ---------------------------------------------------------------------------
create_auto_wave_ports(
    [("Line1", "start"), ("Line1", "end")],
    margin_mm=0.1,
    extend_full_layer=True,
)

oProject.Save()
