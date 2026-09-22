# Copyright Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""Reading and editing cells.

Reads come from the shared document when the notebook has one, else from the
file. Edits always go through the shared document, so an open tab sees them
and the room's autosave writes them to disk.
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional

from .base import CELL_INDEX, NOTEBOOK_PATH, BaseTool, error, ok
from .outputs import summarize_outputs
from .paths import display_path, resolve_notebook_path
from .rooms import cell_source, execution_states, get_room_document, read_cells

POSITION = {
    "type": "string",
    "enum": ["end", "above", "below"],
    "description": "Where the new cell goes: at the end (default), or above or below cell_index.",
    "default": "end",
}


def preview(source: str, width: int = 80) -> str:
    first = source.strip().split("\n", 1)[0]
    return first if len(first) <= width else first[: width - 3] + "..."


def insert_index(ydoc: Any, position: str, cell_index: Optional[int]) -> Optional[int]:
    count = len(ydoc.ycells)
    if position == "end":
        return count
    if cell_index is None:
        return None
    if position == "above":
        return max(0, min(cell_index, count))
    if position == "below":
        return max(0, min(cell_index + 1, count))
    return None


def insert_cell(ydoc: Any, index: int, cell_type: str, source: str) -> None:
    cell: Dict[str, Any] = {"cell_type": cell_type, "source": source, "metadata": {}}
    if cell_type == "code":
        cell["execution_count"] = None
        cell["outputs"] = []
    ycell = ydoc.create_ycell(cell)
    with ydoc.ycells.doc.transaction():
        ydoc.ycells.insert(index, ycell)


async def _open(ctx: Any, notebook_path: Optional[str]):
    """``(api_path, ydoc, error)`` for an edit."""
    if not notebook_path:
        return None, None, error("notebook_path is required")
    api_path = await resolve_notebook_path(ctx, notebook_path)
    if api_path is None:
        return None, None, error(f"notebook '{notebook_path}' not found", notebook_path=notebook_path)
    ydoc = await get_room_document(ctx.serverapp, api_path, create=True)
    if ydoc is None:
        return api_path, None, error(f"could not open the shared document of '{display_path(ctx, api_path)}'")
    return api_path, ydoc, None


def _in_range(ydoc: Any, index: Any, what: str = "cell_index") -> Optional[Dict[str, Any]]:
    if not isinstance(index, int) or isinstance(index, bool):
        return error(f"{what} must be an integer")
    if index < 0 or index >= len(ydoc.ycells):
        return error(f"{what} {index} is out of range; the notebook has {len(ydoc.ycells)} cells", cells=len(ydoc.ycells))
    return None


class ListCellsTool(BaseTool):
    @property
    def name(self) -> str:
        return "list_cells"

    @property
    def description(self) -> str:
        return "List the cells of a notebook: index, type, execution count and the first line of each."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"notebook_path": NOTEBOOK_PATH}, "required": ["notebook_path"]}

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        notebook_path = kwargs.get("notebook_path")
        if not notebook_path:
            return error("notebook_path is required")
        api_path = await resolve_notebook_path(ctx, notebook_path)
        if api_path is None:
            return error(f"notebook '{notebook_path}' not found", notebook_path=notebook_path)
        cells = await read_cells(ctx, api_path)
        states = await execution_states(ctx, api_path)
        listed = []
        for index, cell in enumerate(cells):
            source = cell_source(cell)
            entry: Dict[str, Any] = {
                "index": index,
                "cell_type": cell.get("cell_type", "unknown"),
                "preview": preview(source),
                "lines": source.count("\n") + 1 if source else 0,
            }
            if cell.get("cell_type") == "code":
                entry["execution_count"] = cell.get("execution_count")
                entry["has_error"] = any(o.get("output_type") == "error" for o in cell.get("outputs", []) or [])
                if index in states:
                    entry["execution_state"] = states[index]
            listed.append(entry)
        return ok(notebook_path=display_path(ctx, api_path), cells=listed, count=len(listed))


