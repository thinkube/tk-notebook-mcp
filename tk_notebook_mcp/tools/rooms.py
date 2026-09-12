# Copyright 2025 Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""The collaborative document (the "room") of a notebook.

jupyter_server_ydoc keeps one shared document per open notebook. Edits made
to it reach every JupyterLab tab that has the notebook open and are saved to
disk by the room's own autosave. A room normally exists only while a tab is
open; here the server creates it on demand, so the tools work with no tab at
all, and a tab that opens later joins the same document.
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional

from jupyter_core.utils import ensure_async


def ydoc_extension(serverapp: Any) -> Optional[Any]:
    apps = serverapp.extension_manager.extension_apps.get("jupyter_server_ydoc", set())
    return next(iter(apps), None)


def room_id_for(serverapp: Any, api_path: str) -> str:
    from jupyter_server_ydoc.utils import encode_file_path, room_id_from_encoded_path

    file_id = serverapp.web_app.settings["file_id_manager"].index(api_path)
    return room_id_from_encoded_path(encode_file_path("json", "notebook", file_id))


async def get_room_document(serverapp: Any, api_path: str, create: bool) -> Optional[Any]:
    """The notebook's shared document. With ``create`` the room is made if it is not there."""
    extension = ydoc_extension(serverapp)
    if extension is None:
        raise RuntimeError("the jupyter_server_ydoc extension is not loaded")
    return await extension.get_document(
        path=api_path, content_type="notebook", file_format="json", copy=False, create=create
    )


async def save_and_close_room(serverapp: Any, api_path: str) -> bool:
    """Write the room's content to disk and drop the room. True when a room existed."""
    from jupyter_server_ydoc.websocketserver import RoomNotFound

    extension = ydoc_extension(serverapp)
    if extension is None:
        return False
    room_id = room_id_for(serverapp, api_path)
    try:
        room = await extension.ywebsocket_server.get_room(room_id)
    except RoomNotFound:
        return False
    if getattr(room, "clients", None):
        # A tab still has the notebook open; the room stays for it.
        return True
    save = room._save_to_disc()
    if save is not None:
        try:
            await asyncio.wait_for(asyncio.shield(save), 30)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
    await extension.ywebsocket_server.delete_room(room=room)
    return True


def cell_source(cell: Any) -> str:
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(source)
    return str(source)


def cells_of_document(ydoc: Any) -> List[dict]:
    return [ydoc.get_cell(i) for i in range(len(ydoc.ycells))]


async def read_cells(ctx: Any, api_path: str) -> List[dict]:
    """The notebook's cells: from the room when one exists, otherwise from the file."""
    ydoc = await get_room_document(ctx.serverapp, api_path, create=False)
    if ydoc is not None:
        return cells_of_document(ydoc)
    model = await ensure_async(ctx.contents_manager.get(api_path, content=True, type="notebook"))
    return list(model.get("content", {}).get("cells", []))


def set_cell_outputs(ydoc: Any, cell_index: int, execution_count: Optional[int], outputs: List[dict]) -> None:
    """Replace a cell's outputs and count in one transaction, so tabs see one change."""
    cell = ydoc.ycells[cell_index]
    with cell.doc.transaction():
        cell["execution_count"] = execution_count
        del cell["outputs"][:]
        for output in outputs:
            cell["outputs"].append(output)
