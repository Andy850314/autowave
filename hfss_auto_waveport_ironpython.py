# -*- coding: utf-8 -*-
"""HFSS wave-port automation - native IronPython.

Finds the trace's port-side end by matching its bounding box against a
mask/boundary object, then picks the end face at the true extreme X or Y
on that side (never a mid-trace feature like a via bump). Port width =
that face's local width + margin_mm each side. Port height = the layers
sandwiching the trace. Grows a PEC cap outward as the reference plane.
"""

import math
import clr
clr.AddReference("Microsoft.VisualBasic")
from Microsoft.VisualBasic import Interaction

oProject = oDesktop.GetActiveProject()
oDesign = oProject.GetActiveDesign()
oEditor = oDesign.SetActiveEditor("3D Modeler")
oModule = oDesign.GetModule("BoundarySetup")

_MM_PER_UNIT = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "meter": 1000.0,
                "um": 0.001, "nm": 1e-6, "in": 25.4, "mil": 0.0254}


def _mm(value_mm, units):
    return value_mm / _MM_PER_UNIT.get(units.lower(), 1.0)


def _sanitize(name):
    out = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in name)
    if out and out[0].isdigit():
        out = "_" + out
    return out or "Port"


def _bbox(name):
    return [float(v) for v in oEditor.GetObjectBoundingBox(name)]


def _solids_and_sheets():
    names = []
    for g in ("Solids", "Sheets"):
        try:
            names.extend(list(oEditor.GetObjectsInGroup(g)))
        except Exception:
            pass
    return names


def _end_faces(name, area_ratio=0.4):
    """(face_id, area, center) for the small-area cross-section faces."""
    try:
        face_ids = list(oEditor.GetFaceIDs(name))
    except Exception as exc:
        print("Could not read faces of %s: %s" % (name, exc))
        return []
    areas = {}
    for fid in face_ids:
        try:
            areas[fid] = float(oEditor.GetFaceArea(fid))
        except Exception:
            pass
    if not areas:
        return []
    max_area = max(areas.values())
    out = []
    for fid, area in areas.items():
        if area <= area_ratio * max_area:
            try:
                center = [float(v) for v in oEditor.GetFaceCenter(fid)]
            except Exception:
                vids = list(oEditor.GetVertexIDsFromFace(fid))
                pts = [[float(v) for v in oEditor.GetVertexPosition(v_)] for v_ in vids]
                if not pts:
                    continue
                center = [sum(p[i] for p in pts) / len(pts) for i in range(3)]
            out.append((fid, area, center))
    return out


def _face_geometry(face_id):
    """centroid, in-plane width direction, width, Z span of a face."""
    vids = list(oEditor.GetVertexIDsFromFace(face_id))
    pts = [[float(v) for v in oEditor.GetVertexPosition(v_)] for v_ in vids]
    zmin, zmax = min(p[2] for p in pts), max(p[2] for p in pts)
    tol = (zmax - zmin) * 1e-6 or 1e-9
    level = [p for p in pts if abs(p[2] - zmin) <= tol] or pts
    width, a, b = max(
        ((math.hypot(a_[0] - b_[0], a_[1] - b_[1]), a_, b_)
         for i, a_ in enumerate(level) for b_ in level[i + 1:]),
        key=lambda t: t[0],
    )
    length = width or 1.0
    perp_x, perp_y = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    px = sum(p[0] for p in pts) / len(pts)
    py = sum(p[1] for p in pts) / len(pts)
    return px, py, perp_x, perp_y, width, zmin, zmax


def _sandwich_z(px, py, trace_zmin, trace_zmax, exclude, z_tol=1e-6):
    """Z span from the face of the layer touching the trace's bottom to
    the face of the layer touching its top (the contact surfaces, not
    those layers' own full thickness). Also returns those two layers'
    names, since they border the port face and belong in the port's
    reference conductors.
    """
    below, above = [], []
    for name in _solids_and_sheets():
        if name in exclude:
            continue
        xmin, ymin, zmin, xmax, ymax, zmax = _bbox(name)
        if not (xmin - z_tol <= px <= xmax + z_tol and ymin - z_tol <= py <= ymax + z_tol):
            continue
        if zmax <= trace_zmin + z_tol:
            below.append((zmin, zmax, name))
        if zmin >= trace_zmax - z_tol:
            above.append((zmin, zmax, name))
    lower = max(below, key=lambda z: z[1]) if below else (trace_zmin, trace_zmin, None)
    upper = min(above, key=lambda z: z[0]) if above else (trace_zmax, trace_zmax, None)
    z0, z1 = lower[1], upper[0]
    if z1 <= z0:
        raise RuntimeError("Bad port height at (%s, %s)." % (px, py))
    return z0, z1, lower[2], upper[2]


