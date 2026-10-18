"""Hybrid passage retrieval for ask() (Person B, PLAN_PS2 sections 4 and 9).

Two retrievers that fail in opposite ways, fused:

- BM25 (rank_bm25) catches exact legal terms, clause words and numbers
  ("60 days", "sublet", "Rs. 45,000").
- Dense embeddings (all-MiniLM-L6-v2 as ONNX, run by onnxruntime) in a FAISS
  inner-product index catch paraphrase ("can I leave early?" ->
  "terminate this agreement").

Rankings are combined with reciprocal-rank fusion. Everything runs in
process memory: no network, nothing written to disk. If the embedding model,
onnxruntime or FAISS is unavailable, retrieval falls back to BM25 alone
(PLAN_PS2 section 4), and the result is still deterministic.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from collections import OrderedDict
from pathlib import Path

from .config import PROJECT_ROOT
from .types import Document, Passage

log = logging.getLogger(__name__)

EMBED_MODEL_DIR = Path(os.environ.get("LEGALLENS_EMBED_MODEL_DIR",
                                      PROJECT_ROOT / "models" / "all-MiniLM-L6-v2"))
MAX_TOKENS = 256          # all-MiniLM-L6-v2 was trained up to 256 word pieces
RRF_K = 60                # standard reciprocal-rank-fusion constant
CACHE_DOCS = 4            # indexes kept in memory (one per open document)

_STOP = set("""a an and are as at be by can do does for from has have how i if in into is it its
me my of on or shall should that the their them there these this to under was what when where
which who will with would you your""".split())
_TOKEN_RE = re.compile(r"[a-z]+|\d+(?:[.,]\d+)*")


_SUFFIXES = ("ations", "ation", "ating", "ated", "ates", "ate", "ions", "ion",
             "ings", "ing", "ers", "er", "ed", "es", "s", "e")

# People ask in everyday words; contracts use legal ones. Each pattern adds
# the legal terms to the BM25 query only (never to the answer), so a tenant
# asking "can I rent a room to a friend" still reaches the sublet clause.
LAY_TERMS: list[tuple[re.Pattern, str]] = [(re.compile(p, re.I), t) for p, t in [
    (r"\b(rent (it |a room |the flat |the house )?(out|to)|room ?mate|lodger|someone else (live|stay)|share the (flat|house))",
     "sublet sublease"),
    (r"\b(leave|move out|vacate|quit|get out|break)\b.*\b(early|before)\b|\bend (the|this|my) (agreement|contract|lease|job)|\bcancel\b",
     "terminate termination notice vacate"),
    (r"\b(resign|quit (my|the) job|leave (the|my) job)\b", "resign terminate notice period"),
    (r"\b(deposit back|get (my|the) deposit|refund)\b", "deposit refund deduct"),
    (r"\b(fine|fined|charge|extra money|pay late|late payment)\b", "penalty late fee"),
    (r"\b(fix|fixing|broken|repair)\b", "repair maintenance"),
    (r"\b(raise|increase|hike)\b.*\brent\b|\brent\b.*\b(raise|increase|hike)\b", "rent increase revise escalation"),
    (r"\b(fire|fired|sack|let go|dismiss)\b", "terminate termination dismissal notice"),
    (r"\b(work for|join) (a |another )?(competitor|rival|other compan)", "non-compete competitor"),
    (r"\b(secret|private information|tell others)\b", "confidential confidentiality"),
    (r"\b(pay|salary|wage)\b.*\b(when|how much)\b|\b(when|how much)\b.*\b(pay|salary|wage)\b", "salary payment"),
]]


def _stem(tok: str) -> str:
    if not tok.isalpha() or len(tok) <= 3:
        return tok
    for suf in _SUFFIXES:
        keep = 3 if suf == "s" else 4          # "days" -> "day", but "notes" stays long enough
        if tok.endswith(suf) and len(tok) - len(suf) >= keep and not (suf == "s" and tok.endswith("ss")):
            return tok[: -len(suf)]
    return tok


def tokenize(text: str) -> list[str]:
    """Lowercase words and numbers, stopwords dropped, light suffix folding so
    'terminate', 'terminated' and 'termination' meet."""
    return [_stem(t) for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


def expand_query(query: str) -> str:
    extra = [terms for rx, terms in LAY_TERMS if rx.search(query)]
    return f"{query} {' '.join(extra)}" if extra else query


# ------------------------------------------------------------------ embedder

class _Embedder:
    """all-MiniLM-L6-v2 via onnxruntime + tokenizers: mean pooling, L2 norm."""

    def __init__(self, model_dir: Path):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.np = np
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(model_dir / "onnx" / "model.onnx"), opts,
                                            providers=["CPUExecutionProvider"])
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.enable_truncation(MAX_TOKENS)
        self.tok.enable_padding()               # pad to the longest item in each batch
        self.inputs = {i.name for i in self.session.get_inputs()}

    def embed(self, texts: list[str], batch: int = 32):
        np = self.np
        chunks = []
        for i in range(0, len(texts), batch):
            enc = self.tok.encode_batch(texts[i:i + batch])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feed)[0]                    # (b, seq, 384)
            m = mask[..., None].astype(np.float32)
            pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
            pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
            chunks.append(pooled.astype(np.float32))
        return np.vstack(chunks)


_embedder: _Embedder | None = None
_embedder_failed = False


def _get_embedder() -> _Embedder | None:
    global _embedder, _embedder_failed
    if _embedder is None and not _embedder_failed:
        try:
            import faiss  # noqa: F401  (needed for the index; fail early if absent)
            _embedder = _Embedder(EMBED_MODEL_DIR)
        except Exception as e:                  # missing files or packages -> BM25 only
            _embedder_failed = True
            log.info("dense retrieval unavailable (%s); using BM25 only", type(e).__name__)
    return _embedder


def dense_available() -> bool:
    return _get_embedder() is not None


# --------------------------------------------------------------------- index

class _Index:
    def __init__(self, passages: list[Passage]):
        from rank_bm25 import BM25Okapi

        self.passages = passages
        corpus = [tokenize(f"{p.heading or ''} {p.text}") for p in passages]
        # BM25Okapi divides by the average length; guard against all-empty corpora
        self.bm25 = BM25Okapi([toks or ["_"] for toks in corpus])
        self.faiss = None
        emb = _get_embedder()
        if emb is not None and passages:
            import faiss
            vecs = emb.embed([f"{p.heading}. {p.text}" if p.heading else p.text for p in passages])
            self.faiss = faiss.IndexFlatIP(vecs.shape[1])
            self.faiss.add(vecs)

    def search(self, query: str, k: int) -> list[tuple[Passage, float]]:
        n = len(self.passages)
        if not n:
            return []
        bm = self.bm25.get_scores(tokenize(expand_query(query)) or ["_"])
        # passages sharing no term with the query carry no BM25 evidence: leave them
        # out of its ranking instead of ranking them by position
        bm_rank = sorted((i for i in range(n) if bm[i] > 0), key=lambda i: (-bm[i], i))
        top_bm = max(max(bm), 1e-9)

        dense: dict[int, float] = {}
        dense_rank: list[int] = []
        if self.faiss is not None:
            q = _get_embedder().embed([query])
            sims, idx = self.faiss.search(q, n)
            dense_rank = [int(i) for i in idx[0] if i >= 0]
            dense = {int(i): float(s) for i, s in zip(idx[0], sims[0]) if i >= 0}

        fused: dict[int, float] = {}
        for ranking in (bm_rank, dense_rank):
            for r, i in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r + 1)
        order = sorted(fused, key=lambda i: (-fused[i], i))[:k]
        # Reported score is a relevance in [0, 1]: cosine similarity when the
        # dense model is loaded, otherwise BM25 relative to the best match.
        return [(self.passages[i], round(max(dense[i], 0.0) if dense else bm[i] / top_bm, 4))
                for i in order]


_cache: "OrderedDict[str, _Index]" = OrderedDict()


def _key(doc: Document) -> str:
    h = hashlib.sha256(doc.doc_id.encode())
    for p in doc.passages:
        h.update(b"\0" + p.id.encode() + b"\0" + p.text.encode())
    return h.hexdigest()


def retrieve(doc: Document, query: str, k: int = 3) -> list[tuple[Passage, float]]:
    """Top-k passages for a question, best first, with a relevance in [0, 1]."""
    if not doc.passages:
        return []
    key = _key(doc)
    index = _cache.get(key)
    if index is None:
        index = _Index(doc.passages)
        _cache[key] = index
        while len(_cache) > CACHE_DOCS:
            _cache.popitem(last=False)
    else:
        _cache.move_to_end(key)
    return index.search(query, k)


def clear_cache() -> None:
    """Drop every in-memory index (the UI's "clear session" calls this)."""
    _cache.clear()
