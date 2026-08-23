---
name: paraview
description: Use the paraview MCP server (execute_python / get_state / get_screenshot) whenever a task needs numbers, arrays, or derived quantities out of mesh or simulation data, not only when a picture is requested -- OpenFOAM cases (.foam), VTK/VTU/VTP/PVD, EXODUS (.e/.ex2), CGNS, EnSight, XDMF, Fluent, Tecplot, STL/OBJ, CSV. Covers loading a file and listing its arrays and ranges, probing a point, sampling along a line, integrating or averaging over a patch or slice (flow rate, force, mean), min/max and where it occurs, mesh statistics, CSV/VTU export, and screenshots. Reach for it on your own initiative before writing an ad-hoc parser for a result file, and start a headless ParaView yourself if none is running (instructions inside).
---

# Getting data out of simulations with ParaView (paraview MCP server)

ParaView already reads every common mesh/result format, handles multiblock data,
time steps and decomposed cases, and hands you numpy arrays in three lines. Use it
for data extraction, not only for pictures; write a one-off file parser only when the
format is something ParaView cannot open.

## 1. Get a session

Call `bridge_status`. If `connected` is true, go to section 2.

If not, start a headless ParaView yourself (no GUI, ~2 s):

```shell
nohup pvpython --force-offscreen-rendering /path/to/paraview_mcp/bridge/paraview_mcp_bridge.py --standalone \
    > /tmp/paraview_mcp_bridge.log 2>&1 &
```

- `pvpython` ships with ParaView (`<ParaView install>/bin/pvpython`; honour
  `$PARAVIEW_MCP_PVPYTHON` if it is set). `/path/to/paraview_mcp` is the checkout the
  MCP server runs from (the `--directory` in its registration; `claude mcp get paraview`
  prints it).
