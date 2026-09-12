# Copyright 2025 Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""The tools the extension serves, in the order they are listed."""

from typing import List

from .base import BaseTool
from .cells import DeleteCellTool, InsertCellTool, ListCellsTool, MoveCellTool, OverwriteCellTool, ReadCellTool
from .execution import (
    CheckAllCellsStatusTool,
    CheckExecutionStatusTool,
    ExecuteAllCellsTool,
    ExecuteCellAsyncTool,
    ExecuteCellTool,
    ExecuteIPythonTool,
    InsertAndExecuteCellTool,
)
from .kernel_tools import CheckModuleTool, GetKernelStatusTool, InterruptKernelTool, ListKernelsTool, RestartKernelTool
from .notebooks import CloseNotebookTool, CreateNotebookTool, ListNotebooksTool, UseNotebookTool


def all_tools() -> List[BaseTool]:
    return [
        UseNotebookTool(),
        CloseNotebookTool(),
        ListNotebooksTool(),
        CreateNotebookTool(),
        ListCellsTool(),
        ReadCellTool(),
        InsertCellTool(),
        OverwriteCellTool(),
        DeleteCellTool(),
        MoveCellTool(),
        ExecuteCellTool(),
        ExecuteCellAsyncTool(),
        CheckExecutionStatusTool(),
        ExecuteAllCellsTool(),
        CheckAllCellsStatusTool(),
        InsertAndExecuteCellTool(),
        ExecuteIPythonTool(),
        RestartKernelTool(),
        InterruptKernelTool(),
        GetKernelStatusTool(),
        ListKernelsTool(),
        CheckModuleTool(),
    ]


__all__ = ["all_tools", "BaseTool"]
