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

It also grows a thin PEC-backed solid outward from the port sheet (away
from the trace), by default 1 mil thick, to use as the wave port's
reference plane (see pec_cap_mil on create_auto_wave_port).

For a BENT/ANGLED trace, automatic start/end detection from the trace's
overall bounding box does not reliably find the right corner (it mixes
both segments), and even a manually-picked point/direction is easy to get
slightly wrong. The robust fix: read the trace's actual terminal face
directly off its geometry.

  1. list_end_faces("TraceName")  - prints each small "end" face (the
     real cross-section the trace terminates on) with its center, so you
     can match it to the corner you want (e.g. where your arrow points).
  2. create_auto_wave_port_from_face("TraceName", face_id)  - builds the
     port exactly on that face's own plane (its real width direction and
     Z span), no direction guessing at all - works at any angle.

If you already know where ONE end of the trace is (e.g. its start) and
just want the port automatically at the OTHER end, skip picking a face_id
by eye: find_other_end_face("TraceName", near_point=(x, y)) ranks every
candidate end face by distance from that known point and returns the
farthest one's face id - pass that straight into
create_auto_wave_port_from_face.

create_auto_wave_port / create_auto_wave_ports (bounding-box based, with
optional manual position/direction_from) are still here for a simple
straight axis-aligned trace, but for a bent/angled one prefer the
face-based path above.

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


def _sanitize_name(name):
    """AEDT part/boundary names allow only letters, numbers, underscores.

    Trace/net names often contain '.', '-', '+', spaces, etc. (e.g.
    "RF_OUT+", "U1.Net2"), which fail with "Invalid part name" if used
    directly to build a new object/boundary name. Replace anything else
    with '_', and make sure it doesn't start with a digit.
    """
    out = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("_")
    cleaned = "".join(out)
    if cleaned and cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned or "Port"


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


def list_vertices(obj_name, ndigits=4):
    """Print and return the distinct (x, y, z) corner points of an object.

    Use this on a bent/angled trace to find the exact corner to cut the
    port at: automatic bounding-box based endpoint detection only works
    for a straight, axis-aligned segment. Run this first, read the
    printed coordinates off the corner near where you want the port
    (matching what you see in the 3D view), and pass that as `position`
    (plus another nearby point on the same segment as `direction_from`)
    to create_auto_wave_port.
    """
    try:
        ids = oEditor.GetVertexIDsFromObject(obj_name)
    except Exception as exc:
        print("Could not read vertices of %s: %s" % (obj_name, exc))
        return []
    seen_keys = set()
    verts = []
    for vid in ids:
        pos = [float(v) for v in oEditor.GetVertexPosition(vid)]
        key = (round(pos[0], ndigits), round(pos[1], ndigits), round(pos[2], ndigits))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        verts.append(pos)
        print("(x=%.4f, y=%.4f, z=%.4f)" % (pos[0], pos[1], pos[2]))
    return verts


