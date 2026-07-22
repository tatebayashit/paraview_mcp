# ParaView MCP

English | [日本語](README_ja.md)

An MCP (Model Context Protocol) server for controlling ParaView with natural language. From an MCP client such as Claude Desktop or Claude Code, you can send Python code to a running ParaView instance and let an AI create visualizations, manipulate the pipeline, and check the result via screenshots.

This repository is a fork of [LLNL/paraview_mcp](https://github.com/LLNL/paraview_mcp), but the connection layer has been redesigned from the ground up (the authoritative spec is [docs/DESIGN.md](docs/DESIGN.md)). The upstream implementation relied on ParaView's pvserver collaboration-sync feature, which is deprecated and unstable in current ParaView releases. This fork replaces it with a much simpler approach: **send code strings to a small bridge that runs inside ParaView itself.**

## Supported platforms

- **OS**: Windows, WSL (e.g. Ubuntu), and native Linux are all supported. There's nothing OS-specific about this project -- if ParaView runs there, this should work.
- **ParaView**: verified against 6.1.1 (the bridge itself is written to work on ParaView 5.11+ / Python 3.9+).
- **MCP server side**: Python 3.10+ and [uv](https://docs.astral.sh/uv/) (installed below).

Running ParaView and the MCP server on the same OS is the simplest setup. Mixing OSes (e.g. Claude Desktop on Windows talking to ParaView inside WSL) also works -- see [Mixing OSes](#mixing-oses) below.

## How it works

```
Claude          ◄─ stdio (MCP) ─►  paraview-mcp server  ◄─ TCP 127.0.0.1:9911 ─►  bridge inside ParaView
(Desktop/Code)                     pure Python, no paraview dep    (NDJSON)          exec on the GUI main thread
```

- **Bridge** ([bridge/paraview_mcp_bridge.py](bridge/paraview_mcp_bridge.py)): a single file using only the standard library. It runs inside ParaView's embedded Python, receives code over a localhost TCP socket, and executes it on the GUI main thread. Register it as a macro once and it's a one-click launch from then on.
- **MCP server** (`paraview-mcp`): runs in a regular Python environment and does not depend on the `paraview` package at all, so there's no structural version-matching problem with ParaView.
- If the GUI is already connected to a pvserver, the bridge just uses that existing session -- no pvserver-side configuration or `--multi-clients` needed.

## Installation

A step-by-step guide, written so first-time users don't get stuck.

### 1. Get ParaView

If you don't already have it, download an installer for your OS from the [official ParaView site](https://www.paraview.org/download/). Prebuilt binaries are available for Windows, Linux, and macOS. If you're on WSL, installing the Linux build inside your WSL distro is the simplest route.

### 2. Install uv

This project manages Python packages with [uv](https://docs.astral.sh/uv/). uv handles everything from installing the right Python version to creating a virtual environment and installing dependencies, in a single command -- it removes most of the usual friction of setting up a Python project.

If you don't have uv yet, run one of the following depending on your OS.

**Linux / macOS / WSL** (in a terminal):

```shell
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows** (in PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installing, open a new terminal (or a new PowerShell window) and check that it worked:

```shell
uv --version
```

If a version number prints, you're set. If something goes wrong, see [uv's own installation docs](https://docs.astral.sh/uv/getting-started/installation/).

> Don't worry if you don't have Python 3.10+ installed already -- `uv sync` in the next step will fetch a suitable Python version automatically.

### 3. Clone this repository and set it up

```shell
git clone https://github.com/tatebayashit/paraview_mcp.git
cd paraview_mcp
uv sync
```

`uv sync` creates a virtual environment (`.venv`) and installs all the required Python packages automatically. If it finishes without errors, you're ready.

## Usage

### 1. ParaView side: start the bridge

1. Start ParaView (if you'll be using pvserver, connect to it first via File → Connect).
2. Start the bridge:
   - **Builtin session (the common case)**: Macros → Import new macro… to register `bridge/paraview_mcp_bridge.py`, then run that macro.
   - **Connected to pvserver**: don't register it as a macro -- instead, paste the contents of `bridge/paraview_mcp_bridge.py` directly into View → Python Shell and run it (see "Known limitations" below for why).
3. Success looks like these two lines (the second one confirms the timer-driven loop is actually running):

```
[paraview-mcp HH:MM:SS] listening on 127.0.0.1:9911
[paraview-mcp HH:MM:SS] bridge active (first tick fired)
```

**Autostart (optional)**: instead of steps 1-2, you can point ParaView at the bridge directly on startup with `--script` (verified on real hardware, and unaffected by the macro-related issue mentioned above). It can't be combined with `--state`, `--data`, or a positional data-file argument, though.

```shell
paraview --script /path/to/bridge/paraview_mcp_bridge.py
# a positional argument works the same way:
paraview /path/to/bridge/paraview_mcp_bridge.py
```

### 2. MCP client side: register the server

Claude Desktop (`claude_desktop_config.json`):

```json
"mcpServers": {
  "paraview": {
    "command": "uv",
    "args": ["run", "--directory", "/path/to/paraview_mcp", "paraview-mcp"]
  }
}
```

Claude Code:

```shell
claude mcp add paraview -- uv run --directory /path/to/paraview_mcp paraview-mcp
```

If you're running Claude Desktop on Windows against a server inside WSL, see [Mixing OSes](#mixing-oses) below.

### Tools

| Tool | Description |
|---|---|
| `execute_python(code, timeout_s=120, render=True)` | Runs Python code inside ParaView. `paraview.simple` is already imported, the namespace persists across calls, and the value of the trailing expression is returned (the same convention as IPython). Every response includes a summary of the current pipeline state (`state`) |
| `get_screenshot(max_width=1280, quality=80)` | Captures the active RenderView as a JPEG (sent as base64, so no file sharing is needed) |
| `bridge_status()` | Checks connectivity to the bridge, the ParaView version, and the session type (builtin / client-server). The first place to look when something isn't working |
| `get_state(detail="summary"\|"arrays"\|"full")` | Reads the pipeline state. `summary` gives the source list, active view, and time; `arrays` adds each source's point/cell arrays; `full` also adds bounds, cell counts, and representative properties |
| `reset_session(clear_pipeline=True, clear_namespace=True)` | Resets the pipeline (deletes all sources) and/or the execution namespace |

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PARAVIEW_MCP_PORT` | 9911 | The bridge's listening port / the port the server connects to (must match on both sides) |
| `PARAVIEW_MCP_HOST` | 127.0.0.1 | The host the server connects to (usually no need to change this) |
| `PARAVIEW_MCP_TOKEN` | none | If set, a shared secret checked on every request (set the same value on both sides) |
| `PARAVIEW_MCP_LOG` | none | Path to also write the server's logs to a file |

## Mixing OSes

Running ParaView, the MCP server, and the MCP client (e.g. Claude Desktop) all on the same OS is the simplest setup, and the one to try first -- Windows-only, WSL-only, and Linux-only all work as-is.

Mixing OSes is also supported. For example, if you want Claude Desktop on Windows talking to ParaView running inside WSL, the setup we've verified is to **run the MCP server on the same side as ParaView (inside WSL) and launch it via `wsl.exe`**:

```json
"mcpServers": {
  "paraview": {
    "command": "wsl.exe",
    "args": ["-d", "Ubuntu", "--", "/home/user/paraview_mcp/.venv/bin/paraview-mcp"]
  }
}
```

That way the actual traffic stays entirely inside WSL, so you don't need to think about Windows↔WSL networking at all.

The other direction -- ParaView on Windows, MCP server inside WSL -- depends on your WSL networking mode (NAT vs. mirrored) and version, so whether `127.0.0.1` reaches across the boundary can vary. Try it first; if the server can't reach the bridge, either set `PARAVIEW_MCP_HOST` to the actual reachable IP address instead of `127.0.0.1`, or fall back to putting both sides on the same OS as described above.

When the filesystem is split across OSes, file paths in code should be given **from the perspective of whichever side ParaView is running on** (screenshots are transferred as base64, so no shared filesystem is needed for those).

## Headless usage (no GUI)

```shell
pvpython --force-offscreen-rendering bridge/paraview_mcp_bridge.py --standalone [--port 9911]
```

A minimal setup where the AI drives ParaView with no GUI, and a human checks results via screenshots. CI uses this mode too.

## Security notes

- By design, this is an **arbitrary code execution service**. Whatever Python code the MCP client (an LLM) generates runs with the ParaView process's own privileges. There's no static analysis or sandboxing of the code. **The MCP client's own tool-call approval UI is the last line of defense** -- understand that before using this.
- The bridge only binds to 127.0.0.1. Remote exposure is not supported.
- On a shared machine, we recommend setting `PARAVIEW_MCP_TOKEN` (it guards against other local processes connecting to the bridge).

## Known limitations

- ParaView's GUI freezes while code is executing (it runs on the main thread, the same as manually applying a heavy filter). Don't force-quit just because the OS reports "Not Responding."
- There's no way to cancel code that's already running.
- Closing the RenderView that's hosting the bridge's timer stops the bridge. `bridge_status` will guide you to restart it when that happens.
- Output that bypasses vtkOutputWindow (vtkLogger output, or C++ writing straight to stdout/stderr) isn't captured in `vtk_messages` (it still shows up in the process's own console).
- **Known issue**: starting the bridge **via a registered macro** while connected to pvserver crashes ParaView with a segmentation fault. This reproduces even with unmodified verification code, so it's been isolated as a ParaView-side issue rather than something in this project (details: [docs/M1_PLAN.md](docs/M1_PLAN.md) §5 #8). **Workaround**: when connected to pvserver, start the bridge by pasting it into the Python Shell instead (macro registration is fine for builtin sessions).

## Development

```shell
uv sync --extra dev
uv run pytest tests/unit         # 96 tests, no ParaView needed
uv run pytest tests/integration  # needs a real pvpython (auto-skips if absent)
uv run ruff check bridge/ src/ tests/
```

- unit CI: [.github/workflows/unit.yml](.github/workflows/unit.yml) (Python 3.10-3.12)
- integration CI: [.github/workflows/integration.yml](.github/workflows/integration.yml) (ParaView 6.1.1 from conda-forge, via Xvfb)
- manual smoke test: [docs/SMOKE.md](docs/SMOKE.md)
- roadmap ([docs/DESIGN.md](docs/DESIGN.md) §13): M0 spike **done** → M1 MVP **done** (2026-07-19) → M2 hardening **done** (2026-07-21, [docs/M2_PLAN.md](docs/M2_PLAN.md)) → M3 UX **done** (2026-07-22, [docs/M3_PLAN.md](docs/M3_PLAN.md))

## About the upstream project

This repository is a fork of LLNL's ParaView-MCP and keeps its BSD-3-Clause license ([LICENSE](LICENSE) / [NOTICE](NOTICE)). The connection layer has been redesigned from scratch and this fork is developed independently, but the core idea -- controlling ParaView through MCP -- traces back to the original upstream work, so the demo and paper are credited here.

[![Video Title](https://img.youtube.com/vi/GvcBnAcIXp4/maxresdefault.jpg)](https://youtu.be/GvcBnAcIXp4)

S. Liu, H. Miao, and P.-T. Bremer, "Paraview-MCP: Autonomous Visualization Agents with Direct Tool Use," in Proc. IEEE VIS 2025 Short Papers, 2025.

```bibtex
@inproceedings{liu2025paraview,
  title={Paraview-MCP: Autonomous Visualization Agents with Direct Tool Use},
  author={Liu, S. and Miao, H. and Bremer, P.-T.},
  booktitle={Proc. IEEE VIS 2025 Short Papers},
  pages={00},
  year={2025},
  organization={IEEE}
}
```

Paraview_MCP was originally created by Shusen Liu (liu42@llnl.gov) and Haichao Miao (miao1@llnl.gov).

LLNL-CODE-2007260
