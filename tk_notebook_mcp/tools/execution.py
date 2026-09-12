# Copyright 2025 Alejandro Martínez Corriá and the Thinkube contributors
# Copyright (c) 2023-2024 Datalayer, Inc.
# SPDX-License-Identifier: BSD-3-Clause

"""Running cells and code.

Every run goes through one path: take the kernel, open one client, run,
write the outputs into the shared document, release the kernel. The blocking
tools wait for the result; the background ones return an execution id and
record progress in the execution store.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from jupyter_core.utils import ensure_async

from .base import CELL_INDEX, NOTEBOOK_PATH, BaseTool, error, ok
from .cells import POSITION, code_cell_indices, insert_cell, insert_index
from .executions import store
from .kernels import (
    KernelBusy,
    busy_error,
    error_summary,
    kernel_client,
    hold_kernel,
    note_restart,
    resolve_kernel,
    wait_ready,
    run_code,
)
from .outputs import process_outputs
from .paths import display_path
from .rooms import cell_source, cells_of_document, get_room_document, set_cell_outputs

DEFAULT_TIMEOUT = 600
DEFAULT_BACKGROUND_TIMEOUT = 3600

TIMEOUT = {
    "type": "integer",
    "description": f"Seconds to wait for the cell; 0 means no limit (default {DEFAULT_TIMEOUT}). Past it the kernel is interrupted.",
    "default": DEFAULT_TIMEOUT,
}

BACKGROUND_TIMEOUT = {
    "type": "integer",
    "description": f"Seconds allowed per cell; 0 means no limit (default {DEFAULT_BACKGROUND_TIMEOUT}).",
    "default": DEFAULT_BACKGROUND_TIMEOUT,
}


def _timeout(value: Any, default: int) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return float(default)
    return max(0.0, seconds)


async def run_cell(ctx: Any, api_path: str, cell_index: int, kernel_id: str, client: Any, timeout: float) -> Dict[str, Any]:
    """Run one cell of the notebook and store its outputs. The result says how it went."""
    ydoc = await get_room_document(ctx.serverapp, api_path, create=True)
    if cell_index < 0 or cell_index >= len(ydoc.ycells):
        return error(f"cell_index {cell_index} is out of range; the notebook has {len(ydoc.ycells)} cells", cell_index=cell_index)
    cell = ydoc.get_cell(cell_index)
    if cell.get("cell_type") != "code":
        return error(f"cell {cell_index} is a {cell.get('cell_type')} cell, not code", cell_index=cell_index)
    source = cell_source(cell)
    if not source.strip():
        return ok(cell_index=cell_index, skipped=True, outputs=[], execution_count=None)

    execution_count, outputs, failure = await run_code(ctx, kernel_id, client, source, timeout)

    # The room may have been replaced during a long run; write into the one that is live now.
    ydoc = await get_room_document(ctx.serverapp, api_path, create=True)
    if cell_index < len(ydoc.ycells):
        set_cell_outputs(ydoc, cell_index, execution_count, outputs)

    result: Dict[str, Any] = {
        "cell_index": cell_index,
        "execution_count": execution_count,
        "outputs": process_outputs(ctx, outputs),
    }
    raised = error_summary(outputs)
    if failure:
        return error(failure, timed_out=failure.startswith("the cell did not finish"), **result)
    if raised:
        return error(f"cell {cell_index} raised {raised}", **result)
    return ok(**result)


class ExecuteCellTool(BaseTool):
    @property
    def name(self) -> str:
        return "execute_cell"

    @property
    def description(self) -> str:
        return (
            "Run one code cell and return its outputs once it finishes. The outputs are "
            "stored in the notebook. Needs use_notebook first. For a cell that runs for "
            "many minutes use execute_cell_async."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"notebook_path": NOTEBOOK_PATH, "cell_index": CELL_INDEX, "timeout_seconds": TIMEOUT},
            "required": ["notebook_path", "cell_index"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        cell_index = kwargs.get("cell_index")
        if cell_index is None:
            return error("cell_index is required")
        kernel_id, api_path, err = await resolve_kernel(ctx, kwargs.get("notebook_path"), kwargs.get("kernel_id"))
        if err:
            return err
        timeout = _timeout(kwargs.get("timeout_seconds"), DEFAULT_TIMEOUT)
        try:
            async with hold_kernel(kernel_id, f"execute_cell {cell_index} of {display_path(ctx, api_path)}"):
                async with kernel_client(ctx, kernel_id) as client:
                    result = await run_cell(ctx, api_path, cell_index, kernel_id, client, timeout)
        except KernelBusy as busy:
            return busy_error(kernel_id, busy)
        result["notebook_path"] = display_path(ctx, api_path)
        result["kernel_id"] = kernel_id
        return result


class ExecuteCellAsyncTool(BaseTool):
    @property
    def name(self) -> str:
        return "execute_cell_async"

    @property
    def description(self) -> str:
        return (
            "Start one code cell in the background and return an execution_id at once. "
            "Poll check_execution_status for the outputs. Use it for training steps, "
            "long queries and anything that outlives a normal call."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"notebook_path": NOTEBOOK_PATH, "cell_index": CELL_INDEX, "timeout_seconds": BACKGROUND_TIMEOUT},
            "required": ["notebook_path", "cell_index"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        cell_index = kwargs.get("cell_index")
        if cell_index is None:
            return error("cell_index is required")
        kernel_id, api_path, err = await resolve_kernel(ctx, kwargs.get("notebook_path"), kwargs.get("kernel_id"))
        if err:
            return err
        timeout = _timeout(kwargs.get("timeout_seconds"), DEFAULT_BACKGROUND_TIMEOUT)
        shown = display_path(ctx, api_path)
        execution_id = store.create(ctx, "cell", notebook_path=shown, kernel_id=kernel_id, cell_index=cell_index)

        async def run() -> None:
            try:
                async with hold_kernel(kernel_id, f"execute_cell_async {cell_index} of {shown}"):
                    async with kernel_client(ctx, kernel_id) as client:
                        result = await run_cell(ctx, api_path, cell_index, kernel_id, client, timeout)
                store.update(
                    ctx,
                    execution_id,
                    status="completed" if result["success"] else "error",
                    outputs=result.get("outputs", []),
                    execution_count=result.get("execution_count"),
                    error=result.get("error"),
                )
            except KernelBusy as busy:
                store.update(ctx, execution_id, status="error", error=busy_error(kernel_id, busy)["error"])
            except Exception as e:
                ctx.log.error("tk-notebook-mcp: background cell run failed: %s", e, exc_info=True)
                store.update(ctx, execution_id, status="error", error=f"{type(e).__name__}: {e}")

        asyncio.create_task(run())
        return ok(execution_id=execution_id, status="running", notebook_path=shown, cell_index=cell_index, kernel_id=kernel_id)


class CheckExecutionStatusTool(BaseTool):
    @property
    def name(self) -> str:
        return "check_execution_status"

    @property
    def description(self) -> str:
        return "The state of a background cell run: running, completed or error, with the outputs once it ends."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"execution_id": {"type": "string", "description": "The id execute_cell_async returned."}},
            "required": ["execution_id"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        execution_id = kwargs.get("execution_id")
        if not execution_id:
            return error("execution_id is required")
        record = store.get(ctx, execution_id)
        if record is None:
            return error(f"execution '{execution_id}' not found", execution_id=execution_id)
        return {"success": record["status"] not in ("error", "lost"), **record}


class ExecuteAllCellsTool(BaseTool):
    @property
    def name(self) -> str:
        return "execute_all_cells"

    @property
    def description(self) -> str:
        return (
            "Run every code cell in order, in the background, and return an execution_id at "
            "once. Poll check_all_cells_status for progress. Stops at the first cell that "
            "raises unless stop_on_error is false. Can restart the kernel first."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notebook_path": NOTEBOOK_PATH,
                "restart_kernel": {"type": "boolean", "description": "Restart the kernel before the run (default false).", "default": False},
                "stop_on_error": {"type": "boolean", "description": "Stop at the first cell that raises (default true).", "default": True},
                "cell_timeout_seconds": BACKGROUND_TIMEOUT,
            },
            "required": ["notebook_path"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        kernel_id, api_path, err = await resolve_kernel(ctx, kwargs.get("notebook_path"), kwargs.get("kernel_id"))
        if err:
            return err
        restart = bool(kwargs.get("restart_kernel", False))
        stop_on_error = bool(kwargs.get("stop_on_error", True))
        timeout = _timeout(kwargs.get("cell_timeout_seconds"), DEFAULT_BACKGROUND_TIMEOUT)
        shown = display_path(ctx, api_path)

        ydoc = await get_room_document(ctx.serverapp, api_path, create=True)
        indices = code_cell_indices(cells_of_document(ydoc))
        if not indices:
            return error(f"'{shown}' has no code cells to run", notebook_path=shown)

        try:
            hold = hold_kernel(kernel_id, f"execute_all_cells of {shown}")
            await hold.__aenter__()
        except KernelBusy as busy:
            return busy_error(kernel_id, busy)

        execution_id = store.create(
            ctx,
            "all_cells",
            notebook_path=shown,
            kernel_id=kernel_id,
            total_cells=len(indices),
            completed_cells=0,
            current_cell_index=None,
            failed_cell_index=None,
            results=[],
        )

        async def run() -> None:
            results: List[Dict[str, Any]] = []
            try:
                if restart:
                    note_restart(kernel_id)
                    await ensure_async(ctx.kernel_manager.restart_kernel(kernel_id))
                    await wait_ready(ctx, kernel_id)
                async with kernel_client(ctx, kernel_id) as client:
                    for cell_index in indices:
                        store.update(ctx, execution_id, current_cell_index=cell_index)
                        result = await run_cell(ctx, api_path, cell_index, kernel_id, client, timeout)
                        results.append(result)
                        store.update(ctx, execution_id, completed_cells=len(results), results=results)
                        if not result["success"]:
                            if result.get("timed_out") or "restarted" in (result.get("error") or ""):
                                store.update(ctx, execution_id, status="error", failed_cell_index=cell_index, error=result["error"], current_cell_index=None)
                                return
                            if stop_on_error:
                                store.update(ctx, execution_id, status="error", failed_cell_index=cell_index, error=result["error"], current_cell_index=None)
                                return
                failed = [r["cell_index"] for r in results if not r["success"]]
                store.update(
                    ctx,
                    execution_id,
                    status="error" if failed else "completed",
                    failed_cell_index=failed[0] if failed else None,
                    error=f"{len(failed)} cells raised: {failed}" if failed else None,
                    current_cell_index=None,
                )
            except Exception as e:
                ctx.log.error("tk-notebook-mcp: run of all cells failed: %s", e, exc_info=True)
                store.update(ctx, execution_id, status="error", error=f"{type(e).__name__}: {e}", current_cell_index=None)
            finally:
                await hold.__aexit__(None, None, None)

        asyncio.create_task(run())
        return ok(
            execution_id=execution_id,
            status="running",
            notebook_path=shown,
            kernel_id=kernel_id,
            total_cells=len(indices),
            restart_kernel=restart,
        )


class CheckAllCellsStatusTool(BaseTool):
    @property
    def name(self) -> str:
        return "check_all_cells_status"

    @property
    def description(self) -> str:
        return "Progress of a run started by execute_all_cells: cells done, the one running, and each cell's result."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"execution_id": {"type": "string", "description": "The id execute_all_cells returned."}},
            "required": ["execution_id"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        execution_id = kwargs.get("execution_id")
        if not execution_id:
            return error("execution_id is required")
        record = store.get(ctx, execution_id)
        if record is None:
            return error(f"execution '{execution_id}' not found", execution_id=execution_id)
        total = record.get("total_cells") or 0
        done = record.get("completed_cells") or 0
        return {
            "success": record["status"] not in ("error", "lost"),
            "progress_percent": int(done * 100 / total) if total else 0,
            **record,
        }


class InsertAndExecuteCellTool(BaseTool):
    @property
    def name(self) -> str:
        return "insert_and_execute_cell"

    @property
    def description(self) -> str:
        return "Insert a code cell and run it in one step. Returns its index and outputs."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notebook_path": NOTEBOOK_PATH,
                "content": {"type": "string", "description": "The code to insert and run."},
                "position": POSITION,
                "cell_index": {**CELL_INDEX, "description": "The cell that 'above' or 'below' refers to."},
                "timeout_seconds": TIMEOUT,
            },
            "required": ["notebook_path", "content"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        content = kwargs.get("content")
        if content is None:
            content = kwargs.get("source") or kwargs.get("code")
        if content is None:
            return error("content is required")
        kernel_id, api_path, err = await resolve_kernel(ctx, kwargs.get("notebook_path"), kwargs.get("kernel_id"))
        if err:
            return err
        timeout = _timeout(kwargs.get("timeout_seconds"), DEFAULT_TIMEOUT)
        ydoc = await get_room_document(ctx.serverapp, api_path, create=True)
        index = insert_index(ydoc, kwargs.get("position") or "end", kwargs.get("cell_index"))
        if index is None:
            return error("position 'above' or 'below' needs cell_index")
        insert_cell(ydoc, index, "code", content)
        try:
            async with hold_kernel(kernel_id, f"insert_and_execute_cell {index} of {display_path(ctx, api_path)}"):
                async with kernel_client(ctx, kernel_id) as client:
                    result = await run_cell(ctx, api_path, index, kernel_id, client, timeout)
        except KernelBusy as busy:
            return busy_error(kernel_id, busy)
        result["notebook_path"] = display_path(ctx, api_path)
        result["kernel_id"] = kernel_id
        result["inserted"] = True
        return result


class ExecuteIPythonTool(BaseTool):
    @property
    def name(self) -> str:
        return "execute_ipython"

    @property
    def description(self) -> str:
        return (
            "Run code in a notebook's kernel without changing the notebook: inspect a "
            "variable, check a package, try a line. Returns the outputs."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notebook_path": NOTEBOOK_PATH,
                "kernel_id": {"type": "string", "description": "A kernel id, instead of notebook_path."},
                "code": {"type": "string", "description": "Python or IPython code."},
                "timeout_seconds": {**TIMEOUT, "default": 300},
            },
            "required": ["code"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        code = kwargs.get("code")
        if not code:
            return error("code is required")
        kernel_id, api_path, err = await resolve_kernel(ctx, kwargs.get("notebook_path"), kwargs.get("kernel_id"))
        if err:
            return err
        timeout = _timeout(kwargs.get("timeout_seconds"), 300)
        try:
            async with hold_kernel(kernel_id, "execute_ipython"):
                async with kernel_client(ctx, kernel_id) as client:
                    execution_count, outputs, failure = await run_code(ctx, kernel_id, client, code, timeout)
        except KernelBusy as busy:
            return busy_error(kernel_id, busy)
        result = {"kernel_id": kernel_id, "execution_count": execution_count, "outputs": process_outputs(ctx, outputs)}
        if failure:
            return error(failure, **result)
        raised = error_summary(outputs)
        if raised:
            return error(f"the code raised {raised}", **result)
        return ok(**result)


def outputs_text(outputs: List[Dict[str, Any]]) -> str:
    """The stream text of a run, for tools that parse what they printed."""
    parts = []
    for output in outputs:
        if output.get("output_type") == "stream" and output.get("name", "stdout") == "stdout":
            text = output.get("text", "")
            parts.append("".join(text) if isinstance(text, list) else str(text))
    return "".join(parts)
