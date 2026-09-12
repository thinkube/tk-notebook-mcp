# Copyright 2025 Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""tk-notebook-mcp: notebook operations for Claude, served by the Jupyter server."""

from ._version import __version__


def _jupyter_server_extension_points():
    from .extension import TKNotebookMCP

    return [{"module": "tk_notebook_mcp.extension", "app": TKNotebookMCP}]


__all__ = ["__version__", "_jupyter_server_extension_points"]
