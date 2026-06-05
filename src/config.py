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
    # --- LLM provider: "ollama" (local, default), "anthropic", or "openai" ---
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    llm_model: str = os.getenv("LLM_MODEL", "llama3.1")  # Ollama/OpenAI model tag
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    ollama_num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "16384"))  # must hold a full judgment
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    # llamacpp: run a GGUF directly (e.g. an Ollama-downloaded blob) without a server
    llamacpp_model_path: str = os.getenv("LLAMACPP_MODEL_PATH", "")
    llamacpp_gpu_layers: int = int(os.getenv("LLAMACPP_GPU_LAYERS", "-1"))
    # Anthropic (optional — set LLM_PROVIDER=anthropic to use)
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")

    # --- Embeddings / rerank (open source, local, multilingual) ---
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    reranker_model: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
    # reranker is a ~2.3GB download; opt in explicitly
    use_reranker: bool = os.getenv("USE_RERANKER", "false").lower() in ("1", "true", "yes")

    # --- Local storage ---
    sqlite_path: str = os.getenv("SQLITE_PATH", str(REPO_ROOT / "data" / "roscribe.db"))
    chroma_dir: str = os.getenv("CHROMA_DIR", str(REPO_ROOT / "data" / "chroma"))
    tesseract_langs: str = os.getenv("TESSERACT_LANGS", "eng+sin+tam")

    # --- Personal repository (your law-school notes) ---
    personal_repo_dir: str = os.getenv("PERSONAL_REPO_DIR", "")


settings = Settings()