def list_end_faces(obj_name, area_ratio=0.4):
    """Print candidate 'end' (cross-section) faces of a swept/extruded trace.

    A long thin trace's end faces (the true terminal cross-sections) are
    normally much smaller in area than its top/bottom/side walls - this
    holds regardless of how many bends or what angle the trace has. Prints
    every face whose area is <= area_ratio times the largest face's area,
    with its center, so you can match it against the corner you actually
    want a port on (compare the printed center to what you see in the 3D
    view / the arrow you're pointing at). Then pass its face id to
    create_auto_wave_port_from_face.
    """
    try:
        face_ids = list(oEditor.GetFaceIDs(obj_name))
    except Exception as exc:
        print("Could not read faces of %s: %s" % (obj_name, exc))
        return []
    areas = {}
    for fid in face_ids:
        try:
            areas[fid] = float(oEditor.GetFaceArea(fid))
        except Exception:
            continue
    if not areas:
        return []
    max_area = max(areas.values())
    candidates = []
    for fid, area in areas.items():
        if area <= area_ratio * max_area:
            try:
                center = [float(v) for v in oEditor.GetFaceCenter(fid)]
            except Exception:
                # GetFaceCenter can fail on a non-planar face (e.g. a
                # rounded/filleted corner counted as a small face too) -
                # fall back to the average of its own vertices instead of
                # dropping it silently.
                try:
                    vids = list(oEditor.GetVertexIDsFromFace(fid))
                    pts = [[float(v) for v in oEditor.GetVertexPosition(vid)] for vid in vids]
                    if not pts:
                        raise RuntimeError("no vertices")
                    center = [sum(p[i] for p in pts) / len(pts) for i in range(3)]
                except Exception as exc2:
                    print("face %s: area=%.6g, center unavailable (%s) - skipped" % (fid, area, exc2))
                    continue
            candidates.append((fid, area, center))
            print("face %s: area=%.6g, center=(x=%.4f, y=%.4f, z=%.4f)" %
                  (fid, area, center[0], center[1], center[2]))
    return candidates


def find_other_end_face(obj_name, near_point, area_ratio=0.4):
    """Given ONE known end of a trace (e.g. its start - point "1" in a
    sketch), find the face at the OTHER end automatically: the candidate
    end face farthest (by XY distance) from `near_point`. Useful for a
    long meandering trace where you know where it starts but want the
    port built at whichever end that isn't, without reading its
    coordinates off the 3D view by eye.

    near_point : (x, y) - approximately where the known end is (doesn't
        need to be exact, just closer to that end than to the other one).

    Prints every candidate with its distance from near_point, so you can
    sanity-check the pick before using it, then returns the farthest
    face's id (or None if no candidates were found).
    """
    candidates = list_end_faces(obj_name, area_ratio=area_ratio)
    if not candidates:
        print("No candidate end faces found.")
        return None

    def dist(center):
        return math.hypot(center[0] - near_point[0], center[1] - near_point[1])

    ranked = sorted(candidates, key=lambda c: dist(c[2]))
    print("Ranked by distance from (%.4f, %.4f):" % (near_point[0], near_point[1]))
    for fid, area, center in ranked:
        print("  face %s: distance=%.4f" % (fid, dist(center)))

    far_fid = ranked[-1][0]
    print("-> farthest from the given point: face %s (use this as the port side)" % far_fid)
    return far_fid


def _face_cross_section(face_id):
    """Read a rectangular end face's own geometry: centroid (px, py), the
    in-plane width direction (perp_x, perp_y) perpendicular to the trace's
    local propagation direction, the width, and the face's own Z span.

    Read straight off the face's actual vertices, so it's exact no matter
    what angle the trace's last segment runs at - no direction guessing.
    """
    vids = list(oEditor.GetVertexIDsFromFace(face_id))
    pts = [[float(v) for v in oEditor.GetVertexPosition(vid)] for vid in vids]
    if len(pts) < 3:
        raise RuntimeError("Face %s does not have enough vertices to define a cross-section." % face_id)

    zmin = min(p[2] for p in pts)
    zmax = max(p[2] for p in pts)
    tol = (zmax - zmin) * 1e-6 if zmax > zmin else 1e-9

    bottom = [p for p in pts if abs(p[2] - zmin) <= tol]
    level = bottom if len(bottom) >= 2 else pts

    best = None
    for i in range(len(level)):
        for j in range(i + 1, len(level)):
            d = math.hypot(level[j][0] - level[i][0], level[j][1] - level[i][1])
            if best is None or d > best[0]:
                best = (d, level[i], level[j])
    if best is None or best[0] == 0:
        raise RuntimeError("Face %s looks degenerate (no width found)." % face_id)
    width, a, b = best
    perp_x, perp_y = _normalize(b[0] - a[0], b[1] - a[1])

    px = sum(p[0] for p in pts) / len(pts)
    py = sum(p[1] for p in pts) / len(pts)

    return px, py, perp_x, perp_y, width, zmin, zmax


