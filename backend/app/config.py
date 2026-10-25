"""Central configuration. Every value can be overridden in backend/.env."""
import os
from pathlib import Path

try:  # lets you run `uvicorn main:app` locally without Docker
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- Claude / Anthropic ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1500"))

# --- Embeddings (local, CPU, no extra API key needed) ---
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_CACHE_DIR = os.getenv("EMBED_CACHE_DIR", str(DATA_DIR / "models"))

# --- Chunking & retrieval ---
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
TOP_K = int(os.getenv("TOP_K", "6"))
CANDIDATES = int(os.getenv("CANDIDATES", "25"))  # per retriever, before fusion
RRF_K = int(os.getenv("RRF_K", "60"))

# --- Security / limits ---
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")  # protects upload & delete when set
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
