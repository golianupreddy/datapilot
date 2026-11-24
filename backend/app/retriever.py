from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field

from .config import get_settings
from .db import admin_conn
from .llm import LLMClient
from .schema_docs import ALL_TABLES, JOIN_EDGES, SCHEMA_DOCS, render_schema

log = logging.getLogger("datapilot.retriever")

STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "by", "with", "per", "each", "what", "which",
    "who", "how", "many", "much", "is", "are", "was", "were", "show", "list", "give", "me", "all", "top", "most",
    "than", "that", "this", "from", "at", "as", "do", "does", "did", "have", "has", "their", "our", "my", "us",
}


def _norm(tok: str) -> str:
    if len(tok) > 3 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def _tokens(text: str) -> list[str]:
    return [_norm(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


def _build_keyword_index() -> dict[str, dict[str, int]]:
    index: dict[str, dict[str, int]] = {}
    for name, doc in SCHEMA_DOCS.items():
        weights: dict[str, int] = {}

        def add(text: str, weight: int) -> None:
            for t in _tokens(text):
                weights[t] = max(weights.get(t, 0), weight)

        add(name.replace("_", " "), 3)
        for syn in doc["synonyms"]:
            add(syn, 3)
        for col in doc["columns"]:
            add(col.replace("_", " "), 2)
        add(doc["description"], 1)
        index[name] = weights
    return index


def _build_adjacency() -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {t: set() for t in ALL_TABLES}
    for a, b, _ in JOIN_EDGES:
        if a != b:
            adj[a].add(b)
            adj[b].add(a)
    return adj


KEYWORD_INDEX = _build_keyword_index()
ADJ = _build_adjacency()


def _shortest_path(a: str, b: str) -> list[str]:
    if a == b:
        return [a]
    prev: dict[str, str | None] = {a: None}
    queue = deque([a])
    while queue:
        cur = queue.popleft()
        for nxt in ADJ.get(cur, ()):
            if nxt in prev:
                continue
            prev[nxt] = cur
            if nxt == b:
                path, node = [], b
                while node is not None:
                    path.append(node)
                    node = prev[node]
                return path[::-1]
            queue.append(nxt)
    return []


def expand_join_paths(tables: list[str], max_tables: int = 6) -> list[str]:
    out = list(tables)
    for i in range(len(tables)):
        for j in range(i + 1, len(tables)):
            for t in _shortest_path(tables[i], tables[j]):
                if t not in out and len(out) < max_tables:
                    out.append(t)
    return [t for t in ALL_TABLES if t in out]


@dataclass
class RetrievalResult:
    tables: list[str]
    method: str
    context: str
    scores: dict[str, float] = field(default_factory=dict)


class SchemaRetriever:
    def __init__(self, llm: LLMClient | None) -> None:
        self.llm = llm
        self.s = get_settings()

    def full_schema(self, method: str = "full") -> RetrievalResult:
        return RetrievalResult(tables=list(ALL_TABLES), method=method, context=render_schema(ALL_TABLES))

    def _keyword_rank(self, question: str) -> list[str]:
        q = set(_tokens(question))
        scored = []
        for table, weights in KEYWORD_INDEX.items():
            score = sum(weights.get(t, 0) for t in q)
            if score > 0:
                scored.append((score, table))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [t for _, t in scored]

    def _embedding_rank(self, question: str) -> list[str]:
        if self.llm is None:
            return []
        vec = self.llm.embed([question], "RETRIEVAL_QUERY")[0]
        literal = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
        with admin_conn() as conn:
            rows = conn.execute(
                "SELECT table_name FROM schema_embeddings ORDER BY embedding <=> %s::vector LIMIT 8",
                (literal,),
            ).fetchall()
        return [r["table_name"] for r in rows]

    def retrieve(self, question: str, top_k: int | None = None) -> RetrievalResult:
        k = top_k or self.s.retrieval_top_k
        keyword = self._keyword_rank(question)
        semantic: list[str] = []
        try:
            semantic = self._embedding_rank(question)
        except Exception as e:
            log.warning("Embedding retrieval failed, falling back to keyword only: %s", e)

        if not keyword and not semantic:
            return self.full_schema(method="full-fallback")

        scores: dict[str, float] = {}
        for ranking in (keyword, semantic):
            for rank, table in enumerate(ranking, start=1):
                scores[table] = scores.get(table, 0.0) + 1.0 / (60 + rank)

        top = [t for t, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:k]]
        tables = expand_join_paths(top)
        method = "hybrid" if semantic and keyword else ("keyword" if keyword else "embedding")
        return RetrievalResult(tables=tables, method=method, context=render_schema(tables), scores=scores)
