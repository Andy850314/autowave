# -*- coding: utf-8 -*-
"""HFSS wave-port automation - native IronPython (no pyaedt needed).

Port width = trace width + margin_mm on each side.
Port height = auto-detected from the layers sandwiching the trace.
Optional PEC cap grown outward as the port's reference plane.

Pick a port-side finder:
  - create_auto_wave_port_by_mask(trace, mask) - fastest, bbox vs mask,
    axis-aligned ends only.
  - find_port_face_on_mask(trace, mask) + create_auto_wave_port_from_face
    - works at any angle, tests each end face's contact with the mask.
  - find_other_end_face(trace, near_point) - no mask, farthest end from
    a known point.
  - create_auto_wave_port(trace, end=...) - simple straight trace.

Edit the bottom section, then run.
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
    """Names may only have letters/numbers/underscores."""
    out = []
    for ch in name:
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
    cleaned = "".join(out)
    if cleaned and cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned or "Port"


def get_bounding_box(obj_name):
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
    """Print an object's distinct corner points."""
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
    """Print candidate end (cross-section) faces - the small-area ones."""
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
    """Return the end face farthest from near_point (the known end)."""
    candidates = list_end_faces(obj_name, area_ratio=area_ratio)
    if not candidates:
        print("No candidate end faces found.")
        return None

    def dist(center):
        return math.hypot(center[0] - near_point[0], center[1] - near_point[1])

    ranked = sorted(candidates, key=lambda c: dist(c[2]))
    for fid, area, center in ranked:
        print("  face %s: distance=%.4f" % (fid, dist(center)))

    far_fid = ranked[-1][0]
    print("-> farthest: face %s" % far_fid)
    return far_fid


def _touches(position, obj_name):
    """True if obj_name is in contact with position (native query)."""
    units = oEditor.GetModelUnits()
    args = [
        "NAME:Parameters",
        "XPosition:=", str(position[0]) + units,
        "YPosition:=", str(position[1]) + units,
        "ZPosition:=", str(position[2]) + units,
    ]
    try:
        bodies = list(oEditor.GetBodyNamesByPosition(args))
    except Exception:
        bodies = []
    return obj_name in bodies


def find_port_face_on_mask(trace_name, mask_name, area_ratio=0.4):
    """Return the end face that's actually touching mask_name."""
    candidates = list_end_faces(trace_name, area_ratio=area_ratio)
    if not candidates:
        print("No candidate end faces found.")
        return None

    try:
        mask_bbox = get_bounding_box(mask_name)
        mask_z_candidates = [mask_bbox[2], mask_bbox[5]]
    except Exception as exc:
        print("Could not read bounding box of '%s': %s" % (mask_name, exc))
        mask_z_candidates = []

    matches = []
    for fid, area, center in candidates:
        probe_points = [center]
        for mz in mask_z_candidates:
            if abs(mz - center[2]) > 1e-9:
                probe_points.append((center[0], center[1], mz))
        touched = any(_touches(p, mask_name) for p in probe_points)
        print("face %s: touches '%s'? %s" % (fid, mask_name, touched))
        if touched:
            matches.append(fid)

    if len(matches) == 1:
        print("-> face %s" % matches[0])
        return matches[0]
    if len(matches) > 1:
        print("Multiple matches: %s - narrow down with area_ratio." % matches)
        return matches[0]
    print("No candidate touches '%s'." % mask_name)
    return None


def find_port_side_by_bbox(trace_name, mask_name, tol_mm=0.01):
    """Compare trace vs mask bounding boxes; return (end, direction) for
    whichever edge (xmax/xmin/ymax/ymin) lines up, or None.
    """
    units = oEditor.GetModelUnits()
    tol = _mm_to_model_units(tol_mm, units)

    t_xmin, t_ymin, t_zmin, t_xmax, t_ymax, t_zmax = get_bounding_box(trace_name)
    m_xmin, m_ymin, m_zmin, m_xmax, m_ymax, m_zmax = get_bounding_box(mask_name)

    checks = [
        ("xmax", abs(t_xmax - m_xmax), "end", (1.0, 0.0)),
        ("xmin", abs(t_xmin - m_xmin), "start", (1.0, 0.0)),
        ("ymax", abs(t_ymax - m_ymax), "end", (0.0, 1.0)),
        ("ymin", abs(t_ymin - m_ymin), "start", (0.0, 1.0)),
    ]
    for which, diff, end, direction in checks:
        print("%s: |trace - mask| = %g%s" % (which, diff, units))

    matches = [c for c in checks if c[1] <= tol]
    if not matches:
        print("No bbox edge matched within %g%s." % (tol, units))
        return None

    matches.sort(key=lambda c: c[1])
    which, diff, end, direction = matches[0]
    print("-> matched on %s: end=%s, direction=%s" % (which, end, direction))
    return end, direction


