"""HFSS wave-port automation utilities (PyAEDT).

Given a trace object in an HFSS 3D Modeler design ("Driven Modal" or
"Driven Terminal"), automatically build and assign a wave port sized as:

  - width  = trace width + a margin added on *each* side (0.1 mm by
    default, matching "x" / "y" in the reference sketch).
  - height (z) = the local dielectric "sandwich" around the trace,
    auto-detected by finding the nearest solid/sheet boundaries directly
    below and directly above the trace at the port location (the "layers
    that sandwich the line segment", per the reference sketch).

Run this from AEDT's own Python console, or externally through PyAEDT with
an HFSS design already open. Edit the ``__main__`` block at the bottom
before running it directly.
"""

import math

try:
    from ansys.aedt.core import Hfss  # PyAEDT >= 0.15
except ImportError:  # pragma: no cover - older PyAEDT releases
    from pyaedt import Hfss

# millimeters represented by one unit of each length unit AEDT can report
# via Modeler3D.model_units.
_MM_PER_UNIT = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "meter": 1000.0,
    "um": 0.001,
    "nm": 1e-6,
    "in": 25.4,
    "mil": 0.0254,
}


def _mm_to_model_units(hfss, value_mm: float) -> float:
    """Convert a value expressed in millimeters to the design's model units."""
    units = getattr(hfss.modeler, "model_units", "mm")
    factor = _MM_PER_UNIT.get(str(units).lower(), 1.0)
    return value_mm / factor


def _normalize(vx: float, vy: float) -> tuple:
    length = math.hypot(vx, vy)
    if length == 0:
        raise ValueError("Direction vector must not be zero-length.")
    return vx / length, vy / length


def find_sandwich_bounds(
    hfss,
    probe_x: float,
    probe_y: float,
    trace_zmin: float,
    trace_zmax: float,
    exclude_names,
    extend_full_layer: bool = True,
    z_tol: float = 1e-6,
):
    """Find the Z span of the layer(s) sandwiching the trace at (probe_x, probe_y).

    Scans every solid/sheet object in the design whose XY footprint contains
    the probe point and returns the Z boundaries of the closest object below
    the trace and the closest object above it - i.e. the layers that
    "sandwich" (夾層) the trace at that location.

    Parameters
    ----------
    extend_full_layer : bool, optional
        If ``True`` (default), the returned span covers the *entire*
        thickness of the layer below and the layer above (e.g. ground plane
        to ground plane for a stripline-like stackup). If ``False``, it only
        covers the trace's own contact boundaries with those layers (i.e.
        ``trace_zmin``/``trace_zmax``).

    Returns
    -------
    tuple
        ``(z_min, z_max, lower_object_name, upper_object_name)``
    """
    exclude = set(exclude_names)
    candidates = []
    for obj in list(hfss.modeler.solid_objects) + list(hfss.modeler.sheet_objects):
        if obj.name in exclude:
            continue
        xmin, ymin, zmin, xmax, ymax, zmax = obj.bounding_box
        if xmin - z_tol <= probe_x <= xmax + z_tol and ymin - z_tol <= probe_y <= ymax + z_tol:
            candidates.append((zmin, zmax, obj.name))

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
            f"Could not resolve a valid port height at ({probe_x}, {probe_y}): "
            f"z_min={z_min_port}, z_max={z_max_port}. Check exclude_names/geometry, "
            "or pass an explicit position away from object edges/gaps."
        )

    return z_min_port, z_max_port, lower[2], upper[2]


