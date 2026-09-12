# Copyright 2025 Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""The tool registry and the context every tool runs with."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .tools.base import BaseTool


@dataclass
class ToolContext:
    """Direct access to the Jupyter server's managers, handed to every tool call."""

    serverapp: Any

    @property
    def contents_manager(self) -> Any:
        return self.serverapp.contents_manager

    @property
    def kernel_manager(self) -> Any:
        return self.serverapp.kernel_manager

    @property
    def session_manager(self) -> Any:
        return self.serverapp.session_manager

    @property
    def kernel_spec_manager(self) -> Any:
        return self.serverapp.kernel_spec_manager

    @property
    def log(self) -> Any:
        return self.serverapp.log

    @property
    def root_dir(self) -> str:
        return self.serverapp.root_dir

    @property
    def preferred_dir(self) -> str:
        """The notebooks folder as an API path relative to the root, or an empty string."""
        return getattr(self.contents_manager, "preferred_dir", "") or ""


class ToolRegistry:
    """Holds the tools by name and runs them with the shared context."""

    def __init__(self, context: ToolContext):
        self.context = context
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool '{tool.name}' registered twice")
        self._tools[tool.name] = tool

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> List[str]:
        return list(self._tools)

    def describe(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    async def call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Run one tool. Every tool answers with a dict that carries ``success``."""
        tool = self._tools[name]
        self.context.log.info("tk-notebook-mcp: %s %s", name, _brief(arguments))
        result = await tool.execute(self.context, **arguments)
        if not isinstance(result, dict):
            result = {"success": True, "result": result}
        result.setdefault("success", "error" not in result)
        if result["success"]:
            self.context.log.info("tk-notebook-mcp: %s done", name)
        else:
            self.context.log.info("tk-notebook-mcp: %s failed: %s", name, result.get("error"))
        return result


def _brief(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Arguments for the log line, with long strings cut short."""
    brief = {}
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > 80:
            value = value[:77] + "..."
        brief[key] = value
    return brief
