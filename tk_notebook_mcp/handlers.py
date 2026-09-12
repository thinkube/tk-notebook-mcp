# Copyright 2025 Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""HTTP handlers: health, the tool list and the tool call."""

import json

from jupyter_server.base.handlers import JupyterHandler
from tornado import web

from ._version import __version__


class _RegistryHandler(JupyterHandler):
    @property
    def registry(self):
        return self.settings["tk_notebook_mcp_registry"]


class HealthHandler(_RegistryHandler):
    """GET /api/tk-notebook/mcp/health"""

    @web.authenticated
    async def get(self):
        self.finish(
            {
                "status": "ok",
                "service": "tk-notebook-mcp",
                "version": __version__,
                "tools": len(self.registry),
            }
        )


class ToolsListHandler(_RegistryHandler):
    """GET /api/tk-notebook/mcp/tools/list"""

    @web.authenticated
    async def get(self):
        self.finish({"tools": self.registry.describe()})


class ToolCallHandler(_RegistryHandler):
    """POST /api/tk-notebook/mcp/tools/call with ``{"tool": name, "arguments": {...}}``.

    The response is the tool's own result: a JSON object with ``success`` and,
    on failure, ``error``. A tool that does not exist is a 404; a request that
    is not JSON or names no tool is a 400; a tool that raises is a 500 whose
    body carries the exception text.
    """

    @web.authenticated
    async def post(self):
        try:
            body = json.loads(self.request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.set_status(400)
            self.finish({"success": False, "error": "request body must be JSON"})
            return

        tool_name = body.get("tool")
        arguments = body.get("arguments") or {}
        if not tool_name:
            self.set_status(400)
            self.finish({"success": False, "error": "'tool' is required"})
            return
        if not isinstance(arguments, dict):
            self.set_status(400)
            self.finish({"success": False, "error": "'arguments' must be an object"})
            return
        if tool_name not in self.registry:
            self.set_status(404)
            self.finish({"success": False, "error": f"tool '{tool_name}' not found"})
            return

        try:
            result = await self.registry.call(tool_name, arguments)
        except Exception as e:
            self.log.error("tk-notebook-mcp: %s raised: %s", tool_name, e, exc_info=True)
            self.set_status(500)
            self.finish({"success": False, "error": f"{type(e).__name__}: {e}"})
            return

        self.finish(result)