def create_auto_wave_port_from_face(trace_name, face_id, end_label="end", margin_mm=0.1,
                                     extend_full_layer=True, port_name=None,
                                     impedance=50, renormalize=True, pec_cap_mil=1):
    """Create and assign a wave port using a trace's actual end (cross-section)
    face - the exact plane the trace terminates on, however it bends or
    angles leading up to it. Use list_end_faces(trace_name) first to find
    the right face_id (compare each candidate's printed center against
    where you want the port).
    """
    units = oEditor.GetModelUnits()
    px, py, perp_x, perp_y, width, trace_zmin, trace_zmax = _face_cross_section(face_id)

    margin = _mm_to_model_units(margin_mm, units)
    half_extent = width / 2.0 + margin

    z_min_port, z_max_port, lower_name, upper_name = find_sandwich_bounds(
        px, py, trace_zmin, trace_zmax, exclude_names=[trace_name], extend_full_layer=extend_full_layer
    )
    print("[%s/face%s] port width=%g%s, height=%g%s (layer below=%s, layer above=%s)" % (
        trace_name, face_id, 2 * half_extent, units, z_max_port - z_min_port, units, lower_name, upper_name
    ))

    p0 = (px - perp_x * half_extent, py - perp_y * half_extent, z_min_port)
    p1 = (px + perp_x * half_extent, py + perp_y * half_extent, z_min_port)
    p2 = (px + perp_x * half_extent, py + perp_y * half_extent, z_max_port)
    p3 = (px - perp_x * half_extent, py - perp_y * half_extent, z_max_port)

    safe_trace_name = _sanitize_name(trace_name)
    sheet_name = "%s_%s_port_sheet" % (safe_trace_name, end_label)
    _delete_if_exists(sheet_name)
    _create_port_sheet(sheet_name, p0, p1, p2, p3, units)

    if pec_cap_mil:
        try:
            cap_name = _create_pec_reference_cap(sheet_name, trace_name, pec_cap_mil, units)
            print("[%s/%s] PEC reference cap created: %s (%gmil)" % (trace_name, end_label, cap_name, pec_cap_mil))
        except Exception as exc:
            print("[%s/%s] PEC reference cap failed: %s" % (trace_name, end_label, exc))

    port_name = port_name or ("%s_%s_port" % (safe_trace_name, end_label))
    port_name = _sanitize_name(port_name)
    int_start = (px, py, z_min_port)
    int_stop = (px, py, z_max_port)
    _assign_wave_port(port_name, sheet_name, int_start, int_stop, units,
                       impedance=impedance, renormalize=renormalize)
    return port_name


