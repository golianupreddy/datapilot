from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from functools import lru_cache
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent import DataPilotAgent
from .config import get_settings
from .db import admin_conn
from .llm import LLMClient
from .retriever import SchemaRetriever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()

app = FastAPI(title="DataPilot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache
def get_agent() -> DataPilotAgent:
    llm = LLMClient()
    return DataPilotAgent(llm, SchemaRetriever(llm))


_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request) -> None:
    limit = settings.rate_limit_per_minute
    if limit <= 0:
        return
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    now = time.monotonic()
    if len(_hits) > 5000:
        _hits.clear()
    window = _hits[ip]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= limit:
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute and try again.")
    window.append(now)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    mode: Literal["full", "retrieval", "baseline"] = "full"


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def root():
    return {
        "service": "DataPilot Analytics API",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "frontend": "https://datapilot-bay.vercel.app/",
    }


@app.get("/health")
def health():
    db_ok = True
    try:
        with admin_conn() as conn:
            conn.execute("SELECT 1")
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "model": settings.llm_model}


@app.post("/ask", dependencies=[Depends(rate_limit)])
def ask(req: AskRequest):
    return get_agent().ask(req.question, req.mode)


METRICS_SQL = """SELECT
  COUNT(*)                                                         AS total_queries,
  ROUND(AVG(success::int)::numeric, 3)                             AS success_rate,
  ROUND(AVG(retries)::numeric, 3)                                  AS avg_retries,
  COUNT(*) FILTER (WHERE retries > 0)                              AS needed_repair,
  COUNT(*) FILTER (WHERE retries > 0 AND success)                  AS self_healed,
  ROUND((COUNT(*) FILTER (WHERE retries > 0 AND success))::numeric
        / NULLIF(COUNT(*) FILTER (WHERE retries > 0), 0), 3)       AS recovery_rate,
  ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms))::numeric, 0)  AS p50_latency_ms,
  ROUND((percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms))::numeric, 0) AS p95_latency_ms,
  ROUND(AVG(prompt_tokens + output_tokens)::numeric, 0)            AS avg_tokens
FROM query_traces
WHERE intent IS DISTINCT FROM 'out_of_scope'"""

TRACES_SQL = """SELECT id, created_at, question, mode, intent, retrieved_tables, retrieval_method, attempts, final_sql,
       success, retries, row_count, chart_type, error, prompt_tokens, output_tokens, latency_ms
FROM query_traces
ORDER BY id DESC
LIMIT %s"""


@app.get("/traces")
def traces(limit: int = Query(50, ge=1, le=200)):
    with admin_conn() as conn:
        rows = conn.execute(TRACES_SQL, (limit,)).fetchall()
        metrics = conn.execute(METRICS_SQL).fetchone()
    return {"traces": rows, "metrics": metrics}


@app.get("/evals")
def evals():
    with admin_conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, git_sha, n_questions, results FROM eval_runs ORDER BY id DESC LIMIT 5"
        ).fetchall()
    return {"runs": rows}


@app.get("/llm/status")
def llm_status():
    return {"chain": get_agent().llm.status()}
