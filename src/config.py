"""Central configuration. Reads from environment / .env (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    reranker_model: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
    sqlite_path: str = os.getenv("SQLITE_PATH", str(REPO_ROOT / "data" / "roscribe.db"))
    chroma_dir: str = os.getenv("CHROMA_DIR", str(REPO_ROOT / "data" / "chroma"))
    tesseract_langs: str = os.getenv("TESSERACT_LANGS", "eng+sin+tam")


settings = Settings()