def create_auto_wave_port_by_mask(trace_name, mask_name, margin_mm=0.1, extend_full_layer=True,
                                   tol_mm=0.01, port_name=None, impedance=50, renormalize=True,
                                   pec_cap_mil=1):
    """Fast path: bbox-match against mask_name, build with CreateRectangle."""
    match = find_port_side_by_bbox(trace_name, mask_name, tol_mm=tol_mm)
    if match is None:
        return None
    end, direction = match

    units = oEditor.GetModelUnits()
    xmin, ymin, zmin, xmax, ymax, zmax = get_bounding_box(trace_name)
    dx, dy = xmax - xmin, ymax - ymin
    along_x = abs(direction[0]) >= abs(direction[1])

    if along_x:
        px = xmin if end == "start" else xmax
        py = (ymin + ymax) / 2.0
        width = dy
    else:
        px = (xmin + xmax) / 2.0
        py = ymin if end == "start" else ymax
        width = dx

    if width <= 0:
        raise ValueError("Could not infer trace width from bounding box.")

    margin = _mm_to_model_units(margin_mm, units)
    half_extent = width / 2.0 + margin

    z_min_port, z_max_port, lower_name, upper_name = find_sandwich_bounds(
        px, py, zmin, zmax, exclude_names=[trace_name], extend_full_layer=extend_full_layer
    )
    print("[%s/%s] port width=%g%s, height=%g%s (below=%s, above=%s)" % (
        trace_name, end, 2 * half_extent, units, z_max_port - z_min_port, units, lower_name, upper_name
    ))

    safe_trace_name = _sanitize_name(trace_name)
    sheet_name = "%s_%s_port_sheet" % (safe_trace_name, end)
    _delete_if_exists(sheet_name)
    _create_port_sheet_rect(sheet_name, along_x, px, py, half_extent, z_min_port, z_max_port, units)

    if pec_cap_mil:
        try:
            cap_name = _create_pec_reference_cap(sheet_name, trace_name, pec_cap_mil, units)
            print("PEC cap created: %s (%gmil)" % (cap_name, pec_cap_mil))
        except Exception as exc:
            print("PEC cap failed: %s" % exc)

    port_name = port_name or ("%s_%s_port" % (safe_trace_name, end))
    port_name = _sanitize_name(port_name)
    int_start = (px, py, z_min_port)
    int_stop = (px, py, z_max_port)
    _assign_wave_port(port_name, sheet_name, int_start, int_stop, units,
                       impedance=impedance, renormalize=renormalize)
    return port_name


def _face_cross_section(face_id):
    """Read a face's centroid, in-plane width direction, width, and Z span."""
    vids = list(oEditor.GetVertexIDsFromFace(face_id))
    pts = [[float(v) for v in oEditor.GetVertexPosition(vid)] for vid in vids]
    if len(pts) < 3:
        raise RuntimeError("Face %s has too few vertices." % face_id)

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
        raise RuntimeError("Face %s looks degenerate." % face_id)
    width, a, b = best
    perp_x, perp_y = _normalize(b[0] - a[0], b[1] - a[1])

    px = sum(p[0] for p in pts) / len(pts)
    py = sum(p[1] for p in pts) / len(pts)

    return px, py, perp_x, perp_y, width, zmin, zmax


