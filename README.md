# HFSS Wave-Port Automation

PyAEDT script that automates wave-port creation on a trace end inside an
ANSYS HFSS 3D Modeler design (Driven Modal / Driven Terminal).

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

- `hfss_auto_waveport.py` - the automation module. Import it, or run it
  directly after editing the example block at the bottom.

## Requirements

- PyAEDT (`pip install pyaedt`, or the `ansys.aedt.core` package on newer
  releases - the script tries both import paths automatically).
- An HFSS design already open in AEDT (Driven Modal or Driven Terminal
  solution type), with the trace and its surrounding stackup solids/sheets
  already modeled.

## Usage

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
- `integration_line` (default `hfss.axis_directions.ZPos`): direction of
  the port's integration line. The default assumes a vertical E-field
  (ground below → signal above). **Verify this matches your stackup's
  reference conductor** and pass `hfss.axis_directions.ZNeg`, or an
  explicit `[[x, y, z], [x, y, z]]` point pair, if not.
- `reference`: reference conductor(s), needed for a Driven Terminal
  solution.

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
- The script assigns a **Modal** wave port by default. For a **Terminal**
  solution, pass the `reference` conductor(s) explicitly.
- This has not been run against a live AEDT session in this environment
  (no ANSYS install available here); the PyAEDT API calls were verified
  against the current PyAEDT source (`ansys.aedt.core.Hfss.wave_port`,
  `Modeler3D.create_polyline`, `Object3d.bounding_box`). Please do a
  smoke test on one trace before batch-running it across a full design.
