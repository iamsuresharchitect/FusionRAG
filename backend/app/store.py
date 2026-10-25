"""Hybrid index: dense vectors (semantic) + BM25 (keyword), fused with Reciprocal Rank Fusion.

Everything is persisted to DATA_DIR/index so the index survives container restarts
(docker-compose mounts a named volume there).
"""
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

import numpy as np

from . import config
from .ingest import chunk_text

_STOP = set(
    "a an and are as at be by for from has have in is it its of on or that the this to was were will with "
    "what which who how why when where do does did can could should would i you we they he she".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"\w+", text.lower()) if t not in _STOP and len(t) > 1]


class BM25:
    """Okapi BM25 keyword scoring (same formula as the rank_bm25 library)."""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.doc_len = np.array([len(d) for d in corpus], dtype=np.float32)
        self.avgdl = float(self.doc_len.mean()) if len(corpus) else 0.0
        self.tf: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for doc in corpus:
            counts: dict[str, int] = {}
            for t in doc:
                counts[t] = counts.get(t, 0) + 1
            self.tf.append(counts)
            for t in counts:
                df[t] = df.get(t, 0) + 1
        n = len(corpus)
        # +1 inside the log keeps IDF positive even for very common terms
        self.idf = {t: float(np.log((n - f + 0.5) / (f + 0.5) + 1.0)) for t, f in df.items()}

    def get_scores(self, query: list[str]) -> np.ndarray:
        scores = np.zeros(len(self.tf), dtype=np.float32)
        norm = self.k1 * (1 - self.b + self.b * self.doc_len / max(self.avgdl, 1e-9))
        for t in set(query):
            idf = self.idf.get(t)
            if idf is None:
                continue
            f = np.array([d.get(t, 0) for d in self.tf], dtype=np.float32)
            scores += idf * f * (self.k1 + 1) / (f + norm)
        return scores