def create_auto_wave_port(
    hfss,
    trace_name: str,
    end: str = "end",
    margin_mm: float = 0.1,
    extend_full_layer: bool = True,
    direction=None,
    width_mm=None,
    position=None,
    port_name=None,
    reference=None,
    integration_line=None,
    is_microstrip: bool = False,
    renormalize: bool = True,
    impedance: float = 50,
    modes: int = 1,
):
    """Create and assign a wave port automatically sized around a trace end.

    Parameters
    ----------
    hfss : ansys.aedt.core.Hfss
        Active HFSS (3D Modeler, Driven Modal/Terminal) application.
    trace_name : str
        Name of the trace/conductor object the port terminates.
    end : str, optional
        Which end of the trace's bounding box to cut the port at:
        ``"start"`` or ``"end"``. Ignored if `position` is given explicitly.
        The default is ``"end"``.
    margin_mm : float, optional
        Extension added on *each* side of the trace width, in millimeters.
        The default is ``0.1`` (trace width + 0.1 mm on both sides).
    extend_full_layer : bool, optional
        See :func:`find_sandwich_bounds`. The default is ``True``.
    direction : tuple[float, float], optional
        Explicit in-plane (x, y) propagation direction at the cut. If
        omitted, it is inferred from the trace's bounding box (assumes an
        axis-aligned Manhattan trace routed along X or Y).
    width_mm : float, optional
        Explicit trace width in millimeters, measured perpendicular to
        `direction`. If omitted, it is inferred from the trace's bounding
        box (only valid for an axis-aligned trace).
    position : tuple[float, float], optional
        Explicit (x, y) point at which to cut the port. If omitted, it is
        derived from the trace's bounding box and `end`.
    port_name : str, optional
        Name for the created port. Defaults to ``"{trace_name}_{end}_port"``.
    reference : optional
        Reference conductor(s) for a Terminal solution. Passed through to
        :meth:`Hfss.wave_port`.
    integration_line : optional
        Integration line direction/points passed through to
        :meth:`Hfss.wave_port`. Defaults to ``hfss.axis_directions.ZPos``
        (vertical E-field, typical for a microstrip/stripline-like
        cross-section). Verify this points from the reference/ground
        conductor toward the signal conductor for your stackup and override
        it if not (e.g. ``hfss.axis_directions.ZNeg``, or an explicit
        ``[[x, y, z], [x, y, z]]`` pair of points).
    is_microstrip, renormalize, impedance, modes :
        Passed through to :meth:`Hfss.wave_port`.

    Returns
    -------
    ansys.aedt.core.modules.boundary.common.BoundaryObject
        The created wave port.
    """
    if end not in ("start", "end"):
        raise ValueError("end must be 'start' or 'end'.")

    trace = hfss.modeler[trace_name]
    if trace is None:
        raise ValueError(f"Object '{trace_name}' was not found in the design.")

    xmin, ymin, zmin, xmax, ymax, zmax = trace.bounding_box
    dx, dy = xmax - xmin, ymax - ymin

    if direction is None:
        along_x = dx >= dy
        direction = (1.0, 0.0) if along_x else (0.0, 1.0)
    else:
        along_x = abs(direction[0]) >= abs(direction[1])
    dir_x, dir_y = _normalize(*direction)
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
        width = _mm_to_model_units(hfss, width_mm)
    else:
        width = dy if along_x else dx
        if width <= 0:
            raise ValueError("Could not infer trace width from the bounding box; pass width_mm explicitly.")

    margin = _mm_to_model_units(hfss, margin_mm)
    half_extent = width / 2.0 + margin

    z_min_port, z_max_port, lower_name, upper_name = find_sandwich_bounds(
        hfss, px, py, zmin, zmax, exclude_names=[trace_name], extend_full_layer=extend_full_layer
    )
    hfss.logger.info(
        f"[{trace_name}/{end}] port width={2 * half_extent:g}{hfss.modeler.model_units}, "
        f"height={z_max_port - z_min_port:g}{hfss.modeler.model_units} "
        f"(layer below={lower_name}, layer above={upper_name})"
    )

    p0 = (px - perp_x * half_extent, py - perp_y * half_extent, z_min_port)
    p1 = (px + perp_x * half_extent, py + perp_y * half_extent, z_min_port)
    p2 = (px + perp_x * half_extent, py + perp_y * half_extent, z_max_port)
    p3 = (px - perp_x * half_extent, py - perp_y * half_extent, z_max_port)

    sheet_name = f"{trace_name}_{end}_port_sheet"
    sheet = hfss.modeler.create_polyline(
        points=[list(p0), list(p1), list(p2), list(p3)],
        cover_surface=True,
        close_surface=True,
        name=sheet_name,
    )

    if integration_line is None:
        integration_line = hfss.axis_directions.ZPos

    port_name = port_name or f"{trace_name}_{end}_port"
    port = hfss.wave_port(
        assignment=sheet.name,
        reference=reference,
        create_port_sheet=False,
        integration_line=integration_line,
        modes=modes,
        impedance=impedance,
        name=port_name,
        renormalize=renormalize,
        is_microstrip=is_microstrip,
    )
    return port


def create_auto_wave_ports(hfss, trace_ends, **kwargs):
    """Batch-create wave ports for a list of traces / (trace_name, end) pairs.

    Example
    -------
    >>> create_auto_wave_ports(hfss, [("Trace1", "start"), ("Trace1", "end")])
    """
    ports = []
    for item in trace_ends:
        trace_name, end = item if isinstance(item, (tuple, list)) else (item, "end")
        ports.append(create_auto_wave_port(hfss, trace_name, end=end, **kwargs))
    return ports


if __name__ == "__main__":
    # Example usage - edit the trace names/ends before running.
    # Hfss() with no arguments attaches to the active AEDT session and design.
    hfss = Hfss()

    create_auto_wave_ports(
        hfss,
        [("Line1", "start"), ("Line1", "end")],
        margin_mm=0.1,
        extend_full_layer=True,
    )

    hfss.save_project()