def _delete_if_exists(name):
    try:
        if name in list(oEditor.GetMatchedObjectName(name)):
            oEditor.Delete(["NAME:Selections", "Selections:=", name])
    except Exception:
        pass


def _create_rect(name, along_x, px, py, half_w, z0, z1, units):
    if along_x:
        axis, x0, y0, z, w, h = "X", px, py - half_w, z0, 2 * half_w, z1 - z0
    else:
        axis, x0, y0, z, w, h = "Y", px - half_w, py, z0, z1 - z0, 2 * half_w
    params = ["NAME:RectangleParameters", "IsCovered:=", True,
              "XStart:=", str(x0) + units, "YStart:=", str(y0) + units, "ZStart:=", str(z) + units,
              "Width:=", str(w) + units, "Height:=", str(h) + units, "WhichAxis:=", axis]
    attrs = ["NAME:Attributes", "Name:=", name, "Flags:=", "", "Color:=", "(143 175 143)",
             "Transparency:=", 0.6, "PartCoordinateSystem:=", "Global", "UDMId:=", "",
             "MaterialValue:=", "\"vacuum\"", "SurfaceMaterialValue:=", "\"\"", "SolveInside:=", True,
             "ShellElement:=", False, "ShellElementThickness:=", "0mm", "IsMaterialEditable:=", True,
             "UseMaterialAppearance:=", False, "IsLightweight:=", False]
    oEditor.CreateRectangle(params, attrs)


def _pec_cap(sheet_name, mask_name, along_x, is_max, thickness_mil, units):
    """Clone the port sheet, thicken it past the mask's own edge (outward,
    away from the board) - direction is known exactly from along_x/is_max
    (how the port side was matched), not guessed from the trace's bbox.
    """
    before = set(_solids_and_sheets())
    oEditor.Copy(["NAME:Selections", "Selections:=", sheet_name])
    oEditor.Paste()
    clone = list(set(_solids_and_sheets()) - before)[0]

    t = _mm(thickness_mil * 0.0254, units)
    mask_bbox = _bbox(mask_name)
    idx = (3 if is_max else 0) if along_x else (4 if is_max else 1)

    def thicken(val):
        oEditor.ThickenSheet(
            ["NAME:Selections", "Selections:=", clone, "NewPartsModelFlag:=", "Model"],
            ["NAME:SheetThickenParameters", "Thickness:=", str(val) + units, "BothSides:=", False],
        )

    thicken(t)
    clone_bbox = _bbox(clone)
    went_outward = (clone_bbox[idx] > mask_bbox[idx] + 1e-9) if is_max \
        else (clone_bbox[idx] < mask_bbox[idx] - 1e-9)
    if not went_outward:
        oDesign.Undo()
        thicken(-t)

    oEditor.ChangeProperty(
        ["NAME:AllTabs", ["NAME:Geometry3DAttributeTab", ["NAME:PropServers", clone],
                           ["NAME:ChangedProps", ["NAME:Material", "Value:=", "\"pec\""]]]]
    )
    return clone


def _assign_port(sheet_name, ref_names, port_index):
    """Matches AEDT's own recorded "Auto Identify Ports" macro: pick the
    port sheet's face, use the given conductors as reference. Every
    conductor actually bordering the port face must be listed here, or
    AutoIdentifyPorts treats it as its own (spurious) extra terminal.
    """
    face_id = oEditor.GetFaceIDs(sheet_name)[0]
    oModule.AutoIdentifyPorts(
        ["NAME:Faces", face_id],
        True,
        ["NAME:ReferenceConductors"] + list(ref_names),
        str(port_index),
        False,
    )


