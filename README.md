# DataPilot Analytics

**Read-only natural-language-to-SQL workbench with self-healing queries and built-in telemetry, running over the Northwind PostgreSQL database.**

| | |
|---|---|
| **Live app** | https://datapilot-bay.vercel.app/ |
| **API** | https://datapilot-91i7.onrender.com (docs at `/docs`) |
| **Portfolio** | https://golianupreddy.github.io/portfolio/ |

> Hosted on free tiers (Render, Vercel, Neon). After idle time the first request can take up to a minute while the API wakes up.

## What it does

Ask a business question in plain English. DataPilot retrieves the relevant schema, plans and writes SQL, validates it, runs it as a **SELECT-only** database role, repairs its own mistakes, and returns a table, a chart, and a short analyst insight. Every run is traced, and a benchmark suite scores the agent.

- **Ask SQL:** preset and custom prompts, mode selector (`full` / `retrieval` / `baseline`), status, latency, token and retry KPIs, analyst insight, bar/line charts, results table, and an inspector for the generated SQL and retrieved tables.
- **Traces:** p50/p95 latency, success rate, self-healed count, and a log of recent runs.
- **Evals:** saved benchmark scorecards stored in PostgreSQL.

## Architecture & Pipeline

1. **Hybrid retrieval:** Table descriptions are embedded (`gemini-embedding-001`, 768 dimensions) in `pgvector` and fused with lexical overlap so only relevant tables reach the prompt.
2. **Plan + generate:** One LLM call decides whether the question is answerable and writes the query. Out-of-scope or write requests are refused here.
3. **Validate & execute:** SQL is parsed to an AST with `sqlglot` and run under a least-privilege read-only role (`datapilot_ro`) with a statement timeout.
4. **Self-heal:** On a database error, guardrail rejection, or empty result, a critic agent diagnoses the failure and rewrites the query with bounded retries.
5. **Analyse:** The model drafts an insight and picks a chart type (best-effort; data still returns if the model is unavailable).

## Guardrails & Reliability

- **SQL Guardrails:** Single `SELECT` (CTEs allowed), table allow-list, system catalog block, automatic `LIMIT` cap, and `datapilot_ro` read-only role.
- **LLM Reliability:** Model fallback chain (`LLM_MODELS`), per-model circuit-breaker cooldowns, fail-fast retries, merged planner+SQL call, and query/embedding caching.
- **Evaluation:** 10-case benchmark (`backend/scripts/eval_suite.py`) across `full`, `retrieval`, and `baseline` modes persisted to Neon `eval_runs` (recorded `full` run `id=2`: `6/10` passed under upstream `503` spikes), plus deterministic unit tests (`backend/tests/test_self_healing.py`).
- **Stack & API:** FastAPI, `psycopg` 3, `sqlglot`, Google GenAI SDK, Neon PostgreSQL + `pgvector`, React (Vite), Recharts, Render, Vercel (`POST /ask`, `GET /traces`, `GET /evals`, `GET /health`, `GET /llm/status`).

## License

MIT

