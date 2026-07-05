"""Typed application settings.

Single source of truth for every knob. Everything is environment-driven so the
volatile axes (embedding/LLM provider, rerank, determinism mode) can be switched
without code changes — see docs/DECISIONS.md.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

CassetteMode = Literal["off", "record", "replay"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- infrastructure ---
    database_url: str = "postgresql+asyncpg://ariadne:ariadne@postgres:5432/ariadne"
    qdrant_url: str = "http://qdrant:6333"
    redis_url: str = "redis://redis:6379/0"

    # --- LLM / embeddings (all LLM access flows through LangChain) ---
    gemini_api_key: str = ""
    embedding_provider: Literal["gemini", "voyage", "local"] = "gemini"
    embedding_model: str = "models/gemini-embedding-001"
    llm_model: str = "gemini-3.5-flash"
    voyage_api_key: str = ""

    # --- retrieval ---
    rerank_enabled: bool = False
    top_k: int = 8
    retrieve_limit: int = 40
    rrf_k: int = 60

    # --- harness / determinism ---
    cassette_mode: CassetteMode = "off"
    cassette_dir: str = "tests/cassettes"

    # --- generator-critic budgets ---
    max_critic_iterations: int = 2
    token_budget: int = 12_000
    request_timeout_s: float = 90.0

    # --- observability ---
    log_level: str = "INFO"
    otel_enabled: bool = True

    # --- graph store (opt-in: docker compose --profile graph up + GRAPH_ENABLED=true) ---
    graph_enabled: bool = False
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_auth: str = "neo4j/ariadnegraph"
    graph_augment_top: int = 3  # how many top hits to expand via the graph

    # --- agents (coordinator + specialized personas) ---
    dev_search_enabled: bool = True  # authorship-backed "who wrote this" persona
    coordinator_enabled: bool = True  # route questions to a persona; off → plain Daedalus QA
    router_min_confidence: float = 0.5  # below this, fall back to QA

    # --- orchestrator (Theseus): confidence-gated dynamic tool-calling ---
    orchestrator_enabled: bool = False  # dark-launch; off → coordinator/Daedalus path unchanged
    gate_default_threshold: float = 0.6  # min necessity to run an action when no per-type override
    gate_thresholds: dict[str, float] = {  # per action-type necessity bar (cheap low, costly high)
        "retrieval": 0.5,
        "graph_neighbors": 0.55,
        "authorship_lookup": 0.6,
        "version_diff": 0.65,
    }
    action_budget: int = 6  # max gated actions per run (bounds the ReAct loop)
    max_intent_revisions: int = 1  # how many times intent may be re-derived on new evidence
    escalation_threshold: float = 0.7  # crisis prob at/above which we escalate to a human/help

    # --- human-in-the-loop (high-stakes proposals pause for approval) ---
    hitl_enabled: bool = True  # gate architect proposals on human approval via interrupt()


@lru_cache
def get_settings() -> Settings:
    return Settings()