def _delete_if_exists(name):
    """Delete a stray object left over from a previous failed attempt.

    Re-running this script while debugging can leave a partially-created
    object with the target sheet name around; a second CreatePolyline /
    CreateRectangle call with the same name then fails. Clear it first.
    """
    try:
        existing = list(oEditor.GetMatchedObjectName(name))
    except Exception:
        existing = []
    if name in existing:
        try:
            oEditor.Delete(["NAME:Selections", "Selections:=", name])
        except Exception as exc:
            print("Could not delete existing object %s: %s" % (name, exc))


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
    """Create a covered, closed 4-point polygon sheet via native CreatePolyline.

    Deliberately minimal - only PolylineParameters + PolylinePoints, no
    explicit PolylineSegments/PolylineXSection. AEDT fills those in with
    defaults (straight "Line" segments between consecutive points, and the
    closing edge from IsPolylineClosed) when they're omitted, matching how
    a plain closed polygon is recorded from the UI.
    """
    pts = [p0, p1, p2, p3]

    polyline_points = ["NAME:PolylinePoints"]
    for p in pts:
        polyline_points.append(
            ["NAME:PLPoint",
             "X:=", str(p[0]) + units,
             "Y:=", str(p[1]) + units,
             "Z:=", str(p[2]) + units]
        )

    polyline_parameters = [
        "NAME:PolylineParameters",
        "IsPolylineCovered:=", True,
        "IsPolylineClosed:=", True,
        polyline_points,
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


def _create_port_sheet_rect(sheet_name, along_x, px, py, half_extent, z_min_port, z_max_port, units):
    """Fallback: build the port sheet with native CreateRectangle instead.

    Simpler argument structure than CreatePolyline (no nested point/segment
    arrays), used automatically if CreatePolyline fails. WhichAxis follows
    AEDT's standard cyclic convention: axis "X" -> Width along Y, Height
    along Z; axis "Y" -> Width along Z, Height along X.
    """
    if along_x:
        which_axis = "X"
        x0, y0, z0 = px, py - half_extent, z_min_port
        width, height = 2 * half_extent, z_max_port - z_min_port
    else:
        which_axis = "Y"
        x0, y0, z0 = px - half_extent, py, z_min_port
        width, height = z_max_port - z_min_port, 2 * half_extent

    rect_parameters = [
        "NAME:RectangleParameters",
        "IsCovered:=", True,
        "XStart:=", str(x0) + units,
        "YStart:=", str(y0) + units,
        "ZStart:=", str(z0) + units,
        "Width:=", str(width) + units,
        "Height:=", str(height) + units,
        "WhichAxis:=", which_axis,
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

    oEditor.CreateRectangle(rect_parameters, attributes)


def _clone_object(name):
    """Copy+paste an object (oEditor.Copy / oEditor.Paste), return the clone's name."""
    before = set(get_solids_and_sheets())
    oEditor.Copy(["NAME:Selections", "Selections:=", name])
    oEditor.Paste()
    after = set(get_solids_and_sheets())
    new_names = list(after - before)
    if not new_names:
        raise RuntimeError("Clone of %s failed: no new object detected after paste." % name)
    return new_names[0]


def _thicken_sheet_native(name, thickness_expr, both_sides=False):
    oEditor.ThickenSheet(
        ["NAME:Selections", "Selections:=", name, "NewPartsModelFlag:=", "Model"],
        ["NAME:SheetThickenParameters", "Thickness:=", thickness_expr, "BothSides:=", both_sides],
    )


def _set_material(name, material):
    oEditor.ChangeProperty(
        ["NAME:AllTabs",
         ["NAME:Geometry3DAttributeTab",
          ["NAME:PropServers", name],
          ["NAME:ChangedProps",
           ["NAME:Material", "Value:=", "\"%s\"" % material]]]]
    )


def _create_pec_reference_cap(sheet_name, trace_name, thickness_mil, units):
    """Clone the port sheet and thicken it *outward* into a thin PEC solid,
    to use as the wave port's reference plane.

    Mirrors PyAEDT's own Hfss._create_pec_cap: thicken one way, and if the
    result stayed inside the trace's own bounding box (i.e. it grew toward
    the trace instead of away from it), undo that and thicken the other way.
    """
    thickness_val = _mm_to_model_units(thickness_mil * 0.0254, units)  # 1 mil = 0.0254 mm
    clone_name = _clone_object(sheet_name)
    trace_bbox = get_bounding_box(trace_name)

    _thicken_sheet_native(clone_name, str(thickness_val) + units, False)
    clone_bbox = get_bounding_box(clone_name)

    tol = 1e-9
    internal = False
    for i in range(6):
        a, b = trace_bbox[i], clone_bbox[i]
        if i < 3:
            if (b - a) > tol:
                internal = True
        else:
            if (b - a) < tol:
                internal = True

    if internal:
        oDesign.Undo()
        _thicken_sheet_native(clone_name, str(-thickness_val) + units, False)

    _set_material(clone_name, "pec")
    return clone_name


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
                           direction=None, direction_from=None, width_mm=None, position=None,
                           port_name=None, impedance=50, renormalize=True, pec_cap_mil=1):
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
        traces. Default: inferred from the trace's bounding box (only
        reliable for a straight, axis-aligned segment).
    direction_from : explicit (x, y) point on the same trace segment as
        `position`, used to compute `direction` as (position - direction_from)
        when `direction` itself isn't given. Handy for a bent trace: run
        list_vertices(trace_name) first, then pass the corner you want as
        `position` and any other point further back along that same
        segment as `direction_from`.
    width_mm : explicit trace width in mm, for when bounding-box inference
        isn't reliable (e.g. angled/bent trace, pad instead of a straight
        segment) - recommended whenever `position`/`direction_from` are
        used.
    position : explicit (x, y) point to cut the port at, overriding `end`.
        For a bent trace, get this from list_vertices(trace_name).
    pec_cap_mil : thickness in mil of a PEC-backed solid grown outward from
        the port sheet (away from the trace), used as the wave port's
        reference plane. Set to 0/None to skip it.
    """
    if end not in ("start", "end"):
        raise ValueError("end must be 'start' or 'end'.")

    units = oEditor.GetModelUnits()

    xmin, ymin, zmin, xmax, ymax, zmax = get_bounding_box(trace_name)
    dx, dy = xmax - xmin, ymax - ymin

    if direction is None and direction_from is not None and position is not None:
        direction = (position[0] - direction_from[0], position[1] - direction_from[1])

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

    safe_trace_name = _sanitize_name(trace_name)
    sheet_name = "%s_%s_port_sheet" % (safe_trace_name, end)
    _delete_if_exists(sheet_name)
    try:
        _create_port_sheet(sheet_name, p0, p1, p2, p3, units)
    except Exception as exc:
        print("CreatePolyline failed (%s); falling back to CreateRectangle." % exc)
        _create_port_sheet_rect(sheet_name, along_x, px, py, half_extent, z_min_port, z_max_port, units)

    if pec_cap_mil:
        try:
            cap_name = _create_pec_reference_cap(sheet_name, trace_name, pec_cap_mil, units)
            print("[%s/%s] PEC reference cap created: %s (%gmil)" % (trace_name, end, cap_name, pec_cap_mil))
        except Exception as exc:
            print("[%s/%s] PEC reference cap failed: %s" % (trace_name, end, exc))

    port_name = port_name or ("%s_%s_port" % (safe_trace_name, end))
    port_name = _sanitize_name(port_name)
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
# TRACE_NAME is your trace object.
#
# Option A - you know roughly where the trace STARTS (e.g. point "1" in a
# sketch) and just want the port automatically at the OTHER end: set
# START_POINT to that rough (x, y) location (get it via list_vertices(),
# or by hovering over it in AEDT's 3D view and reading the coordinate
# readout). find_other_end_face() then ranks every candidate end face by
# distance from START_POINT and picks the farthest one automatically.
#
# Option B - leave START_POINT as None: the script just prints every
# candidate end face's id/center via list_end_faces() so you can pick
# FACE_ID by eye instead, then re-run.
# ---------------------------------------------------------------------------
TRACE_NAME = "A__L0P"
START_POINT = None  # e.g. START_POINT = (12.3, 4.5)  - roughly where the trace starts
FACE_ID = None  # manual override - set this directly to skip START_POINT entirely

if FACE_ID is None and START_POINT is not None:
    FACE_ID = find_other_end_face(TRACE_NAME, near_point=START_POINT)
elif FACE_ID is None:
    list_end_faces(TRACE_NAME)
    print("Set START_POINT (roughly where the trace starts) or FACE_ID directly, then re-run.")

if FACE_ID is not None:
    create_auto_wave_port_from_face(
        TRACE_NAME,
        face_id=FACE_ID,
        margin_mm=0.1,
        extend_full_layer=True,
    )
    oProject.Save()
