# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

`tk-notebook-mcp` is a Jupyter **server** extension. It has no frontend. It serves notebook tools over three HTTP endpoints under `/api/tk-notebook/mcp`, and thinkube-control forwards them to Claude Code as MCP operations. The wheel is installed into the `tk-jupyter-base` image from this repository's `latest` GitHub release.

## Layout

```
tk_notebook_mcp/
  extension.py        # the ExtensionApp: registers the tools, mounts the handlers
  handlers.py         # health, tools/list, tools/call
  registry.py         # ToolContext (the server's managers) and ToolRegistry
  tools/
    base.py           # BaseTool, ok(), error(), shared schema fragments
    paths.py          # notebook names -> contents API paths
    rooms.py          # the shared document of a notebook (jupyter_server_ydoc)
    kernels.py        # finding, holding and running code on a kernel
    outputs.py        # large outputs written beside the notebooks
    executions.py     # records of background runs, mirrored to disk
    notebooks.py      # use_notebook, close_notebook, list_notebooks, create_notebook
    cells.py          # list, read, insert, overwrite, delete, move
    execution.py      # execute_cell, the async and run-all tools, execute_ipython
    kernel_tools.py   # restart, interrupt, status, list_kernels, check_module
tests/                # pytest; no Jupyter server needed
```

## Rules the code follows

- A tool returns a dict with `success`; expected failures are `error("...")` in plain words, never exceptions.
- Every edit goes through the room (`get_room_document(..., create=True)`); reads try the room first, then the file.
- Every run goes through `kernels.run_code` under `hold_kernel`; one client per call, re-acquire the room before writing outputs.
- Argument names are the ones thinkube-control sends: `notebook_path`, `cell_index`, `content`, `position`.
- Comments say what the code does and the constraints it serves, nothing about how it came to be.

## Test and build

```bash
pip install -e ".[test]"
pytest
python -m build             # dist/tk_notebook_mcp-<version>-py3-none-any.whl
```

To try a build on the cluster without rebuilding the image, copy the wheel into the running notebook pod, `pip install --break-system-packages` it, and start a second Jupyter server on another port inside the pod; the pod's own server keeps the image's version.

## Release

Pushing to `main` runs the Build workflow, which tests, builds the wheel and publishes it on the `latest` release. Bump `version` in `pyproject.toml` and `tk_notebook_mcp/_version.py` together, and the wheel file name in `tk-jupyter-base.Containerfile.j2` in the `thinkube` repository.
