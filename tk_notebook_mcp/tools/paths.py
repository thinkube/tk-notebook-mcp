# Copyright 2025 Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""Notebook paths as the contents API sees them.

A caller may name a notebook relative to the notebooks folder (the contents
manager's ``preferred_dir``), relative to the server root, or by absolute path
under the root. Every tool resolves the name once, here, to the root-relative
API path the contents manager, the session manager and the room use.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Optional

from jupyter_core.utils import ensure_async


def _strip(ctx: Any, notebook_path: str) -> str:
    path = notebook_path.strip()
    if path.startswith("~/"):
        path = path[2:]
    root = ctx.root_dir.rstrip("/") + "/"
    if path.startswith(root):
        path = path[len(root):]
    return path.strip("/")


def candidates(ctx: Any, notebook_path: str) -> list[str]:
    """The root-relative paths a name may mean, most specific first."""
    path = _strip(ctx, notebook_path)
    preferred = ctx.preferred_dir.strip("/")
    found = [path]
    if preferred and not path.startswith(preferred + "/"):
        found.append(f"{preferred}/{path}")
    return found


async def resolve_notebook_path(ctx: Any, notebook_path: str) -> Optional[str]:
    """The root-relative API path of an existing notebook, or None."""
    for candidate in candidates(ctx, notebook_path):
        if await ensure_async(ctx.contents_manager.file_exists(candidate)):
            return candidate
    return None


def path_for_new_notebook(ctx: Any, notebook_path: str) -> str:
    """Where a new notebook goes: under the notebooks folder unless the name already says where."""
    path = _strip(ctx, notebook_path)
    if not path.endswith(".ipynb"):
        path += ".ipynb"
    preferred = ctx.preferred_dir.strip("/")
    if preferred and not path.startswith(preferred + "/"):
        path = f"{preferred}/{path}"
    return path


def display_path(ctx: Any, api_path: str) -> str:
    """The path as the caller names it: relative to the notebooks folder when it is inside it."""
    preferred = ctx.preferred_dir.strip("/")
    if preferred and api_path.startswith(preferred + "/"):
        return api_path[len(preferred) + 1:]
    return api_path


def parent_dir(api_path: str) -> str:
    parent = str(PurePosixPath(api_path).parent)
    return "" if parent == "." else parent