class ReadCellTool(BaseTool):
    @property
    def name(self) -> str:
        return "read_cell"

    @property
    def description(self) -> str:
        return "Read one cell: its full source and, for code, its execution count and outputs."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"notebook_path": NOTEBOOK_PATH, "cell_index": CELL_INDEX},
            "required": ["notebook_path", "cell_index"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        notebook_path = kwargs.get("notebook_path")
        cell_index = kwargs.get("cell_index")
        if not notebook_path or cell_index is None:
            return error("notebook_path and cell_index are required")
        api_path = await resolve_notebook_path(ctx, notebook_path)
        if api_path is None:
            return error(f"notebook '{notebook_path}' not found", notebook_path=notebook_path)
        cells = await read_cells(ctx, api_path)
        if not isinstance(cell_index, int) or cell_index < 0 or cell_index >= len(cells):
            return error(f"cell_index {cell_index} is out of range; the notebook has {len(cells)} cells", cells=len(cells))
        cell = cells[cell_index]
        result = ok(
            notebook_path=display_path(ctx, api_path),
            cell_index=cell_index,
            cell_type=cell.get("cell_type", "unknown"),
            source=cell_source(cell),
        )
        if cell.get("cell_type") == "code":
            result["execution_count"] = cell.get("execution_count")
            result["outputs"] = summarize_outputs(list(cell.get("outputs", []) or []))
        return result


class InsertCellTool(BaseTool):
    @property
    def name(self) -> str:
        return "insert_cell"

    @property
    def description(self) -> str:
        return "Insert a code or markdown cell at the end, or above or below a given cell."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notebook_path": NOTEBOOK_PATH,
                "content": {"type": "string", "description": "The cell's source."},
                "cell_type": {"type": "string", "enum": ["code", "markdown"], "default": "code"},
                "position": POSITION,
                "cell_index": {**CELL_INDEX, "description": "The cell that 'above' or 'below' refers to."},
            },
            "required": ["notebook_path", "content"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        content = kwargs.get("content")
        if content is None:
            content = kwargs.get("source")
        cell_type = kwargs.get("cell_type") or "code"
        position = kwargs.get("position") or "end"
        cell_index = kwargs.get("cell_index")
        if content is None:
            return error("content is required")
        if cell_type not in ("code", "markdown"):
            return error("cell_type must be 'code' or 'markdown'")
        api_path, ydoc, err = await _open(ctx, kwargs.get("notebook_path"))
        if err:
            return err
        index = insert_index(ydoc, position, cell_index)
        if index is None:
            return error("position 'above' or 'below' needs cell_index")
        insert_cell(ydoc, index, cell_type, content)
        return ok(notebook_path=display_path(ctx, api_path), cell_index=index, cell_type=cell_type, cells=len(ydoc.ycells))


class OverwriteCellTool(BaseTool):
    @property
    def name(self) -> str:
        return "overwrite_cell"

    @property
    def description(self) -> str:
        return "Replace a cell's source. Returns the previous source and a diff."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notebook_path": NOTEBOOK_PATH,
                "cell_index": CELL_INDEX,
                "content": {"type": "string", "description": "The new source."},
            },
            "required": ["notebook_path", "cell_index", "content"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        cell_index = kwargs.get("cell_index")
        content = kwargs.get("content")
        if content is None:
            content = kwargs.get("source")
        if content is None or cell_index is None:
            return error("cell_index and content are required")
        api_path, ydoc, err = await _open(ctx, kwargs.get("notebook_path"))
        if err:
            return err
        err = _in_range(ydoc, cell_index)
        if err:
            return err
        cell = ydoc.get_cell(cell_index)
        previous = cell_source(cell)
        cell["source"] = content
        ydoc.set_cell(cell_index, cell)
        diff = "\n".join(
            difflib.unified_diff(previous.splitlines(), content.splitlines(), "before", "after", lineterm="", n=1)
        )
        return ok(
            notebook_path=display_path(ctx, api_path),
            cell_index=cell_index,
            cell_type=cell.get("cell_type", "code"),
            previous_content=previous,
            diff=diff or "no change",
        )


class DeleteCellTool(BaseTool):
    @property
    def name(self) -> str:
        return "delete_cell"

    @property
    def description(self) -> str:
        return "Delete a cell. Returns its source so it can be put back."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"notebook_path": NOTEBOOK_PATH, "cell_index": CELL_INDEX},
            "required": ["notebook_path", "cell_index"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        cell_index = kwargs.get("cell_index")
        if cell_index is None:
            return error("cell_index is required")
        api_path, ydoc, err = await _open(ctx, kwargs.get("notebook_path"))
        if err:
            return err
        err = _in_range(ydoc, cell_index)
        if err:
            return err
        cell = ydoc.get_cell(cell_index)
        ydoc.ycells.pop(cell_index)
        return ok(
            notebook_path=display_path(ctx, api_path),
            cell_index=cell_index,
            cell_type=cell.get("cell_type", "code"),
            previous_content=cell_source(cell),
            cells=len(ydoc.ycells),
        )


class MoveCellTool(BaseTool):
    @property
    def name(self) -> str:
        return "move_cell"

    @property
    def description(self) -> str:
        return "Move a cell to another index."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notebook_path": NOTEBOOK_PATH,
                "from_index": {**CELL_INDEX, "description": "Where the cell is now."},
                "to_index": {**CELL_INDEX, "description": "Where it should end up."},
            },
            "required": ["notebook_path", "from_index", "to_index"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        from_index = kwargs.get("from_index")
        to_index = kwargs.get("to_index")
        if from_index is None or to_index is None:
            return error("from_index and to_index are required")
        api_path, ydoc, err = await _open(ctx, kwargs.get("notebook_path"))
        if err:
            return err
        err = _in_range(ydoc, from_index, "from_index") or _in_range(ydoc, to_index, "to_index")
        if err:
            return err
        if from_index == to_index:
            return ok(notebook_path=display_path(ctx, api_path), from_index=from_index, to_index=to_index)
        cell = ydoc.get_cell(from_index)
        with ydoc.ycells.doc.transaction():
            ydoc.ycells.pop(from_index)
            ydoc.ycells.insert(to_index, ydoc.create_ycell(cell))
        return ok(notebook_path=display_path(ctx, api_path), from_index=from_index, to_index=to_index)


def code_cell_indices(cells: List[dict]) -> List[int]:
    return [i for i, c in enumerate(cells) if c.get("cell_type") == "code" and cell_source(c).strip()]
