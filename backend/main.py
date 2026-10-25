"""Hybrid RAG API (FastAPI).

Routes are defined WITHOUT the /api prefix: Nginx strips it
(proxy_pass http://localhost:8000/; — see Step 16 of the guide).
"""
import json
import logging

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import config
from app.ingest import SUPPORTED, extract
from app.llm import stream_answer
from app.store import HybridStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hybrid-rag")

app = FastAPI(title="Hybrid RAG API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])

store = HybridStore(config.DATA_DIR, config.EMBED_MODEL, config.EMBED_CACHE_DIR)


def require_admin(token: str | None):
    if config.ADMIN_TOKEN and token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Admin token required for this action")


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatTurn] = []
    mode: str = "hybrid"  # hybrid | vector | keyword
    top_k: int = Field(default=config.TOP_K, ge=1, le=20)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    mode: str = "hybrid"
    top_k: int = Field(default=config.TOP_K, ge=1, le=20)


@app.get("/health")
def health():
    return {"status": "ok", "documents": len(store.docs), "chunks": len(store.chunks)}


@app.get("/config")
def get_config():
    return {"model": config.CLAUDE_MODEL, "embed_model": config.EMBED_MODEL,
            "admin_required": bool(config.ADMIN_TOKEN), "api_key_set": bool(config.ANTHROPIC_API_KEY),
            "max_upload_mb": config.MAX_UPLOAD_MB, "supported": sorted(SUPPORTED), "top_k": config.TOP_K}


@app.get("/documents")
def list_documents():
    return store.list_documents()


@app.post("/documents")
def upload(files: list[UploadFile] = File(...), x_admin_token: str | None = Header(default=None)):
    # Plain `def` so FastAPI runs it in a thread pool: embedding is CPU-bound.
    require_admin(x_admin_token)
    added, errors = [], []
    for f in files:
        try:
            data = f.file.read()
            if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
                raise ValueError(f"File exceeds {config.MAX_UPLOAD_MB} MB")
            doc = store.add_document(f.filename, extract(f.filename, data))
            log.info("Indexed %s (%s chunks)", f.filename, doc["chunks"])
            added.append(doc)
        except Exception as e:  # report per-file so one bad file doesn't fail the batch
            log.warning("Failed to index %s: %s", f.filename, e)
            errors.append({"file": f.filename, "error": str(e)})
    if not added and errors:
        raise HTTPException(status_code=400, detail=errors)
    return {"added": added, "errors": errors}


@app.delete("/documents/{doc_id}")
def delete_document(doc_id: str, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    if not store.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": doc_id}


@app.post("/search")
def search(req: SearchRequest):
    """Retrieval only, no LLM call. Handy for comparing hybrid vs vector vs keyword."""
    return store.search(req.query, k=req.top_k, mode=req.mode)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/chat")
def chat(req: ChatRequest):
    hits = store.search(req.question, k=req.top_k, mode=req.mode)

    def generate():
        yield _sse("sources", hits)
        if not hits:
            msg = ("No relevant passages found. Upload documents first, or rephrase your question."
                   if store.chunks else "No documents are indexed yet. Upload a PDF, DOCX or text file to begin.")
            yield _sse("token", {"text": msg})
        else:
            try:
                for text in stream_answer(req.question, hits, [t.model_dump() for t in req.history]):
                    yield _sse("token", {"text": text})
            except Exception as e:
                log.exception("Claude call failed")
                yield _sse("error", {"message": str(e)})
        yield _sse("done", {})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
