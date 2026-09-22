# tk-notebook-mcp

Notebook operations for Claude Code, served by the Jupyter server inside Thinkube Notebooks.

[![Build](https://github.com/thinkube/tk-notebook-mcp/workflows/Build/badge.svg)](https://github.com/thinkube/tk-notebook-mcp/actions)
[![License](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](LICENSE)

## What it does

A Jupyter server extension that lets a caller open a notebook, edit its cells, run them and read the outputs, with no JupyterLab tab open. thinkube-control forwards these operations to Claude Code as MCP tools; the extension itself only answers HTTP calls on the notebook server.

Every change goes through the notebook's shared document (jupyter_server_ydoc), so a tab that has the notebook open sees the edits and the outputs as they happen, and the document's own autosave writes them to disk.

## How it reaches a user

It is built into the Thinkube notebook image. The image `tk-jupyter-base` (`core/harbor-images/base-images/tk-jupyter-base.Containerfile.j2` in [thinkube](https://github.com/thinkube/thinkube)) installs the wheel from this repository's `latest` GitHub release, so every notebook server runs the extension. The Thinkube installer builds that image. thinkube-control calls the endpoints below on the user's notebook server (`backend/app/api/jupyter_notebooks.py` in thinkube-control) and offers them to Claude Code as MCP tools. The extension is not installed on its own.

The wheel enables itself through `etc/jupyter/jupyter_server_config.d/tk_notebook_mcp.json`. It needs `jupyter-server-ydoc` (JupyterLab's collaboration server) on the same server.

## Endpoints

All under the server's base URL, authenticated with the server's token:

| Method | Path | What it does |
|---|---|---|
| GET | `/api/tk-notebook/mcp/health` | Service name, version, number of tools |
| GET | `/api/tk-notebook/mcp/tools/list` | Every tool with its description and argument schema |
| POST | `/api/tk-notebook/mcp/tools/call` | Runs one tool: `{"tool": "<name>", "arguments": {...}}` |

A call answers with the tool's own result, a JSON object with `success` and, on failure, `error` in plain words.

## Tools

| Tool | What it does |
|---|---|
| `use_notebook` | Starts the notebook's kernel and shared document. Call it first. `kernel_name`, `create`, `needs_gpu`. |
| `close_notebook` | Saves the document and shuts the kernel down. |
| `list_notebooks`, `create_notebook` | The notebooks under the notebooks folder; a new one. |
| `list_cells`, `read_cell` | Cells by index; one cell's source and outputs. |
| `insert_cell`, `overwrite_cell`, `delete_cell`, `move_cell` | Edits. `insert_cell` takes `position`: `end` (the default), `above` or `below` a `cell_index`. |
| `execute_cell` | Runs one cell and waits. `timeout_seconds`, default 600; past it the kernel is interrupted. |
| `execute_cell_async`, `check_execution_status` | A long cell in the background, polled by id. `timeout_seconds`, default 3600. |
| `execute_all_cells`, `check_all_cells_status` | The whole notebook in the background, polled by id. `restart_kernel`, `stop_on_error`, `cell_timeout_seconds` (default 3600). |
| `insert_and_execute_cell` | Inserts a code cell and runs it. `timeout_seconds`, default 600. |
| `execute_ipython` | Runs code in the kernel without touching the notebook. `timeout_seconds`, default 300. |
| `restart_kernel`, `interrupt_kernel`, `get_kernel_status`, `list_kernels` | The kernel. |
| `check_module` | Whether packages are installed in the kernel's own environment. |

Paths are relative to the notebooks folder (`thinkube/notebooks`) or to the server root. A kernel is held by one call at a time; a second call waits five seconds and then says who holds it.

## Working on it

```bash
git clone https://github.com/thinkube/tk-notebook-mcp.git
cd tk-notebook-mcp
pip install -e ".[test]"
pytest
python -m build
```

A push to `main` builds the wheel and publishes it on the `latest` GitHub release (`.github/workflows/build.yml`). The notebook image installs the wheel by its versioned file name, so a version change in `pyproject.toml` also needs the file name in `tk-jupyter-base.Containerfile.j2` changed.

## License

BSD 3-Clause License. See [LICENSE](LICENSE). Parts of the kernel executor derive from jupyter-mcp-server by Datalayer, Inc.; the files that carry that code (`tools/execution.py`, `tools/kernels.py`, `tools/notebooks.py`) keep the Datalayer copyright line.
