# Copyright Alejandro Martínez Corriá and the Thinkube contributors
# Copyright (c) 2023-2024 Datalayer, Inc.
# SPDX-License-Identifier: BSD-3-Clause

"""Kernels: finding the one a notebook uses, holding it for a run, and running code on it.

One executor serves every tool that runs code. A kernel is held by one call
at a time: a second call waits a few seconds and then reports who holds it.
A run that passes its timeout interrupts the kernel so it is not left busy.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from contextlib import asynccontextmanager
from inspect import isawaitable
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from jupyter_core.utils import ensure_async

from .base import error
from .paths import display_path, resolve_notebook_path

_locks: Dict[str, asyncio.Lock] = {}
_holders: Dict[str, str] = {}
_generation: Dict[str, int] = {}

HOLD_WAIT_SECONDS = 5.0
READY_SECONDS = 90.0


class KernelBusy(Exception):
    """Raised when a kernel is held by another call for longer than the wait."""


@asynccontextmanager
async def hold_kernel(kernel_id: str, purpose: str, wait_seconds: float = HOLD_WAIT_SECONDS):
    lock = _locks.setdefault(kernel_id, asyncio.Lock())
    try:
        await asyncio.wait_for(lock.acquire(), wait_seconds)
    except asyncio.TimeoutError:
        raise KernelBusy(_holders.get(kernel_id, "another call")) from None
    _holders[kernel_id] = purpose
    try:
        yield
    finally:
        _holders.pop(kernel_id, None)
        lock.release()


def busy_error(kernel_id: str, busy: KernelBusy) -> Dict[str, Any]:
    return error(
        f"the kernel is busy with {busy}; wait for it, or interrupt the kernel",
        kernel_id=kernel_id,
        busy_with=str(busy),
    )


def note_restart(kernel_id: str) -> None:
    """Runs in flight on this kernel stop waiting for replies that will never come."""
    _generation[kernel_id] = _generation.get(kernel_id, 0) + 1


async def find_session(ctx: Any, api_path: str) -> Optional[dict]:
    for session in await ctx.session_manager.list_sessions():
        if session.get("path") == api_path:
            return session
    return None


def kernel_model(ctx: Any, kernel_id: str) -> Optional[dict]:
    for kernel in ctx.kernel_manager.list_kernels():
        if kernel["id"] == kernel_id:
            return kernel
    return None


async def resolve_kernel(
    ctx: Any, notebook_path: Optional[str] = None, kernel_id: Optional[str] = None
) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    """The kernel a call means: ``(kernel_id, api_path, error)``.

    A ``kernel_id`` wins when given. Otherwise the notebook's session names
    the kernel; a notebook without a session has no kernel yet.
    """
    if kernel_id:
        if kernel_model(ctx, kernel_id) is None:
            return None, None, error(f"kernel '{kernel_id}' not found", kernel_id=kernel_id)
        return kernel_id, None, None
    if not notebook_path:
        return None, None, error("notebook_path or kernel_id is required")
    api_path = await resolve_notebook_path(ctx, notebook_path)
    if api_path is None:
        return None, None, error(f"notebook '{notebook_path}' not found", notebook_path=notebook_path)
    session = await find_session(ctx, api_path)
    if session is None:
        shown = display_path(ctx, api_path)
        return None, api_path, error(
            f"'{shown}' has no kernel; call use_notebook first", notebook_path=shown
        )
    return session["kernel"]["id"], api_path, None


async def wait_ready(ctx: Any, kernel_id: str, seconds: float = READY_SECONDS) -> bool:
    """True once the kernel process reports ready, False when it did not within ``seconds``."""
    km = ctx.kernel_manager.get_kernel(kernel_id)
    ready = getattr(km, "ready", None)
    if ready is None:
        return True
    try:
        await asyncio.wait_for(asyncio.shield(ready), seconds)
        return True
    except asyncio.TimeoutError:
        return False


_gpu_count: Optional[int] = None


async def gpu_count() -> int:
    """How many GPUs this server can see. Fixed for the life of the pod."""
    global _gpu_count
    if _gpu_count is not None:
        return _gpu_count

    def probe() -> int:
        if shutil.which("nvidia-smi"):
            try:
                out = subprocess.run(
                    ["nvidia-smi", "-L"], capture_output=True, text=True, timeout=10
                )
                if out.returncode == 0:
                    return sum(1 for line in out.stdout.splitlines() if line.startswith("GPU "))
            except Exception:
                pass
        return 0

    _gpu_count = await asyncio.to_thread(probe)
    return _gpu_count


@asynccontextmanager
async def kernel_client(ctx: Any, kernel_id: str, ready_seconds: float = READY_SECONDS):
    """A client connected to the kernel, confirmed to answer, closed on exit."""
    km = ctx.kernel_manager
    lkm = km.pinned_superclass.get_kernel(km, kernel_id)
    client = lkm.client()
    client.start_channels()
    try:
        await client.wait_for_ready(timeout=ready_seconds)
        yield client
    finally:
        client.stop_channels()


ProgressCallback = Callable[[Optional[int], List[Dict[str, Any]]], Awaitable[None]]

PROGRESS_INTERVAL = 0.25


def append_output(outputs: List[Dict[str, Any]], output: Dict[str, Any]) -> None:
    """Add an output the way a notebook stores it: consecutive stream text of one name is one output."""
    if (
        output.get("output_type") == "stream"
        and outputs
        and outputs[-1].get("output_type") == "stream"
        and outputs[-1].get("name") == output.get("name")
    ):
        outputs[-1] = {**outputs[-1], "text": outputs[-1].get("text", "") + output.get("text", "")}
        return
    outputs.append(output)


async def run_code(
    ctx: Any,
    kernel_id: str,
    client: Any,
    code: str,
    timeout_seconds: float,
    on_progress: Optional[ProgressCallback] = None,
) -> Tuple[Optional[int], List[Dict[str, Any]], Optional[str]]:
    """Run ``code`` and collect its outputs.

    Returns ``(execution_count, outputs, failure)``. ``failure`` is None when
    the kernel replied in time, otherwise a sentence saying what happened:
    the run passed its timeout and the kernel was interrupted, or the kernel
    was restarted underneath it.

    ``on_progress`` is called with the outputs so far whenever they changed,
    at most a few times a second, so a tab watching the notebook sees a
    progress bar advance and prints appear as they happen.
    """
    import zmq
    import zmq.asyncio

    generation = _generation.get(kernel_id, 0)
    msg_id = client.execute(
        code, silent=False, store_history=True, allow_stdin=False, stop_on_error=False
    )

    poller = zmq.asyncio.Poller()
    iopub = client.iopub_channel.socket
    shell = client.shell_channel.socket
    poller.register(iopub, zmq.POLLIN)
    poller.register(shell, zmq.POLLIN)

    outputs: List[Dict[str, Any]] = []
    execution_count: Optional[int] = None
    failure: Optional[str] = None
    replied = False
    replied_at: Optional[float] = None
    interrupted = False
    grace = 0.1
    loop = asyncio.get_event_loop()
    started = loop.time()
    changed = False
    last_progress = started

    async def take(channel: Any) -> Optional[dict]:
        msg = channel.get_msg(timeout=0)
        if isawaitable(msg):
            msg = await msg
        return msg

    while True:
        now = loop.time()
        if changed and on_progress is not None and now - last_progress >= PROGRESS_INTERVAL:
            changed = False
            last_progress = now
            try:
                await on_progress(execution_count, list(outputs))
            except Exception as e:
                ctx.log.warning("tk-notebook-mcp: progress write failed: %s", e)
        if replied and replied_at is not None and now - replied_at >= grace:
            break
        if _generation.get(kernel_id, 0) != generation:
            failure = "the kernel was restarted while this was running"
            break
        if not replied and not interrupted and timeout_seconds > 0 and now - started > timeout_seconds:
            interrupted = True
            failure = f"the cell did not finish in {int(timeout_seconds)} seconds; the kernel was interrupted"
            try:
                await ensure_async(ctx.kernel_manager.interrupt_kernel(kernel_id))
            except Exception as e:
                ctx.log.warning("tk-notebook-mcp: interrupt after timeout failed: %s", e)
            started = now  # the reply to the interrupt gets its own window
        if interrupted and not replied and now - started > 15:
            break

        wait_ms = (grace / 2 if replied else 1.0) * 1000
        events = dict(await poller.poll(wait_ms))
        if not events:
            continue

        if iopub in events:
            msg = await take(client.iopub_channel)
            if msg and msg.get("parent_header", {}).get("msg_id") == msg_id:
                kind = msg.get("msg_type")
                content = msg.get("content", {})
                if kind == "stream":
                    append_output(
                        outputs,
                        {"output_type": "stream", "name": content.get("name", "stdout"), "text": content.get("text", "")},
                    )
                    changed = True
                elif kind == "execute_result":
                    execution_count = content.get("execution_count", execution_count)
                    changed = True
                    outputs.append(
                        {
                            "output_type": "execute_result",
                            "data": content.get("data", {}),
                            "metadata": content.get("metadata", {}),
                            "execution_count": content.get("execution_count"),
                        }
                    )
                elif kind == "display_data":
                    changed = True
                    outputs.append(
                        {"output_type": "display_data", "data": content.get("data", {}), "metadata": content.get("metadata", {})}
                    )
                elif kind == "error":
                    changed = True
                    outputs.append(
                        {
                            "output_type": "error",
                            "ename": content.get("ename", ""),
                            "evalue": content.get("evalue", ""),
                            "traceback": content.get("traceback", []),
                        }
                    )
                elif kind == "clear_output":
                    outputs.clear()
                    changed = True

        if shell in events:
            reply = await take(client.shell_channel)
            if reply and reply.get("parent_header", {}).get("msg_id") == msg_id:
                replied = True
                replied_at = loop.time()
                if execution_count is None:
                    execution_count = reply.get("content", {}).get("execution_count")

    return execution_count, outputs, failure


def error_summary(outputs: List[Dict[str, Any]]) -> Optional[str]:
    for output in outputs:
        if output.get("output_type") == "error":
            name = output.get("ename") or "Error"
            value = output.get("evalue") or ""
            return f"{name}: {value}".strip(": ")
    return None
