# -*- coding: utf-8 -*-
"""HFSS PEC-plane automation - native IronPython.

For a pad-shaped trace (e.g. a via land): builds a sheet sized to the
trace's own footprint (the arrow's span = its bounding box) on the
trace's top (or bottom) face, then grows it into a PEC cap by a
thickness entered at run time.
"""

import math
import clr
clr.AddReference("Microsoft.VisualBasic")
from Microsoft.VisualBasic import Interaction

oProject = oDesktop.GetActiveProject()
oDesign = oProject.GetActiveDesign()
oEditor = oDesign.SetActiveEditor("3D Modeler")

_MM_PER_UNIT = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "meter": 1000.0,
                "um": 0.001, "nm": 1e-6, "in": 25.4, "mil": 0.0254}


def _mm(value_mm, units):
    return value_mm / _MM_PER_UNIT.get(units.lower(), 1.0)


def _sanitize(name):
    out = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in name)
    if out and out[0].isdigit():
        out = "_" + out
    return out or "Pec"


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


def _delete_if_exists(name):
    try:
        if name in list(oEditor.GetMatchedObjectName(name)):
            oEditor.Delete(["NAME:Selections", "Selections:=", name])
    except Exception:
        pass


def _rect_at_z(name, cx, cy, w, h, z, units):
    x0, y0 = cx - w / 2.0, cy - h / 2.0
    params = ["NAME:RectangleParameters", "IsCovered:=", True,
              "XStart:=", str(x0) + units, "YStart:=", str(y0) + units, "ZStart:=", str(z) + units,
              "Width:=", str(w) + units, "Height:=", str(h) + units, "WhichAxis:=", "Z"]
    attrs = ["NAME:Attributes", "Name:=", name, "Flags:=", "", "Color:=", "(143 175 143)",
             "Transparency:=", 0.6, "PartCoordinateSystem:=", "Global", "UDMId:=", "",
             "MaterialValue:=", "\"vacuum\"", "SurfaceMaterialValue:=", "\"\"", "SolveInside:=", True,
             "ShellElement:=", False, "ShellElementThickness:=", "0mm", "IsMaterialEditable:=", True,
             "UseMaterialAppearance:=", False, "IsLightweight:=", False]
    oEditor.CreateRectangle(params, attrs)


def _pec_cap_from_sheet(sheet_name, cap_name, thickness_mil, units, grow_up=True):
    """Clone sheet_name, thicken it thickness_mil away from the board, pec it."""
    before = set(_solids_and_sheets())
    oEditor.Copy(["NAME:Selections", "Selections:=", sheet_name])
    oEditor.Paste()
    clone = list(set(_solids_and_sheets()) - before)[0]

    t = _mm(thickness_mil * 0.0254, units)
    sign = 1.0 if grow_up else -1.0
    oEditor.ThickenSheet(
        ["NAME:Selections", "Selections:=", clone, "NewPartsModelFlag:=", "Model"],
        ["NAME:SheetThickenParameters", "Thickness:=", str(sign * t) + units, "BothSides:=", False],
    )
    _delete_if_exists(cap_name)
    oEditor.ChangeProperty(
        ["NAME:AllTabs", ["NAME:Geometry3DAttributeTab", ["NAME:PropServers", clone],
                           ["NAME:ChangedProps", ["NAME:Name", "Value:=", cap_name],
                            ["NAME:Material", "Value:=", "\"pec\""]]]]
    )
    return cap_name


def create_pec_plane(trace_name, cap_mil, from_top=True):
    """Grow a PEC plane on trace_name's own footprint (sized by its bbox
    - the arrow). from_top=True builds it on the trace's top face and
    grows upward; False uses the bottom face, growing down.
    """
    units = oEditor.GetModelUnits()
    xmin, ymin, zmin, xmax, ymax, zmax = _bbox(trace_name)
    cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
    w, h = xmax - xmin, ymax - ymin
    z = zmax if from_top else zmin

    safe_name = _sanitize(trace_name)
    sheet_name = safe_name + "_pec_base"
    _delete_if_exists(sheet_name)
    _rect_at_z(sheet_name, cx, cy, w, h, z, units)

    cap_name = safe_name + "_pec"
    _pec_cap_from_sheet(sheet_name, cap_name, cap_mil, units, grow_up=from_top)
    _delete_if_exists(sheet_name)
    print("PEC plane: %s (%g%s x %g%s, %gmil)" % (cap_name, w, units, h, units, cap_mil))
    oProject.Save()
    return cap_name


def _selected_trace_names():
    """目前在3D Modeler視窗裡框選/點選的物件名稱。"""
    try:
        return [n for n in list(oEditor.GetSelections()) if n]
    except Exception:
        return []


def create_pec_planes(trace_names, cap_mil, **kwargs):
    """Batch version: one PEC plane per trace."""
    return [create_pec_plane(name, cap_mil, **kwargs) for name in trace_names]


# ---------------------------------------------------------------------------
# 先在3D Modeler視窗裡框選要長PEC平面的pad/via形狀，再執行本腳本：
# 會自動帶入目前選取的名稱，也可自行修改，多條用逗號分隔。
_selected = _selected_trace_names()
_default = ",".join(_selected)
_traces_in = Interaction.InputBox(
    "輸入物件名稱，多條用逗號分隔:", "PEC Plane Setup", _default)

if _traces_in:
    _trace_names = [t.strip() for t in _traces_in.split(",") if t.strip()]
    _cap_mil_in = Interaction.InputBox(
        "PEC要漲多高(mil):", "PEC Plane Setup", "2")
    if _cap_mil_in:
        create_pec_planes(_trace_names, float(_cap_mil_in))
    else:
        print("Cancelled: no thickness entered.")
else:
    print("Cancelled: no name entered.")
