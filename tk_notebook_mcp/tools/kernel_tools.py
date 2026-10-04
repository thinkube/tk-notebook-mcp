# Copyright Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""Kernel tools: restart, interrupt, status, the list, and a package check inside the kernel."""

from __future__ import annotations

import json
from typing import Any, Dict

from jupyter_core.utils import ensure_async

from .base import NOTEBOOK_PATH, BaseTool, error, ok
from .execution import outputs_text
from .kernels import (
    KernelBusy,
    busy_error,
    hold_kernel,
    kernel_client,
    kernel_model,
    note_restart,
    resolve_kernel,
    run_code,
    wait_ready,
)
from .paths import display_path

KERNEL_ID = {"type": "string", "description": "A kernel id, instead of notebook_path."}

TARGET = {
    "type": "object",
    "properties": {"notebook_path": NOTEBOOK_PATH, "kernel_id": KERNEL_ID},
    "required": [],
}


class RestartKernelTool(BaseTool):
    @property
    def name(self) -> str:
        return "restart_kernel"

    @property
    def description(self) -> str:
        return "Restart a notebook's kernel: every variable is lost, the cells and outputs stay. A run in flight is stopped."

    @property
    def input_schema(self) -> dict:
        return TARGET

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        kernel_id, api_path, err = await resolve_kernel(ctx, kwargs.get("notebook_path"), kwargs.get("kernel_id"))
        if err:
            return err
        note_restart(kernel_id)
        await ensure_async(ctx.kernel_manager.restart_kernel(kernel_id))
        ready = await wait_ready(ctx, kernel_id)
        if not ready:
            return error("the kernel did not come back in time after the restart", kernel_id=kernel_id)
        return ok(kernel_id=kernel_id, notebook_path=display_path(ctx, api_path) if api_path else None)


class InterruptKernelTool(BaseTool):
    @property
    def name(self) -> str:
        return "interrupt_kernel"

    @property
    def description(self) -> str:
        return "Interrupt what a kernel is running, as Ctrl-C would. Variables are kept."

    @property
    def input_schema(self) -> dict:
        return TARGET

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        kernel_id, api_path, err = await resolve_kernel(ctx, kwargs.get("notebook_path"), kwargs.get("kernel_id"))
        if err:
            return err
        await ensure_async(ctx.kernel_manager.interrupt_kernel(kernel_id))
        return ok(kernel_id=kernel_id, notebook_path=display_path(ctx, api_path) if api_path else None)


class GetKernelStatusTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_kernel_status"

    @property
    def description(self) -> str:
        return "Whether a kernel is idle or busy, its name, and when it was last active."

    @property
    def input_schema(self) -> dict:
        return TARGET

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        kernel_id, api_path, err = await resolve_kernel(ctx, kwargs.get("notebook_path"), kwargs.get("kernel_id"))
        if err:
            return err
        model = kernel_model(ctx, kernel_id)
        if model is None:
            return error(f"kernel '{kernel_id}' not found", kernel_id=kernel_id)
        return ok(
            kernel_id=kernel_id,
            notebook_path=display_path(ctx, api_path) if api_path else None,
            kernel_name=model.get("name"),
            execution_state=model.get("execution_state"),
            last_activity=str(model.get("last_activity")) if model.get("last_activity") else None,
            connections=model.get("connections", 0),
        )


class ListKernelsTool(BaseTool):
    @property
    def name(self) -> str:
        return "list_kernels"

    @property
    def description(self) -> str:
        return "The kernels running now, with the notebook each serves, and the kernel types installed."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        by_kernel = {}
        for session in await ctx.session_manager.list_sessions():
            by_kernel[session["kernel"]["id"]] = session.get("path")
        running = []
        for kernel in ctx.kernel_manager.list_kernels():
            api_path = by_kernel.get(kernel["id"])
            running.append(
                {
                    "kernel_id": kernel["id"],
                    "kernel_name": kernel.get("name"),
                    "execution_state": kernel.get("execution_state"),
                    "notebook_path": display_path(ctx, api_path) if api_path else None,
                }
            )
        specs = await ensure_async(ctx.kernel_spec_manager.get_all_specs())
        installed = [
            {"name": name, "display_name": spec.get("spec", {}).get("display_name", name)}
            for name, spec in sorted(specs.items())
        ]
        return ok(running=running, installed=installed)


CHECK_CODE = """
import json as _json, importlib as _importlib, importlib.metadata as _metadata
_found = {}
for _name in _json.loads(%r):
    _version = None
    try:
        _version = _metadata.version(_name)
    except _metadata.PackageNotFoundError:
        try:
            _module = _importlib.import_module(_name)
            _version = getattr(_module, "__version__", "installed")
        except Exception:
            _version = None
    _found[_name] = _version
print("__TK_MODULES__" + _json.dumps(_found))
"""


class CheckModuleTool(BaseTool):
    @property
    def name(self) -> str:
        return "check_module"

    @property
    def description(self) -> str:
        return "Whether packages are installed in a notebook's kernel, with their versions. Checks the kernel's own environment."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notebook_path": NOTEBOOK_PATH,
                "kernel_id": KERNEL_ID,
                "module_names": {"type": "array", "items": {"type": "string"}, "description": "Package or module names."},
            },
            "required": ["module_names"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        names = kwargs.get("module_names") or ([kwargs["module_name"]] if kwargs.get("module_name") else [])
        if not names:
            return error("module_names is required")
        kernel_id, api_path, err = await resolve_kernel(ctx, kwargs.get("notebook_path"), kwargs.get("kernel_id"))
        if err:
            return err
        try:
            async with hold_kernel(kernel_id, "check_module"):
                async with kernel_client(ctx, kernel_id) as client:
                    _, outputs, failure = await run_code(ctx, kernel_id, client, CHECK_CODE % json.dumps(names), 60)
        except KernelBusy as busy:
            return busy_error(kernel_id, busy)
        if failure:
            return error(failure, kernel_id=kernel_id)
        text = outputs_text(outputs)
        marker = text.rfind("__TK_MODULES__")
        if marker < 0:
            return error("the kernel did not answer the check", kernel_id=kernel_id)
        found = json.loads(text[marker + len("__TK_MODULES__"):].strip())
        modules = [{"module": name, "available": found.get(name) is not None, "version": found.get(name)} for name in names]
        return ok(
            kernel_id=kernel_id,
            notebook_path=display_path(ctx, api_path) if api_path else None,
            modules=modules,
            missing=[m["module"] for m in modules if not m["available"]],
        )
