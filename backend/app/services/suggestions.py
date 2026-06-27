"""Generate starter questions for a repo from its indexed symbol map (LLM via LangChain).

The digest is built from the repo's own files/symbols, so suggestions are about *this* codebase,
not a hardcoded list. Cached per repo (they only change on re-ingest) and degrades gracefully to
a small generic set if the generator is unavailable or returns garbage.
"""

from __future__ import annotations

import json
import re

from app.core.logging import get_logger
from app.ports.generator import Generator
from app.prompts import suggestions as prompt

log = get_logger("suggestions")
_JSON_ARRAY = re.compile(r"\[.*\]", re.S)
_CACHE: dict[str, list[str]] = {}

# Used when there's no generator (no key / replay without a cassette) or the repo is empty.
FALLBACK = [
    "What does this repository do, and how is it organized?",
    "What are the main modules and how do they fit together?",
    "Where is the entry point and what does it call?",
]


def build_digest(symbol_map: list[tuple[str, list[str]]]) -> str:
    """`path: sym1, sym2, …` per file — the compact view the prompt reasons over."""
    return "\n".join(
        f"{path}: {', '.join(symbols)}" if symbols else path for path, symbols in symbol_map
    )


async def generate_suggestions(
    repo_id: str,
    symbol_map: list[tuple[str, list[str]]],
    generator: Generator | None = None,
) -> list[str]:
    if repo_id in _CACHE:
        return _CACHE[repo_id]
    if not symbol_map:
        return FALLBACK

    if generator is None:
        from app.core.factory import make_generator

        generator = make_generator()

    digest = build_digest(symbol_map)
    try:
        raw = await generator.complete(prompt.SYSTEM, prompt.build_user(digest))
        match = _JSON_ARRAY.search(raw or "")
        items = json.loads(match.group(0)) if match else []
        questions = [str(q).strip() for q in items if str(q).strip()][:4]
    except Exception as exc:  # noqa: BLE001 — never let suggestion generation break the workspace
        log.warning("suggestions_failed", repo_id=repo_id, error=str(exc))
        questions = []

    result = questions or FALLBACK
    _CACHE[repo_id] = result
    return result
