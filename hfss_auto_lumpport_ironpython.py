# -*- coding: utf-8 -*-
"""HFSS lump-port automation - native IronPython.

For a pad-shaped trace (e.g. a via land): builds a port sheet sized to
the trace's own footprint (the arrow's span = its bounding box), grows
a PEC cap cap_mil above it as the reference plane, and assigns a lumped
port with the integration line running edge-to-edge through the
footprint center (matching the arrow direction).
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


def create_lump_port(trace_name, cap_mil=2, port_index=1, impedance_ohm=50, from_top=True):
    """Lumped port on trace_name's own footprint (sized by its bbox - the
    arrow). from_top=True builds the sheet on the trace's top face and
    grows the PEC cap upward; False uses the bottom face, growing down.
    """
    units = oEditor.GetModelUnits()
    xmin, ymin, zmin, xmax, ymax, zmax = _bbox(trace_name)
    cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
    w, h = xmax - xmin, ymax - ymin
    z = zmax if from_top else zmin

    safe_name = _sanitize(trace_name)
    sheet_name = safe_name + "_lump_port_sheet"
    _delete_if_exists(sheet_name)
    _rect_at_z(sheet_name, cx, cy, w, h, z, units)

    cap_name = safe_name + "_lump_port_pec"
    _pec_cap_from_sheet(sheet_name, cap_name, cap_mil, units, grow_up=from_top)
    print("Lump port sheet: %s (%g%s x %g%s), PEC cap: %s (%gmil)" %
          (sheet_name, w, units, h, units, cap_name, cap_mil))

    # Integration line runs edge-to-edge through the center, along X -
    # matching the arrow direction. Swap Start/End or axis if the port
    # polarity comes out wrong.
    port_name = "LumpPort" + str(port_index)
    oModule.AssignLumpPort(
        ["NAME:" + port_name,
         "Objects:=", [sheet_name],
         "DoDeembed:=", False,
         "RenormalizeAllTerminals:=", True,
         ["NAME:Modes",
          ["NAME:Mode1",
           "ModeNum:=", 1,
           "UseIntLine:=", True,
           ["NAME:IntLine", "Start:=", [xmin, cy, z], "End:=", [xmax, cy, z]],
           "AlignmentGroup:=", 0,
           "CharImp:=", "Zpi"]],
         "ShowReporterFilter:=", False,
         "ReporterFilter:=", [True],
         "Impedance:=", str(impedance_ohm) + "ohm"]
    )
    oProject.Save()
    return sheet_name


def _selected_trace_names():
    """目前在3D Modeler視窗裡框選/點選的物件名稱。"""
    try:
        return [n for n in list(oEditor.GetSelections()) if n]
    except Exception:
        return []


def create_lump_ports(trace_names, **kwargs):
    """Batch version: one lump port per trace, port_index auto-increments."""
    ports = []
    for i, trace_name in enumerate(trace_names, start=1):
        ports.append(create_lump_port(trace_name, port_index=i, **kwargs))
    return ports


# ---------------------------------------------------------------------------
# 先在3D Modeler視窗裡框選要設Port的pad/via形狀，再執行本腳本：
# 會自動帶入目前選取的名稱，也可自行修改，多條用逗號分隔。
_selected = _selected_trace_names()
_default = ",".join(_selected)
_traces_in = Interaction.InputBox(
    "輸入物件名稱，多條用逗號分隔:", "Lump Port Setup", _default)

if _traces_in:
    _trace_names = [t.strip() for t in _traces_in.split(",") if t.strip()]
    create_lump_ports(_trace_names, cap_mil=2)
else:
    print("Cancelled: no name entered.")
