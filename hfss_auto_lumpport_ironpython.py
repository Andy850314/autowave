# -*- coding: utf-8 -*-
"""HFSS PEC-wall automation - native IronPython.

For a pad-shaped trace (e.g. a via land): stands a PEC wall up along
the arrow line - a flat vertical sheet through the footprint center,
edge to edge (width = the arrow's span, from the trace's bounding
box), height = a thickness entered at run time.
"""

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


def _delete_if_exists(name):
    try:
        if name in list(oEditor.GetMatchedObjectName(name)):
            oEditor.Delete(["NAME:Selections", "Selections:=", name])
    except Exception:
        pass


def _wall_rect(name, x0, y_const, z0, w, h, units):
    """Flat vertical sheet in the XZ-plane at Y=y_const (normal along Y)."""
    params = ["NAME:RectangleParameters", "IsCovered:=", True,
              "XStart:=", str(x0) + units, "YStart:=", str(y_const) + units, "ZStart:=", str(z0) + units,
              "Width:=", str(w) + units, "Height:=", str(h) + units, "WhichAxis:=", "Y"]
    attrs = ["NAME:Attributes", "Name:=", name, "Flags:=", "", "Color:=", "(255 128 0)",
             "Transparency:=", 0.2, "PartCoordinateSystem:=", "Global", "UDMId:=", "",
             "MaterialValue:=", "\"pec\"", "SurfaceMaterialValue:=", "\"\"", "SolveInside:=", False,
             "ShellElement:=", False, "ShellElementThickness:=", "0mm", "IsMaterialEditable:=", True,
             "UseMaterialAppearance:=", False, "IsLightweight:=", False]
    oEditor.CreateRectangle(params, attrs)


def create_pec_wall(trace_name, cap_mil, from_top=True):
    """Stand a PEC wall along the arrow line (edge-to-edge through the
    footprint center, along X) at trace_name's top (or bottom) Z level.
    """
    units = oEditor.GetModelUnits()
    xmin, ymin, zmin, xmax, ymax, zmax = _bbox(trace_name)
    cy = (ymin + ymax) / 2.0
    w = xmax - xmin
    z0 = zmax if from_top else zmin
    h = _mm(cap_mil * 0.0254, units) * (1.0 if from_top else -1.0)

    name = _sanitize(trace_name) + "_pec"
    _delete_if_exists(name)
    _wall_rect(name, xmin, cy, z0, w, h, units)
    print("PEC wall: %s (%g%s wide, %gmil tall)" % (name, w, units, cap_mil))
    oProject.Save()
    return name


def _selected_trace_names():
    """目前在3D Modeler視窗裡框選/點選的物件名稱。"""
    try:
        return [n for n in list(oEditor.GetSelections()) if n]
    except Exception:
        return []


def create_pec_walls(trace_names, cap_mil, **kwargs):
    """Batch version: one PEC wall per trace."""
    return [create_pec_wall(name, cap_mil, **kwargs) for name in trace_names]


# ---------------------------------------------------------------------------
# 先在3D Modeler視窗裡框選要立PEC牆的pad/via形狀，再執行本腳本：
# 會自動帶入目前選取的名稱，也可自行修改，多條用逗號分隔。
_selected = _selected_trace_names()
_default = ",".join(_selected)
_traces_in = Interaction.InputBox(
    "輸入物件名稱，多條用逗號分隔:", "PEC Wall Setup", _default)

if _traces_in:
    _trace_names = [t.strip() for t in _traces_in.split(",") if t.strip()]
    _cap_mil_in = Interaction.InputBox(
        "PEC要立多高(mil):", "PEC Wall Setup", "2")
    if _cap_mil_in:
        create_pec_walls(_trace_names, float(_cap_mil_in))
    else:
        print("Cancelled: no height entered.")
else:
    print("Cancelled: no name entered.")
