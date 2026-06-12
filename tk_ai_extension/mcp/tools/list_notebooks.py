# Copyright 2025 Alejandro Martínez Corriá and the Thinkube contributors
# Copyright (c) 2023-2024 Datalayer, Inc.
# SPDX-License-Identifier: BSD-3-Clause

"""List notebooks tool (simplified for local-only use)."""

from typing import Any, Optional, List
from .base import BaseTool


class ListNotebooksTool(BaseTool):
    """Tool to list all notebooks in the Jupyter server."""

    @property
    def name(self) -> str:
        return "list_notebooks"

    @property
    def description(self) -> str:
        return "List all .ipynb files in the current directory and subdirectories"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }

    async def _list_notebooks_recursive(
        self,
        contents_manager: Any,
        path: str = "",
        notebooks: Optional[List[str]] = None,
        visited: Optional[set] = None,
    ) -> List[str]:
        """Recursively list all notebooks under ``path``.

        Callers pass the contents manager's ``preferred_dir`` (the user-facing
        notebooks dir) as the starting ``path``, so sibling trees under the
        contents root (e.g. venvs) are outside the walk and never traversed.
        """
        if notebooks is None:
            notebooks = []
        if visited is None:
            visited = set()

        # Guard against symlink cycles
        if path in visited:
            return notebooks
        visited.add(path)

        try:
            model = await contents_manager.get(path, content=True, type='directory')
            for item in model.get('content', []):
                full_path = f"{path}/{item['name']}" if path else item['name']
                if item['type'] == "directory":
                    await self._list_notebooks_recursive(
                        contents_manager, full_path, notebooks, visited
                    )
                elif item['type'] == "notebook" or item['name'].endswith('.ipynb'):
                    notebooks.append(full_path)
        except Exception:
            pass

        return notebooks

    async def execute(
        self,
        contents_manager: Any,
        kernel_manager: Any,
        kernel_spec_manager: Optional[Any] = None,
        **kwargs
    ) -> str:
        """Execute the list_notebooks tool.

        Returns:
            Formatted list of notebook paths
        """
        # Anchor the walk at the contents manager's preferred_dir (the user-facing
        # notebooks dir), not the server root. preferred_dir is an API path relative
        # to root_dir; when unset it is "" and we fall back to walking from the root.
        # This keeps the walk out of sibling trees (e.g. venvs) that live under the
        # root but outside the notebooks dir.
        start_dir = getattr(contents_manager, "preferred_dir", "") or ""
        all_notebooks = await self._list_notebooks_recursive(contents_manager, path=start_dir)

        if not all_notebooks:
            return "No notebooks found in the current directory."

        return "Notebooks:\n" + "\n".join(f"  - {nb}" for nb in sorted(all_notebooks))
