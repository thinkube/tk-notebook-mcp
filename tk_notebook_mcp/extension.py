# Copyright 2025 Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""The Jupyter server extension."""

from jupyter_server.extension.application import ExtensionApp

from .handlers import HealthHandler, ToolCallHandler, ToolsListHandler
from .registry import ToolContext, ToolRegistry
from .tools import all_tools


class TKNotebookMCP(ExtensionApp):
    """Serves the notebook tools under ``/api/tk-notebook/mcp``."""

    name = "tk_notebook_mcp"
    extension_url = "/tk-notebook"

    def initialize_settings(self):
        registry = ToolRegistry(ToolContext(self.serverapp))
        for tool in all_tools():
            registry.register(tool)
        self.settings["tk_notebook_mcp_registry"] = registry
        self.log.info("tk-notebook-mcp: %d tools registered", len(registry))

    def initialize_handlers(self):
        self.handlers.extend(
            [
                (r"/api/tk-notebook/mcp/health", HealthHandler),
                (r"/api/tk-notebook/mcp/tools/list", ToolsListHandler),
                (r"/api/tk-notebook/mcp/tools/call", ToolCallHandler),
            ]
        )


def _jupyter_server_extension_points():
    return [{"module": "tk_notebook_mcp.extension", "app": TKNotebookMCP}]