- It is a long-lived listener on `127.0.0.1:9911` (`PARAVIEW_MCP_PORT` changes it, and
  must match the server's). Wait for `standalone bridge listening` in the log (~2 s),
  then call `bridge_status` again.
- Stop it with `pkill -f "[p]araview_mcp_bridge.py"`: it is a launcher plus a child
  process, so kill by command line, not by PID (the `[p]` keeps pkill from matching the
  shell that runs it).
- If the user wants to watch in the GUI instead, use the GUI ParaView with the bridge
  macro or `paraview --script=<bridge>` (see the project README); the recipes below are
  the same.
- On a machine with no display at all, wrap it in `xvfb-run -a ...` if screenshots crash.

## 2. How to work

- Many small `execute_python` calls, not one script. The namespace persists
  (`paraview.simple` is star-imported; your imports, readers and filters stay alive), and
  the value of the last expression comes back as `value` -- return small things (numbers,
  short lists, dicts), never a whole array or proxy.
- Pass `render=False` for data-only calls; render only when a picture is wanted.
- Every response carries `state` (sources, visibility, active source, time).
  `get_state(detail="arrays")` lists point/cell arrays with ranges for every source.
- On failure read both `error` and `vtk_messages`; VTK errors often raise no exception.
- Give `timeout_s` well above the 120 s default for big files or heavy filters.
- File paths are paths on the machine running ParaView (WSL vs. Windows differ).
- `Delete(obj); del obj` removes one source; `reset_session` wipes everything.

## 3. Recipes

Verified on ParaView 6.1.1 with an OpenFOAM cavity case (`check_recipes.py` next to
this file re-runs every block below against a running bridge). Each block assumes the
ones before it.

Load and inspect:

```python
case = "/path/to/case/case.foam"   # OpenFOAM needs an (empty) .foam file in the case dir: open(case, "a").close()
r = OpenDataFile(case)             # reader chosen by extension; OpenFOAMReader(FileName=case) to be explicit
r.UpdatePipeline()
di = r.GetDataInformation()
{"cells": di.GetNumberOfCells(), "points": di.GetNumberOfPoints(), "bounds": list(di.GetBounds()),
 "cell_arrays": r.CellData.keys(), "point_arrays": r.PointData.keys(), "times": list(r.TimestepValues)}
```

Time steps and ranges (readers sit at the first time step until told otherwise; call
`UpdatePipeline(t)` on the proxy you are about to read or Fetch):

```python
times = list(r.TimestepValues)
t = times[-1] if times else 0.0
r.UpdatePipeline(t)
{"p": r.CellData["p"].GetRange(), "|U|": r.CellData["U"].GetRange(-1), "Ux": r.CellData["U"].GetRange(0)}
```

Into numpy (the whole dataset is pulled into the ParaView process; for huge data reduce
first with Slice/ExtractSubset/etc. and Fetch the result):

```python
from paraview import servermanager as sm
from vtk.numpy_interface import dataset_adapter as dsa
import numpy as np, os
m = MergeBlocks(Input=r)          # multiblock (OpenFOAM, EXODUS) -> one grid; Fetch wants that
m.UpdatePipeline(t)
w = dsa.WrapDataObject(sm.Fetch(m))
U, p = np.array(w.CellData["U"]), np.array(w.CellData["p"])   # w.PointData[...] for point-centred data, w.Points for coordinates
{"Ux_max": float(U[:, 0].max()), "p_mean": float(p.mean()), "n_cells": int(len(p))}
```

Where is the maximum (cell data: use cell centres as the locations):

```python
cc = CellCenters(Input=m); cc.UpdatePipeline(t)
wc = dsa.WrapDataObject(sm.Fetch(cc))
i = int(np.argmax(wc.PointData["p"]))
{"p_max": float(wc.PointData["p"][i]), "at": np.array(wc.Points[i]).tolist()}
```

Probe one point:

```python
pr = ProbeLocation(Input=m, ProbeType="Fixed Radius Point Source")
pr.ProbeType.Center = [0.5, 0.5, 0.5]; pr.ProbeType.NumberOfPoints = 1; pr.ProbeType.Radius = 0.0
pr.UpdatePipeline(t)
wp = dsa.WrapDataObject(sm.Fetch(pr))
{"U": np.array(wp.PointData["U"][0]).tolist(), "p": float(wp.PointData["p"][0]),
 "inside_mesh": int(wp.PointData["vtkValidPointMask"][0])}
```

Sample along a line and export it (`SaveData` picks the writer by extension: .csv
.vtu .vtp .ply ...):

```python
pl = PlotOverLine(Input=m, Point1=[0.5, 0.0, 0.5], Point2=[0.5, 1.0, 0.5], Resolution=100)
pl.UpdatePipeline(t)
wl = dsa.WrapDataObject(sm.Fetch(pl))
s, Ux = np.array(wl.PointData["arc_length"]), np.array(wl.PointData["U"])[:, 0]
SaveData(os.path.join(os.path.dirname(case), "centerline.csv"), proxy=pl)   # columns U:0 U:1 U:2 p arc_length Points:0..2
{"n": int(len(s)), "Ux_min": float(Ux.min()), "Ux_max": float(Ux.max())}
```

Integrate or average over a boundary patch (OpenFOAM patches are separate mesh regions;
`list(r.MeshRegions.Available)` gives `internalMesh`, `patch/<name>`, `group/<name>`. A
second reader holding just the patch is the simplest way to get it; `IntegrateVariables`
returns the integral of every array plus `Area` or `Volume`):

```python
wall = OpenFOAMReader(FileName=case, MeshRegions=["patch/movingWall"])
wall.UpdatePipeline(t)
iv = IntegrateVariables(Input=wall); iv.UpdatePipeline(t)
wi = dsa.WrapDataObject(sm.Fetch(iv))
A = float(wi.CellData["Area"][0])
{"area": A, "p_mean": float(wi.CellData["p"][0]) / A, "U_mean": (np.array(wi.CellData["U"][0]) / A).tolist()}
```

Flow rate through a plane (for a curved surface put `SurfaceNormals(Input=..., ComputeCellNormals=1)`
before the Calculator and use `dot(U,Normals)`, then check the sign; for point-centred
data use `AttributeType="Point Data"`):

```python
sl = Slice(Input=m, SliceType="Plane"); sl.SliceType.Origin = [0.5, 0.5, 0.5]; sl.SliceType.Normal = [1, 0, 0]
un = Calculator(Input=sl, AttributeType="Cell Data", ResultArrayName="Un", Function="U_X")   # U . n for n = +x
q = IntegrateVariables(Input=un); q.UpdatePipeline(t)
wq = dsa.WrapDataObject(sm.Fetch(q))
{"flow_rate": float(wq.CellData["Un"][0]), "area": float(wq.CellData["Area"][0])}
```

Mesh statistics (keep `internalMesh` only: patch faces would add 2-D cells and skew
both numbers):

```python
mq = MeshQuality(Input=m); mq.HexQualityMeasure = "Scaled Jacobian"; mq.TetQualityMeasure = "Scaled Jacobian"
mq.UpdatePipeline(t)
cs = CellSize(Input=m, ComputeVolume=1); cs.UpdatePipeline(t)
{"cells": m.GetDataInformation().GetNumberOfCells(), "scaled_jacobian": mq.CellData["Quality"].GetRange(),
 "cell_volume": cs.CellData["Volume"].GetRange()}
```

Export a dataset, or show it and take a screenshot (then call the `get_screenshot` tool):

```python
SaveData(os.path.join(os.path.dirname(case), "internal.vtu"), proxy=m)
v = GetActiveViewOrCreate("RenderView"); v.ViewTime = t
d = Show(m, v); ColorBy(d, ("CELLS", "p")); d.RescaleTransferFunctionToDataRange(); ResetCamera(v); Render(v)
```

## 4. OpenFOAM specifics

- A `.foam` sentinel file (any name, empty) must exist in the case directory.
- Parallel results left in `processor*/`: `r.CaseType = "Decomposed Case"`.
- Time 0 is skipped by default and the time list is scanned once at load. To include
  0, or to pick up time directories a running solver wrote since:
  `r.SkipZeroTime = 0; r.SMProxy.InvokeCommand("Refresh"); r.UpdatePipelineInformation()`.
- Fields are cell-centred; `r.CellData` has them, `r.PointData` is empty. For point
  values set `r.Createcelltopointfiltereddata = 1` or apply `CellDatatoPointData`.
- `list(r.CellArrays.Available)` lists the fields; `r.CellArrays = ["U", "p"]` loads a
  subset (faster on big cases).
- Default `MeshRegions` is `internalMesh` only; keep it so for volume statistics and
  load patches through a second reader as above.
