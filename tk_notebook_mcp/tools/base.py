# Copyright Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""The base class every tool implements, and the two result helpers."""

from abc import ABC, abstractmethod
from typing import Any, Dict


def ok(**fields: Any) -> Dict[str, Any]:
    """A successful result."""
    return {"success": True, **fields}


def error(message: str, **fields: Any) -> Dict[str, Any]:
    """A failed result, with the reason in the tool's own words."""
    return {"success": False, "error": message, **fields}


class BaseTool(ABC):
    """A tool has a name, a description, a JSON schema for its arguments and an ``execute``.

    ``execute`` receives the ``ToolContext`` and the arguments as keywords, and
    returns a dict. Tools never raise for expected conditions; they return
    ``error(...)`` so the caller sees the reason.
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def input_schema(self) -> dict: ...

    @abstractmethod
    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]: ...


NOTEBOOK_PATH = {
    "type": "string",
    "description": (
        "Path of the notebook, relative to the notebooks folder "
        "(for example 'examples/research-assistant/00-platform-validation.ipynb') "
        "or to the server root."
    ),
}

CELL_INDEX = {
    "type": "integer",
    "description": "0-based position of the cell in the notebook (not the execution count).",
}
