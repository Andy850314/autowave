# HFSS Wave-Port Automation

Automates wave-port creation on a trace end inside an ANSYS HFSS 3D Modeler
design (Driven Modal / Driven Terminal). Two versions are provided - pick
the one that matches how you run it:

- **`hfss_auto_waveport_ironpython.py`** - pure native scripting (`oEditor`,
  `oModule` calls), **no external packages**. Use this if you run scripts
  from AEDT's own Tools > Run Script console (that console is IronPython
  and cannot `import pyaedt`).
- **`hfss_auto_waveport.py`** - PyAEDT version. Use this if you run Python
  *outside* AEDT (a normal Python install with `pip install pyaedt`) and
  let it attach to the running AEDT session.

Both implement the same logic and expose the same parameters
(`create_auto_wave_port` / `create_auto_wave_ports`).

## What it does

For a chosen end of a trace object, it builds a rectangular port sheet and
assigns it as a wave port:

- **Width** (in-plane, perpendicular to the trace) = trace width + a margin
  added on *each* side (default `0.1 mm`, matching the `x` / `y` = 0.1 mm
  callouts in the reference sketch).
- **Height** (`z`) = auto-detected from the stackup: the script scans every
  solid/sheet object in the design at the port's (x, y) location and finds
  the nearest object boundary directly below the trace and directly above
  it - the layers that "sandwich" (夾層) the trace. By default the port
  spans the *full thickness* of both of those layers (e.g. ground plane to
  ground plane for an embedded/stripline-style trace, matching the first
  sketch where the trace's height already lines up with the blue/green
  layer boundaries).

The port sheet is built from 4 explicit 3D points via `create_polyline`
(covered + closed), so it works whether the trace runs along X, along Y, or
(if you pass an explicit `direction`) at an angle - no dependency on the
native `CreateRectangle` width/height-axis convention.

## Files

- `hfss_auto_waveport_ironpython.py` - native/IronPython version. Edit the
  `create_auto_wave_ports([...])` call near the bottom (trace names/ends),
  then in AEDT: **Tools > Run Script > Run Script...** and select this file
  (with the target HFSS design open and active). It runs top-to-bottom, no
  `import` of anything besides the standard `math` module.
- `hfss_auto_waveport.py` - the PyAEDT module. Import it, or run it
  directly after editing the example block at the bottom.

## Requirements

### `hfss_auto_waveport_ironpython.py`

- Nothing to install. Just AEDT itself, with the target HFSS design
  (Driven Modal or Driven Terminal) open and active, and the trace plus its
  surrounding stackup solids/sheets already modeled.

### `hfss_auto_waveport.py`

- PyAEDT (`pip install pyaedt`, or the `ansys.aedt.core` package on newer
  releases - the script tries both import paths automatically), run from a
  regular Python install *outside* AEDT.
- An HFSS design already open in AEDT (Driven Modal or Driven Terminal
  solution type), with the trace and its surrounding stackup solids/sheets
  already modeled.

## Usage

### IronPython (inside AEDT)

Open `hfss_auto_waveport_ironpython.py`, edit the call near the bottom:

```python
create_auto_wave_ports(
    [("Line1", "start"), ("Line1", "end")],
    margin_mm=0.1,
    extend_full_layer=True,
)
```

Then, with the HFSS design open in AEDT: **Tools > Run Script > Run
Script...**, pick the file. It creates the port sheet(s) and assigns the
wave port(s), then saves the project.

### PyAEDT (outside AEDT)

```python
from ansys.aedt.core import Hfss  # or: from pyaedt import Hfss
from hfss_auto_waveport import create_auto_wave_port, create_auto_wave_ports

hfss = Hfss()  # attaches to the active AEDT session/design

# Single port at the "start" end of a trace named "Line1"
create_auto_wave_port(hfss, "Line1", end="start")

# Both ends of the same trace, in one call
create_auto_wave_ports(hfss, [("Line1", "start"), ("Line1", "end")])

hfss.save_project()
```

### Key parameters (see docstrings for the full list)

- `margin_mm` (default `0.1`): extension added on each side of the trace
  width.
- `extend_full_layer` (default `True`): port height spans the full
  thickness of the layer below and the layer above the trace. Set to
  `False` to instead stop exactly at the trace's own top/bottom contact
  boundaries.
- `direction`, `width_mm`, `position`: manual overrides for traces that
  aren't axis-aligned, or where bounding-box inference isn't reliable
  (e.g. a curved/angled trace, or a pad instead of a straight segment).
- Integration line: both versions default to a vertical E-field, drawn
  from the bottom of the port (`z_min`, the layer below) to the top
  (`z_max`, the layer above) - i.e. ground below → signal above. **Verify
  this matches your stackup's reference conductor.** In
  `hfss_auto_waveport.py` this is the `integration_line` parameter
  (default `hfss.axis_directions.ZPos`; pass `hfss.axis_directions.ZNeg`,
  or an explicit `[[x, y, z], [x, y, z]]` point pair, to flip it). The
  IronPython version always uses the computed bottom→top points directly;
  swap `int_start`/`int_stop` in `_assign_wave_port` if you need it
  reversed.
- `reference` (PyAEDT version only): reference conductor(s), needed for a
  Driven Terminal solution. The IronPython version assigns a Modal wave
  port (no reference/terminal support) - extend `_assign_wave_port` if you
  need Terminal-solution ports.

## Assumptions and limitations

- Trace orientation is inferred from its bounding box, so auto-detection
  assumes an axis-aligned (Manhattan) trace segment at the cut location.
  For angled/curved traces, pass `direction` (and usually `width_mm`)
  explicitly.
- Layer detection is bounding-box based: it looks for objects whose XY
  footprint contains the port's (x, y) probe point, not for named stackup
  layers. If your stackup has coincident/zero-gap boundaries this works
  well (as in the reference sketch); if there are actual air gaps between
  the trace and its neighboring layer, the "sandwich" match may skip past
  the gap - use `position` to probe a spot away from anomalies, or narrow
  down with `exclude_names`-style filtering if you extend the script.
- Both scripts assign a **Modal** wave port. For a **Terminal** solution
  with `hfss_auto_waveport.py`, pass the `reference` conductor(s)
  explicitly.
- Neither script has been run against a live AEDT session in this
  environment (no ANSYS install available here). The PyAEDT calls were
  verified against the current PyAEDT source
  (`ansys.aedt.core.Hfss.wave_port`, `Modeler3D.create_polyline`,
  `Object3d.bounding_box`). The IronPython calls
  (`oEditor.GetObjectBoundingBox`, `oEditor.GetObjectsInGroup`,
  `oEditor.GetModelUnits`, `oEditor.CreatePolyline`,
  `oModule.AssignWavePort`) were cross-checked against PyAEDT's own
  underlying native-API argument construction (e.g.
  `Hfss._create_waveport_driven`, `Primitives._default_object_attributes`)
  and a recorded-macro `CreatePolyline` example, since PyAEDT wraps these
  exact same native calls internally. Please do a smoke test on one trace
  before batch-running either script across a full design.
