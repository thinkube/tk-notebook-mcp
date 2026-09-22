# Copyright Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""The three HTTP endpoints, served by a bare tornado application."""

import json
import logging
from types import SimpleNamespace

from jupyter_server.auth.identity import IdentityProvider, User
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

from tk_notebook_mcp.handlers import HealthHandler, ToolCallHandler, ToolsListHandler
from tk_notebook_mcp.registry import ToolContext, ToolRegistry
from tk_notebook_mcp.tools.base import BaseTool, ok


class FixedIdentity(IdentityProvider):
    """Every request is the same signed-in user."""

    async def get_user(self, handler):
        return User("tester")


class Ping(BaseTool):
    name = "ping"
    description = "answers"
    input_schema = {"type": "object", "properties": {}, "required": []}

    async def execute(self, ctx, **kwargs):
        if kwargs.get("boom"):
            raise RuntimeError("boom")
        return ok(pong=True)


def make_registry():
    serverapp = SimpleNamespace(log=logging.getLogger("test"), root_dir="/", base_url="/", contents_manager=SimpleNamespace())
    registry = ToolRegistry(ToolContext(serverapp))
    registry.register(Ping())
    return registry


class HandlerTests(AsyncHTTPTestCase):
    def get_app(self):
        return Application(
            [
                (r"/api/tk-notebook/mcp/health", HealthHandler),
                (r"/api/tk-notebook/mcp/tools/list", ToolsListHandler),
                (r"/api/tk-notebook/mcp/tools/call", ToolCallHandler),
            ],
            tk_notebook_mcp_registry=make_registry(),
            identity_provider=FixedIdentity(),
            cookie_secret=b"test",
            disable_check_xsrf=True,
        )

    def test_health(self):
        response = self.fetch("/api/tk-notebook/mcp/health")
        assert response.code == 200
        body = json.loads(response.body)
        assert body["service"] == "tk-notebook-mcp" and body["tools"] == 1

    def test_list(self):
        body = json.loads(self.fetch("/api/tk-notebook/mcp/tools/list").body)
        assert body["tools"][0]["name"] == "ping"

    def test_call(self):
        response = self.fetch(
            "/api/tk-notebook/mcp/tools/call", method="POST", body=json.dumps({"tool": "ping", "arguments": {}})
        )
        assert response.code == 200
        assert json.loads(response.body) == {"success": True, "pong": True}

    def test_call_errors(self):
        assert self.fetch("/api/tk-notebook/mcp/tools/call", method="POST", body="not json").code == 400
        assert self.fetch("/api/tk-notebook/mcp/tools/call", method="POST", body=json.dumps({})).code == 400
        assert self.fetch("/api/tk-notebook/mcp/tools/call", method="POST", body=json.dumps({"tool": "none"})).code == 404
        response = self.fetch(
            "/api/tk-notebook/mcp/tools/call", method="POST", body=json.dumps({"tool": "ping", "arguments": {"boom": 1}})
        )
        assert response.code == 500
        assert "boom" in json.loads(response.body)["error"]