class HybridStore:
    def __init__(self, data_dir: Path, embed_model: str, cache_dir: str):
        self.dir = Path(data_dir) / "index"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.embed_model = embed_model
        self.cache_dir = cache_dir
        self.lock = threading.RLock()
        self._embedder = None
        self.chunks: list[dict] = []
        self.docs: dict[str, dict] = {}
        self.emb = np.zeros((0, 0), dtype=np.float32)
        self.bm25: BM25 | None = None
        self._load()

    # ---------- embeddings ----------
    @property
    def embedder(self):
        if self._embedder is None:
            from fastembed import TextEmbedding

            self._embedder = TextEmbedding(model_name=self.embed_model, cache_dir=self.cache_dir)
        return self._embedder

    @staticmethod
    def _normalize(m: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(m, axis=-1, keepdims=True)
        return m / np.clip(norms, 1e-12, None)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        vecs = np.array(list(self.embedder.passage_embed(texts)), dtype=np.float32)
        return self._normalize(vecs)

    def embed_query(self, text: str) -> np.ndarray:
        vec = np.array(list(self.embedder.query_embed(text))[0], dtype=np.float32)
        return self._normalize(vec)

    # ---------- persistence ----------
    def _load(self):
        meta = self.dir / "meta.json"
        vecs = self.dir / "embeddings.npy"
        if meta.exists():
            data = json.loads(meta.read_text(encoding="utf-8"))
            self.chunks, self.docs = data.get("chunks", []), data.get("docs", {})
        if vecs.exists() and self.chunks:
            self.emb = np.load(vecs)
        self._rebuild_bm25()

    def _save(self):
        meta_tmp = self.dir / "meta.json.tmp"
        meta_tmp.write_text(json.dumps({"chunks": self.chunks, "docs": self.docs}), encoding="utf-8")
        os.replace(meta_tmp, self.dir / "meta.json")
        vec_tmp = self.dir / "embeddings.tmp.npy"
        np.save(vec_tmp, self.emb)
        os.replace(vec_tmp, self.dir / "embeddings.npy")

    def _rebuild_bm25(self):
        corpus = [tokenize(c["text"]) for c in self.chunks]
        self.bm25 = BM25(corpus) if corpus and any(corpus) else None

    # ---------- documents ----------
    def add_document(self, name: str, pages: list[tuple[int | None, str]]) -> dict:
        new_chunks = []
        doc_id = uuid.uuid4().hex[:12]
        for page, text in pages:
            for piece in chunk_text(text, config.CHUNK_SIZE, config.CHUNK_OVERLAP):
                new_chunks.append({"id": uuid.uuid4().hex[:12], "doc_id": doc_id,
                                   "doc_name": name, "page": page, "text": piece})
        if not new_chunks:
            raise ValueError("No readable text found (scanned PDFs need OCR first).")

        vecs = self.embed_passages([c["text"] for c in new_chunks])  # slow part, outside the lock
        with self.lock:
            self.emb = vecs if self.emb.size == 0 else np.vstack([self.emb, vecs])
            self.chunks.extend(new_chunks)
            doc = {"id": doc_id, "name": name, "chunks": len(new_chunks),
                   "pages": sum(1 for p, _ in pages if p is not None) or None,
                   "added": int(time.time())}
            self.docs[doc_id] = doc
            self._rebuild_bm25()
            self._save()
        return doc

    def delete_document(self, doc_id: str) -> bool:
        with self.lock:
            if doc_id not in self.docs:
                return False
            keep = [i for i, c in enumerate(self.chunks) if c["doc_id"] != doc_id]
            self.chunks = [self.chunks[i] for i in keep]
            self.emb = self.emb[keep] if keep else np.zeros((0, 0), dtype=np.float32)
            del self.docs[doc_id]
            self._rebuild_bm25()
            self._save()
            return True

    def list_documents(self) -> list[dict]:
        with self.lock:
            return sorted(self.docs.values(), key=lambda d: d["added"], reverse=True)

    # ---------- retrieval ----------
    def search(self, query: str, k: int = 6, mode: str = "hybrid") -> list[dict]:
        if mode not in ("hybrid", "vector", "keyword"):
            mode = "hybrid"
        qvec = self.embed_query(query) if mode in ("hybrid", "vector") and self.chunks else None
        with self.lock:
            if not self.chunks:
                return []
            n = config.CANDIDATES
            vec_rank: list[tuple[int, float]] = []
            kw_rank: list[tuple[int, float]] = []

            if qvec is not None:
                sims = self.emb @ qvec
                vec_rank = [(int(i), float(sims[i])) for i in np.argsort(-sims)[:n]]

            if mode in ("hybrid", "keyword") and self.bm25 is not None:
                toks = tokenize(query)
                if toks:
                    scores = self.bm25.get_scores(toks)
                    kw_rank = [(int(i), float(scores[i])) for i in np.argsort(-scores)[:n] if scores[i] > 0]

            fused: dict[int, dict] = {}
            for rank, (i, s) in enumerate(vec_rank):
                f = fused.setdefault(i, {"rrf": 0.0})
                f["rrf"] += 1.0 / (config.RRF_K + rank + 1)
                f["vector_score"], f["vector_rank"] = round(s, 4), rank + 1
            for rank, (i, s) in enumerate(kw_rank):
                f = fused.setdefault(i, {"rrf": 0.0})
                f["rrf"] += 1.0 / (config.RRF_K + rank + 1)
                f["bm25_score"], f["bm25_rank"] = round(s, 4), rank + 1

            top = sorted(fused.items(), key=lambda kv: kv[1]["rrf"], reverse=True)[:k]
            results = []
            for i, f in top:
                c = self.chunks[i]
                results.append({**{key: c[key] for key in ("id", "doc_id", "doc_name", "page", "text")},
                                "score": round(f["rrf"], 5),
                                "vector_score": f.get("vector_score"), "vector_rank": f.get("vector_rank"),
                                "bm25_score": f.get("bm25_score"), "bm25_rank": f.get("bm25_rank")})
            return results
