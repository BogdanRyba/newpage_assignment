"""Seed demo fallback: no Gemini key must not block the bundled sample ingest."""

from __future__ import annotations

import os

import pytest

from app.core.config import get_settings
from app.db.seed import ensure_demo_credentials


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_ensure_demo_credentials_falls_back_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("CASSETTE_MODE", "off")

    ensure_demo_credentials()

    assert os.environ["EMBEDDING_PROVIDER"] == "local"
    assert os.environ["CASSETTE_MODE"] == "replay"
    assert get_settings().embedding_provider == "local"


def test_ensure_demo_credentials_preserves_explicit_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("CASSETTE_MODE", "record")

    ensure_demo_credentials()

    assert os.environ["EMBEDDING_PROVIDER"] == "local"
    assert os.environ["CASSETTE_MODE"] == "record"


def test_ensure_demo_credentials_leaves_gemini_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("CASSETTE_MODE", "off")

    ensure_demo_credentials()

    assert os.environ["EMBEDDING_PROVIDER"] == "gemini"
    assert os.environ["CASSETTE_MODE"] == "off"
