# DataPilot Analytics

**A production-oriented, read-only natural-language-to-SQL analytics workbench with hybrid `pgvector` schema retrieval, `sqlglot` AST guardrails, bounded self-healing query repair, and PostgreSQL-persisted telemetry & evaluation scorecards.**

| Resource | URL |
|---|---|
| **Live Web App (Vercel)** | https://datapilot-bay.vercel.app/ |
| **REST API & OpenAPI Docs (Render)** | https://datapilot-91i7.onrender.com (`/docs`) |
| **Developer Portfolio** | https://golianupreddy.github.io/portfolio/ |

> **Note on Cold Starts:** Deployed on free-tier infrastructure (Vercel, Render, Neon). After idle periods, the first API request may take ~30–50 seconds while the Render service wakes up.

---

## System Overview

DataPilot translates plain-English business questions over the **Northwind** relational schema into safe, executable PostgreSQL queries, automatically visualizes results, and records full execution telemetry. Every query passes through deterministic AST validation and executes under a least-privilege read-only database role (`datapilot_ro`).

### Core Capabilities

- **Ask SQL Workbench:** Interactive query workspace with curated preset prompts, execution mode selector (`full`, `retrieval`, `baseline`), KPI telemetry cards (status, latency, token usage, retry count), automated analyst takeaways, dynamic Recharts visualizations (bar, line, pie), sortable data tables, and a SQL + retrieved-table inspector.
- **Execution Telemetry (`/traces`):** Real-time observability dashboard tracking `p50` / `p95` end-to-end latency, success rate, self-healed query count, model routing, and historical run logs.
- **Benchmark Scorecards (`/evals`):** Automated 10-case evaluation suite comparing `full`, `retrieval`, and `baseline` modes, persisted directly in Neon PostgreSQL (`eval_runs`).

---

## Architecture & Query Pipeline

```text
User Question (Natural Language)
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 1. Hybrid Schema Retrieval                                    │
│    • 768-dim pgvector cosine similarity (gemini-embedding-001)│
│    • Lexical keyword overlap fusion -> Top-K relevant tables  │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│ 2. Intent Gate & SQL Generation                               │
│    • Single merged LLM call validates answerability & scope   │
│    • Rejects out-of-domain or mutating (DDL/DML) prompts      │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│ 3. Deterministic AST Guardrail & Read-Only Execution          │
│    • sqlglot AST check: single SELECT/CTE, table allow-list,  │
│      system catalog block, automatic LIMIT enforcement        │
│    • Executed via least-privilege `datapilot_ro` role + timeout│
└───────────────────────────────┬───────────────────────────────┘
                                │
                 ┌──────────────┴──────────────┐
                 │ Error / Rejection / 0 Rows  │ Success
                 ▼                             ▼
┌─────────────────────────────────┐  ┌──────────────────────────┐
│ 4. Bounded Self-Healing Critic  │  │ 5. Insight & Chart Spec  │
│    • Diagnoses DB/AST failure   │  │    • Analyst summary     │
│    • Rewrites SQL (max retries) ├─►│    • Chart type selection│
└─────────────────────────────────┘  └─────────────┬────────────┘
                                                   │
                                                   ▼
                                     ┌──────────────────────────┐
                                     │ 6. Telemetry Persistence │
                                     │    • Logged to PostgreSQL│
                                     └──────────────────────────┘

---

## Local Development & Testing

### 1. Backend Setup

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

Configure environment variables in backend/.env:
- DATABASE_URL — Neon PostgreSQL connection string (admin/owner for traces & eval writes)
- READONLY_DATABASE_URL — Least-privilege datapilot_ro connection string for generated query execution
- GEMINI_API_KEY — Google AI Studio API key
- LLM_MODELS — Comma-separated fallback model chain

### 2. Frontend Setup
cd frontend
npm install
npm run dev

### 3. Run Unit Tests & Evaluation Suite
cd backend
pytest
python scripts/eval_suite.py --mode full

---

## License

MIT License — built by Goli Anup Reddy (https://golianupreddy.github.io/portfolio/).