def create_wave_port(trace_name, mask_name, margin_mm=0.1, pec_cap_mil=1,
                      port_index=1, tol_mm=0.01, area_ratio=0.4):
    """Find the trace's mask-side end and build a wave port there."""
    units = oEditor.GetModelUnits()
    tol = _mm(tol_mm, units)

    t_xmin, t_ymin, t_zmin, t_xmax, t_ymax, t_zmax = _bbox(trace_name)
    m_xmin, m_ymin, m_zmin, m_xmax, m_ymax, m_zmax = _bbox(mask_name)

    checks = [c for c in [
        (abs(t_xmax - m_xmax), "x", True),
        (abs(t_xmin - m_xmin), "x", False),
        (abs(t_ymax - m_ymax), "y", True),
        (abs(t_ymin - m_ymin), "y", False),
    ] if c[0] <= tol]
    if not checks:
        raise RuntimeError("No bounding-box edge of '%s' matches '%s'." % (trace_name, mask_name))
    _, axis, is_max = min(checks, key=lambda c: c[0])
    along_x = axis == "x"
    print("matched axis=%s is_max=%s" % (axis, is_max))

    candidates = _end_faces(trace_name, area_ratio=area_ratio)
    if not candidates:
        raise RuntimeError("No candidate end faces found on %s." % trace_name)

    # The port end is always the face at the extreme X or Y - never a
    # mid-trace feature (e.g. a via bump), regardless of distance.
    key = (lambda c: c[2][0]) if along_x else (lambda c: c[2][1])
    fid = (max if is_max else min)(candidates, key=key)[0]

    px, py, perp_x, perp_y, width, trace_zmin, trace_zmax = _face_geometry(fid)
    margin = _mm(margin_mm, units)
    half_w = width / 2.0 + margin

    z0, z1, lower_name, upper_name = _sandwich_z(px, py, trace_zmin, trace_zmax, exclude=set([trace_name]))
    print("port width=%g%s height=%g%s (below=%s above=%s)" %
          (2 * half_w, units, z1 - z0, units, lower_name, upper_name))

    safe_name = _sanitize(trace_name)
    sheet_name = safe_name + "_port_sheet"
    _delete_if_exists(sheet_name)
    _create_rect(sheet_name, along_x, px, py, half_w, z0, z1, units)

    if not pec_cap_mil:
        raise ValueError("pec_cap_mil is required: the PEC cap is used as the port's reference conductor.")
    cap = _pec_cap(sheet_name, mask_name, along_x, is_max, pec_cap_mil, units)
    print("PEC cap: %s (%gmil)" % (cap, pec_cap_mil))

    # Every conductor touching the port face (the PEC cap, plus whatever
    # layers border the trace top/bottom) has to be in the reference
    # list, or it shows up as its own spurious terminal.
    refs = [cap]
    for n in (lower_name, upper_name):
        if n and n not in refs:
            refs.append(n)
    _assign_port(sheet_name, refs, port_index)
    oProject.Save()
    return sheet_name


def _selected_trace_names():
    """目前在3D Modeler視窗裡框選/點選的物件名稱。"""
    try:
        return [n for n in list(oEditor.GetSelections()) if n]
    except Exception:
        return []


def create_wave_ports(trace_names, mask_name, **kwargs):
    """Batch version: one wave port per trace, port_index auto-increments."""
    ports = []
    for i, trace_name in enumerate(trace_names, start=1):
        ports.append(create_wave_port(trace_name, mask_name, port_index=i, **kwargs))
    return ports


# ---------------------------------------------------------------------------
# 先在3D Modeler視窗裡框選要設Port的線段，再執行本腳本：
# 會自動帶入目前選取的線段名稱（逗號分隔），可直接確定或自行修改。
_selected = _selected_trace_names()
_default = ",".join(_selected) if _selected else "LINE1"
_traces_in = Interaction.InputBox(
    "線段名稱（已自動帶入目前框選的線段，多條用逗號分隔）：", "Wave Port Setup", _default)

if _traces_in:
    _trace_names = [t.strip() for t in _traces_in.split(",") if t.strip()]
    create_wave_ports(_trace_names, "TOP", margin_mm=0.1)
else:
    print("Cancelled: no trace name entered.")
