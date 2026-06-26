"""Record/replay cassettes at the LangChain model boundary.

The single most important piece of the runtime harness: LLM and embedding calls are
nondeterministic and cost money, so we record real responses once and replay them
offline. Tests and evals run with `CASSETTE_MODE=replay` → deterministic, free, no network.

A cassette is keyed by a hash of (kind, model, payload), so the same logical call always
maps to the same fixture. Re-record (delete the file or run with `record`) when a prompt
or model version changes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("cassette")
T = TypeVar("T")


class CassetteMiss(RuntimeError):
    """Raised in replay mode when no fixture exists for a call."""


def _key(kind: str, model: str, payload: Any) -> str:
    blob = json.dumps({"kind": kind, "model": model, "payload": payload}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _path(key: str) -> Path:
    return Path(get_settings().cassette_dir) / f"{key}.json"


async def through_cassette(
    kind: str,
    model: str,
    payload: Any,
    producer: Callable[[], Awaitable[T]],
) -> T:
    """Run `producer` under the active cassette mode.

    - off    → call through, no recording.
    - record → call through, persist the result as a fixture.
    - replay → return the fixture; raise CassetteMiss if absent (never hit the network).
    """
    mode = get_settings().cassette_mode
    if mode == "off":
        return await producer()

    key = _key(kind, model, payload)
    fixture = _path(key)

    if mode == "replay":
        if not fixture.exists():
            raise CassetteMiss(
                f"no cassette for {kind}/{model} (key {key}). Re-record with CASSETTE_MODE=record."
            )
        return json.loads(fixture.read_text())["result"]

    # record
    result = await producer()
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps({"kind": kind, "model": model, "result": result}, indent=2))
    log.info("cassette_recorded", kind=kind, model=model, key=key)
    return result
