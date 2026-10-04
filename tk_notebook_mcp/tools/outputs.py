# Copyright Alejandro Martínez Corriá and the Thinkube contributors
# SPDX-License-Identifier: BSD-3-Clause

"""Large cell outputs are written beside the notebooks and replaced by a path in the reply.

Images are always written out; text longer than ``TEXT_LIMIT`` is cut and the
full text written out. The outputs stored in the notebook are untouched; only
what goes back to the caller changes.
"""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

TEXT_LIMIT = 10000
OUTPUTS_FOLDER = ".outputs"


def outputs_dir(ctx: Any) -> Path:
    base = Path(ctx.root_dir)
    if ctx.preferred_dir:
        base = base / ctx.preferred_dir
    return base / OUTPUTS_FOLDER


def _write(ctx: Any, content: bytes, ext: str) -> str | None:
    date_dir = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    name = f"{uuid.uuid4().hex[:12]}.{ext}"
    try:
        folder = outputs_dir(ctx) / date_dir
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)
        return f"{OUTPUTS_FOLDER}/{date_dir}/{name}"
    except Exception as e:
        logger.error("could not write output file: %s", e)
        return None


def process_outputs(ctx: Any, outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    processed = []
    for output in outputs:
        output_type = output.get("output_type", "")
        if output_type in ("display_data", "execute_result"):
            data = output.get("data", {})
            if "image/png" in data:
                try:
                    rel = _write(ctx, base64.b64decode(data["image/png"]), "png")
                except Exception as e:
                    logger.warning("could not decode an image output: %s", e)
                    rel = None
                if rel:
                    new_data = {k: v for k, v in data.items() if k != "image/png"}
                    new_data["image/png"] = f"[image saved: {rel}]"
                    output = {**output, "data": new_data}
        if output_type == "stream":
            text = output.get("text", "")
            if isinstance(text, list):
                text = "".join(text)
            if len(text) > TEXT_LIMIT:
                rel = _write(ctx, text.encode("utf-8"), "txt")
                if rel:
                    output = {
                        **output,
                        "text": f"{text[:TEXT_LIMIT]}\n\n[output cut at {TEXT_LIMIT} characters; full output ({len(text)} characters): {rel}]",
                    }
        processed.append(output)
    return processed


def summarize_outputs(outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Outputs for a read: images become a note with their size, long text is cut. Nothing is written."""
    summarized = []
    for output in outputs:
        output_type = output.get("output_type", "")
        if output_type in ("display_data", "execute_result"):
            data = dict(output.get("data", {}))
            for mime in list(data):
                if mime.startswith("image/"):
                    data[mime] = f"[{mime}, {len(str(data[mime]))} characters of base64]"
                elif mime == "text/html" and len(str(data[mime])) > TEXT_LIMIT:
                    data[mime] = f"[text/html, {len(str(data[mime]))} characters]"
            output = {**output, "data": data}
        if output_type == "stream":
            text = output.get("text", "")
            if isinstance(text, list):
                text = "".join(text)
            if len(text) > TEXT_LIMIT:
                output = {**output, "text": f"{text[:TEXT_LIMIT]}\n\n[output cut at {TEXT_LIMIT} of {len(text)} characters]"}
        summarized.append(output)
    return summarized


def has_error(outputs: List[Dict[str, Any]]) -> bool:
    return any(o.get("output_type") == "error" for o in outputs)
