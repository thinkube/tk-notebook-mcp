# tk-notebook-mcp

Notebook operations for Claude Code, served by the Jupyter server inside Thinkube Notebooks.

[![Build](https://github.com/thinkube/tk-notebook-mcp/workflows/Build/badge.svg)](https://github.com/thinkube/tk-notebook-mcp/actions)
[![License](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](LICENSE)

## What it does

A Jupyter server extension that lets a caller open a notebook, edit its cells, run them and read the outputs, with no JupyterLab tab open. thinkube-control forwards these operations to Claude Code as MCP tools; the extension itself only answers HTTP calls on the notebook server.

Every change goes through the notebook's shared document (jupyter_server_ydoc), so a tab that has the notebook open sees the edits and the outputs as they happen, and the document's own autosave writes them to disk.

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
| `insert_cell`, `overwrite_cell`, `delete_cell`, `move_cell` | Edits. `insert_cell` takes `position`: `end`, `above` or `below` a `cell_index`. |
| `execute_cell` | Runs one cell and waits. `timeout_seconds`, default 600; past it the kernel is interrupted. |
| `execute_cell_async`, `check_execution_status` | A long cell in the background, polled by id. |
| `execute_all_cells`, `check_all_cells_status` | The whole notebook in the background, polled by id. `restart_kernel`, `stop_on_error`. |
| `insert_and_execute_cell` | Inserts a code cell and runs it. |
| `execute_ipython` | Runs code in the kernel without touching the notebook. |
| `restart_kernel`, `interrupt_kernel`, `get_kernel_status`, `list_kernels` | The kernel. |
| `check_module` | Whether packages are installed in the kernel's own environment. |

Paths are relative to the notebooks folder (`thinkube/notebooks`) or to the server root. A kernel is held by one call at a time; a second call waits five seconds and then says who holds it.

## Install

```bash
pip install https://github.com/thinkube/tk-notebook-mcp/releases/download/latest/tk_notebook_mcp-0.2.1-py3-none-any.whl
```

The wheel enables itself through `etc/jupyter/jupyter_server_config.d/tk_notebook_mcp.json`. It needs `jupyter-server-ydoc` (JupyterLab's collaboration server) on the same server.

## Develop

```bash
pip install -e ".[test]"
pytest
python -m build
```

## License

BSD-3-Clause. Parts of the kernel executor derive from jupyter-mcp-server by Datalayer, Inc.
