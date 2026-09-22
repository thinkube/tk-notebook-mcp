# Copyright Alejandro Martínez Corriá and the Thinkube contributors
# Copyright (c) 2023-2024 Datalayer, Inc.
# SPDX-License-Identifier: BSD-3-Clause

"""Notebook-level tools: open one for work, close it, list them, create one."""

from __future__ import annotations

import os
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional

from jupyter_core.utils import ensure_async
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

from .base import NOTEBOOK_PATH, BaseTool, error, ok
from .kernels import find_session, gpu_count, wait_ready
from .paths import display_path, parent_dir, path_for_new_notebook, resolve_notebook_path
from .rooms import get_room_document, save_and_close_room


async def kernel_specs(ctx: Any) -> Dict[str, Any]:
    return await ensure_async(ctx.kernel_spec_manager.get_all_specs())


async def write_notebook(ctx: Any, api_path: str, cells: Optional[List[dict]] = None) -> None:
    nb = new_notebook()
    for spec in cells or []:
        source = spec.get("source", "")
        if spec.get("cell_type") == "markdown":
            nb.cells.append(new_markdown_cell(source))
        else:
            nb.cells.append(new_code_cell(source))
    parent = parent_dir(api_path)
    if parent:
        os.makedirs(os.path.join(ctx.root_dir, parent), exist_ok=True)
    await ensure_async(
        ctx.contents_manager.save({"type": "notebook", "content": nb, "format": "json"}, api_path)
    )


async def kernel_named_in(ctx: Any, api_path: str) -> Optional[str]:
    """The kernel the notebook's own metadata names, if any."""
    try:
        model = await ensure_async(ctx.contents_manager.get(api_path, content=True, type="notebook"))
        return model["content"].get("metadata", {}).get("kernelspec", {}).get("name")
    except Exception:
        return None