def create_auto_wave_port_from_face(trace_name, face_id, end_label="end", margin_mm=0.1,
                                     extend_full_layer=True, port_name=None,
                                     impedance=50, renormalize=True, pec_cap_mil=1):
    """Build the port on a specific end face's own plane (any angle)."""
    units = oEditor.GetModelUnits()
    px, py, perp_x, perp_y, width, trace_zmin, trace_zmax = _face_cross_section(face_id)

    margin = _mm_to_model_units(margin_mm, units)
    half_extent = width / 2.0 + margin

    z_min_port, z_max_port, lower_name, upper_name = find_sandwich_bounds(
        px, py, trace_zmin, trace_zmax, exclude_names=[trace_name], extend_full_layer=extend_full_layer
    )
    print("[%s/face%s] port width=%g%s, height=%g%s (below=%s, above=%s)" % (
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
            print("PEC cap created: %s (%gmil)" % (cap_name, pec_cap_mil))
        except Exception as exc:
            print("PEC cap failed: %s" % exc)

    port_name = port_name or ("%s_%s_port" % (safe_trace_name, end_label))
    port_name = _sanitize_name(port_name)
    int_start = (px, py, z_min_port)
    int_stop = (px, py, z_max_port)
    _assign_wave_port(port_name, sheet_name, int_start, int_stop, units,
                       impedance=impedance, renormalize=renormalize)
    return port_name


def _delete_if_exists(name):
    """Clear a stray object left over from a previous failed attempt."""
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
    """Z span of the layers directly below/above the trace at (probe_x, probe_y)."""
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
            "Could not resolve a valid port height at (%s, %s): z_min=%s, z_max=%s." %
            (probe_x, probe_y, z_min_port, z_max_port)
        )
    return z_min_port, z_max_port, lower[2], upper[2]


def _create_port_sheet(sheet_name, p0, p1, p2, p3, units):
    """Covered, closed 4-point polygon via CreatePolyline."""
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
    """Axis-aligned port sheet via CreateRectangle."""
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
    before = set(get_solids_and_sheets())
    oEditor.Copy(["NAME:Selections", "Selections:=", name])
    oEditor.Paste()
    after = set(get_solids_and_sheets())
    new_names = list(after - before)
    if not new_names:
        raise RuntimeError("Clone of %s failed." % name)
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
    """Clone the port sheet, thicken outward into a thin PEC solid."""
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
    """Bbox-based port at one end of a straight, axis-aligned trace."""
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
            raise ValueError("Could not infer trace width; pass width_mm explicitly.")

    margin = _mm_to_model_units(margin_mm, units)
    half_extent = width / 2.0 + margin

    z_min_port, z_max_port, lower_name, upper_name = find_sandwich_bounds(
        px, py, zmin, zmax, exclude_names=[trace_name], extend_full_layer=extend_full_layer
    )
    print("[%s/%s] port width=%g%s, height=%g%s (below=%s, above=%s)" % (
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
            print("PEC cap created: %s (%gmil)" % (cap_name, pec_cap_mil))
        except Exception as exc:
            print("PEC cap failed: %s" % exc)

    port_name = port_name or ("%s_%s_port" % (safe_trace_name, end))
    port_name = _sanitize_name(port_name)
    int_start = (px, py, z_min_port)
    int_stop = (px, py, z_max_port)
    _assign_wave_port(port_name, sheet_name, int_start, int_stop, units,
                       impedance=impedance, renormalize=renormalize)
    return port_name


def create_auto_wave_ports(trace_ends, **kwargs):
    """Batch version: [(trace_name, end), ...]."""
    ports = []
    for item in trace_ends:
        if isinstance(item, (tuple, list)):
            trace_name, end = item[0], item[1]
        else:
            trace_name, end = item, "end"
        ports.append(create_auto_wave_port(trace_name, end=end, **kwargs))
    return ports


# ---------------------------------------------------------------------------
# Edit and run.
# ---------------------------------------------------------------------------
TRACE_NAME = "A__L0P"
MASK_NAME = "TOP"

create_auto_wave_port_by_mask(
    TRACE_NAME,
    MASK_NAME,
    margin_mm=0.1,
    extend_full_layer=True,
)
oProject.Save()

# If bbox comparison prints "No bbox edge matched" (angled port end):
#   FACE_ID = find_port_face_on_mask(TRACE_NAME, MASK_NAME)
#   if FACE_ID is not None:
#       create_auto_wave_port_from_face(TRACE_NAME, face_id=FACE_ID,
#           margin_mm=0.1, extend_full_layer=True)
#       oProject.Save()
