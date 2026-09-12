# Copyright 2025 Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""How a notebook name becomes the path the contents API uses."""

import logging
from types import SimpleNamespace

from tk_notebook_mcp.registry import ToolContext
from tk_notebook_mcp.tools.paths import (
    candidates,
    display_path,
    parent_dir,
    path_for_new_notebook,
    resolve_notebook_path,
)


class FakeContents:
    preferred_dir = "thinkube/notebooks"

    def __init__(self, existing):
        self.existing = set(existing)

    def file_exists(self, path):
        return path in self.existing


def context(existing=()):
    serverapp = SimpleNamespace(
        log=logging.getLogger("test"),
        root_dir="/home/user",
        base_url="/",
        contents_manager=FakeContents(existing),
    )
    return ToolContext(serverapp)


def test_candidates_try_the_name_then_the_notebooks_folder():
    ctx = context()
    assert candidates(ctx, "a.ipynb") == ["a.ipynb", "thinkube/notebooks/a.ipynb"]
    assert candidates(ctx, "thinkube/notebooks/a.ipynb") == ["thinkube/notebooks/a.ipynb"]
    assert candidates(ctx, "/home/user/thinkube/notebooks/a.ipynb") == ["thinkube/notebooks/a.ipynb"]
    assert candidates(ctx, "~/thinkube/notebooks/a.ipynb") == ["thinkube/notebooks/a.ipynb"]


async def test_resolve_finds_the_notebook_under_the_notebooks_folder():
    ctx = context({"thinkube/notebooks/examples/a.ipynb"})
    assert await resolve_notebook_path(ctx, "examples/a.ipynb") == "thinkube/notebooks/examples/a.ipynb"
    assert await resolve_notebook_path(ctx, "thinkube/notebooks/examples/a.ipynb") == "thinkube/notebooks/examples/a.ipynb"
    assert await resolve_notebook_path(ctx, "missing.ipynb") is None


def test_new_notebooks_go_under_the_notebooks_folder():
    ctx = context()
    assert path_for_new_notebook(ctx, "work/new") == "thinkube/notebooks/work/new.ipynb"
    assert path_for_new_notebook(ctx, "thinkube/notebooks/x.ipynb") == "thinkube/notebooks/x.ipynb"


def test_display_and_parent():
    ctx = context()
    assert display_path(ctx, "thinkube/notebooks/examples/a.ipynb") == "examples/a.ipynb"
    assert display_path(ctx, "elsewhere/a.ipynb") == "elsewhere/a.ipynb"
    assert parent_dir("thinkube/notebooks/a.ipynb") == "thinkube/notebooks"
    assert parent_dir("a.ipynb") == ""
