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

    # --- graph store (stretch) ---
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_auth: str = "neo4j/ariadnegraph"

    @property
    def graph_enabled(self) -> bool:
        """Neo4j is opt-in (compose --profile graph). Off in MVP."""
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
