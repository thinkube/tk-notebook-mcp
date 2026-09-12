# Copyright 2025 Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""The registry, the tool list and the argument schemas."""

import logging
from types import SimpleNamespace

import pytest

from tk_notebook_mcp.registry import ToolContext, ToolRegistry
from tk_notebook_mcp.tools import all_tools
from tk_notebook_mcp.tools.base import BaseTool, error, ok


def make_context(**overrides):
    serverapp = SimpleNamespace(
        log=logging.getLogger("test"),
        root_dir="/home/user",
        base_url="/user/test/",
        contents_manager=SimpleNamespace(preferred_dir="thinkube/notebooks"),
        kernel_manager=None,
        session_manager=None,
        kernel_spec_manager=None,
    )
    for key, value in overrides.items():
        setattr(serverapp, key, value)
    return ToolContext(serverapp)


def test_every_tool_has_a_unique_name_and_an_object_schema():
    tools = all_tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names))
    for tool in tools:
        assert tool.description
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)
        for required in schema.get("required", []):
            assert required in schema["properties"], f"{tool.name}: '{required}' is required but not described"


def test_registry_describes_and_refuses_duplicates():
    registry = ToolRegistry(make_context())
    for tool in all_tools():
        registry.register(tool)
    assert len(registry) == len(all_tools())
    assert "use_notebook" in registry
    described = registry.describe()
    assert {"name", "description", "inputSchema"} <= set(described[0])
    with pytest.raises(ValueError):
        registry.register(all_tools()[0])


class Echo(BaseTool):
    name = "echo"
    description = "returns its arguments"
    input_schema = {"type": "object", "properties": {"value": {"type": "string"}}, "required": []}

    async def execute(self, ctx, **kwargs):
        if kwargs.get("fail"):
            return error("asked to fail")
        if kwargs.get("plain"):
            return "just text"
        return ok(value=kwargs.get("value"))


async def test_call_returns_the_tool_result_with_success():
    registry = ToolRegistry(make_context())
    registry.register(Echo())
    assert await registry.call("echo", {"value": "x"}) == {"success": True, "value": "x"}
    failed = await registry.call("echo", {"fail": True})
    assert failed["success"] is False and failed["error"] == "asked to fail"
    plain = await registry.call("echo", {"plain": True})
    assert plain == {"success": True, "result": "just text"}


async def test_unknown_tool_raises_key_error():
    registry = ToolRegistry(make_context())
    with pytest.raises(KeyError):
        await registry.call("missing", {})
