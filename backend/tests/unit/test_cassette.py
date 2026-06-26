"""Cassette contract — the determinism backbone. record persists, replay serves,
replay-miss raises rather than hitting the network."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import cassette
from app.core.cassette import CassetteMiss, through_cassette


def _settings(mode: str, tmp: Path) -> SimpleNamespace:
    return SimpleNamespace(cassette_mode=mode, cassette_dir=str(tmp))


async def test_off_mode_calls_through(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cassette, "get_settings", lambda: _settings("off", tmp_path))
    calls = {"n": 0}

    async def producer():
        calls["n"] += 1
        return [1.0, 2.0]

    result = await through_cassette("embed_query", "m", "hi", producer)
    assert result == [1.0, 2.0]
    assert calls["n"] == 1  # really called


async def test_record_then_replay_is_deterministic(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cassette, "get_settings", lambda: _settings("record", tmp_path))

    async def producer():
        return {"answer": 42}

    recorded = await through_cassette("complete", "gemini", {"q": "x"}, producer)
    assert recorded == {"answer": 42}
    assert list(tmp_path.glob("*.json"))  # fixture written

    # Replay must not call the producer (network) — it raises if it does.
    monkeypatch.setattr(cassette, "get_settings", lambda: _settings("replay", tmp_path))

    async def exploding():
        raise AssertionError("replay must not hit the network")

    replayed = await through_cassette("complete", "gemini", {"q": "x"}, exploding)
    assert replayed == {"answer": 42}


async def test_replay_miss_raises(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cassette, "get_settings", lambda: _settings("replay", tmp_path))

    async def producer():
        return 1

    with pytest.raises(CassetteMiss):
        await through_cassette("complete", "gemini", {"q": "absent"}, producer)