class UseNotebookTool(BaseTool):
    @property
    def name(self) -> str:
        return "use_notebook"

    @property
    def description(self) -> str:
        return (
            "Open a notebook for work: start its kernel and its shared document, with no "
            "JupyterLab tab needed. Call it once before running or editing cells. Returns the "
            "kernel and the number of cells. Creates the file when create is true. A tab that "
            "opens the notebook later shows the same cells and outputs."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notebook_path": NOTEBOOK_PATH,
                "kernel_name": {
                    "type": "string",
                    "description": (
                        "Kernel to run it with, for example 'agent-dev' or 'fine-tuning'. Defaults "
                        "to the kernel the notebook names in its metadata, else the server default."
                    ),
                },
                "create": {
                    "type": "boolean",
                    "description": "Create the notebook if it does not exist (default false).",
                    "default": False,
                },
                "needs_gpu": {
                    "type": "boolean",
                    "description": "Refuse when this notebook server was started without a GPU (default false).",
                    "default": False,
                },
            },
            "required": ["notebook_path"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        notebook_path = kwargs.get("notebook_path")
        kernel_name = kwargs.get("kernel_name")
        create = bool(kwargs.get("create", False))
        needs_gpu = bool(kwargs.get("needs_gpu", False))
        if not notebook_path:
            return error("notebook_path is required")

        gpus = await gpu_count()
        if needs_gpu and gpus == 0:
            return error(
                "this notebook server was started without a GPU; stop it and start one with a GPU",
                gpus=0,
            )

        api_path = await resolve_notebook_path(ctx, notebook_path)
        created = False
        if api_path is None:
            if not create:
                return error(
                    f"notebook '{notebook_path}' not found; pass create=true to make it",
                    notebook_path=notebook_path,
                )
            api_path = path_for_new_notebook(ctx, notebook_path)
            await write_notebook(ctx, api_path)
            created = True
        shown = display_path(ctx, api_path)

        specs = await kernel_specs(ctx)
        if not kernel_name:
            named = await kernel_named_in(ctx, api_path)
            kernel_name = named if named in specs else ctx.kernel_manager.default_kernel_name
        if kernel_name not in specs:
            return error(
                f"kernel '{kernel_name}' is not installed on this server",
                available_kernels=sorted(specs),
            )

        km = ctx.kernel_manager
        sm = ctx.session_manager
        session = await find_session(ctx, api_path)
        replaced = False
        if session is None:
            session = await sm.create_session(
                path=api_path,
                name=PurePosixPath(api_path).name,
                type="notebook",
                kernel_name=kernel_name,
            )
        elif session["kernel"]["name"] != kernel_name:
            old_id = session["kernel"]["id"]
            new_id = await ensure_async(km.start_kernel(kernel_name=kernel_name, path=api_path))
            await sm.update_session(session["id"], kernel_id=new_id)
            await ensure_async(km.shutdown_kernel(old_id))
            session = await sm.get_session(session_id=session["id"])
            replaced = True

        kernel_id = session["kernel"]["id"]
        if not await wait_ready(ctx, kernel_id):
            return error(
                f"kernel '{kernel_name}' did not start in time; check the kernel's environment",
                kernel_id=kernel_id,
                kernel_name=kernel_name,
            )

        ydoc = await get_room_document(ctx.serverapp, api_path, create=True)
        return ok(
            notebook_path=shown,
            kernel_id=kernel_id,
            kernel_name=kernel_name,
            session_id=session["id"],
            cells=len(ydoc.ycells) if ydoc is not None else None,
            gpus=gpus,
            created=created,
            kernel_replaced=replaced,
            url_path=f"{ctx.serverapp.base_url}lab/tree/{api_path}",
        )


class CloseNotebookTool(BaseTool):
    @property
    def name(self) -> str:
        return "close_notebook"

    @property
    def description(self) -> str:
        return (
            "Finish with a notebook: save its shared document, shut its kernel down and free "
            "the memory the kernel held. The file keeps every output."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notebook_path": NOTEBOOK_PATH,
                "shutdown_kernel": {
                    "type": "boolean",
                    "description": "Shut the kernel down (default true). False keeps it for later calls.",
                    "default": True,
                },
            },
            "required": ["notebook_path"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        notebook_path = kwargs.get("notebook_path")
        shutdown = bool(kwargs.get("shutdown_kernel", True))
        if not notebook_path:
            return error("notebook_path is required")
        api_path = await resolve_notebook_path(ctx, notebook_path)
        if api_path is None:
            return error(f"notebook '{notebook_path}' not found", notebook_path=notebook_path)

        room_closed = await save_and_close_room(ctx.serverapp, api_path)
        kernel_shut_down = False
        session = await find_session(ctx, api_path)
        if session is not None and shutdown:
            await ctx.session_manager.delete_session(session["id"])
            kernel_shut_down = True
        return ok(
            notebook_path=display_path(ctx, api_path),
            saved=room_closed,
            kernel_shut_down=kernel_shut_down,
        )


class ListNotebooksTool(BaseTool):
    @property
    def name(self) -> str:
        return "list_notebooks"

    @property
    def description(self) -> str:
        return "List every notebook under the notebooks folder, with the kernel each open one is using."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def _walk(self, ctx: Any, path: str, found: List[str], seen: set) -> None:
        if path in seen:
            return
        seen.add(path)
        try:
            model = await ensure_async(ctx.contents_manager.get(path, content=True, type="directory"))
        except Exception:
            return
        for item in model.get("content", []):
            full = f"{path}/{item['name']}" if path else item["name"]
            if item["type"] == "directory":
                await self._walk(ctx, full, found, seen)
            elif item["type"] == "notebook" or item["name"].endswith(".ipynb"):
                found.append(full)

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        found: List[str] = []
        await self._walk(ctx, ctx.preferred_dir.strip("/"), found, set())
        sessions = {s["path"]: s for s in await ctx.session_manager.list_sessions()}
        notebooks = []
        for api_path in sorted(found):
            entry: Dict[str, Any] = {"notebook_path": display_path(ctx, api_path)}
            session = sessions.get(api_path)
            if session is not None:
                entry["kernel_name"] = session["kernel"]["name"]
                entry["kernel_id"] = session["kernel"]["id"]
            notebooks.append(entry)
        return ok(notebooks=notebooks, count=len(notebooks))


class CreateNotebookTool(BaseTool):
    @property
    def name(self) -> str:
        return "create_notebook"

    @property
    def description(self) -> str:
        return (
            "Create a notebook file, with optional initial cells. Paths without a folder go "
            "under the notebooks folder. Call use_notebook afterwards to run it."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "notebook_path": NOTEBOOK_PATH,
                "cells": {
                    "type": "array",
                    "description": "Initial cells, in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cell_type": {"type": "string", "enum": ["code", "markdown"]},
                            "source": {"type": "string"},
                        },
                        "required": ["cell_type", "source"],
                    },
                },
            },
            "required": ["notebook_path"],
        }

    async def execute(self, ctx: Any, **kwargs: Any) -> Dict[str, Any]:
        notebook_path = kwargs.get("notebook_path") or kwargs.get("path")
        cells = kwargs.get("cells") or []
        if not notebook_path:
            return error("notebook_path is required")
        existing = await resolve_notebook_path(ctx, notebook_path)
        if existing is not None:
            return error(f"'{display_path(ctx, existing)}' already exists", notebook_path=display_path(ctx, existing))
        api_path = path_for_new_notebook(ctx, notebook_path)
        await write_notebook(ctx, api_path, cells)
        return ok(notebook_path=display_path(ctx, api_path), cells=len(cells))
