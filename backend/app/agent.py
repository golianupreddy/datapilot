from __future__ import annotations

import copy
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Jsonb

from .config import get_settings
from .db import ExecutionError, admin_conn, execute_readonly
from .guardrails import GuardrailError, validate_sql
from .llm import LLMClient, LLMError, LLMResult
from .retriever import SchemaRetriever
from .schema_docs import BUSINESS_RULES, TABLE_OVERVIEW

log = logging.getLogger("datapilot.agent")

ROUTER_SYSTEM = """You are the router/planner of DataPilot, an analytics assistant over the Northwind trading-company PostgreSQL database.
Decide whether the user's message can be answered with a READ-ONLY SQL query over these tables:
{overview}

Return JSON only:
{{"intent": "data_question" | "out_of_scope",
  "plan": "<max 2 sentences: which tables, joins and aggregations are needed>",
  "refusal": "<one polite sentence if out_of_scope, else empty string>"}}

Mark out_of_scope when the message asks to modify data (insert/update/delete/drop), asks for credentials or system information,
asks about things not in this database (weather, news, general knowledge, coding help), or is not a question about the data."""

SQL_GEN_SYSTEM = """You are an expert PostgreSQL analyst. Write ONE read-only SQL query that answers the question using ONLY the tables and columns in the provided schema.
Rules:
- Output a single SELECT statement (a WITH ... CTE is allowed). Never write INSERT/UPDATE/DELETE/DDL.
- No trailing semicolon. Qualify columns with table aliases whenever you join.
- Give output columns short, readable snake_case aliases.
- For "top N" / "best" / "worst" questions use ORDER BY ... LIMIT N. Order time series by date ascending.
- Cast to numeric before ROUND: ROUND((expr)::numeric, 2).
- Follow the BUSINESS RULES exactly.
- Respond with JSON only: {"sql": "<query>", "explanation": "<one sentence>"}"""

CRITIC_SYSTEM = """You are a senior PostgreSQL debugger. A generated query failed or returned suspicious results. Diagnose the cause and return a corrected query.
Checklist: wrong or hallucinated column/table names, missing join keys, ROUND on non-numeric, wrong aggregation or GROUP BY, wrong filter value spelling
or case (use ILIKE), wrong date range (data covers 1996-07 to 1998-05), misuse of the business rules.
If the problem is ZERO_ROWS and you are confident an empty result is genuinely the correct answer, set confident_empty to true and return the same SQL.
Respond with JSON only: {"diagnosis": "<one sentence>", "sql": "<corrected query>", "confident_empty": false}"""

ANALYST_SYSTEM = """You are a data analyst. Given the question, column names and a sample of the result rows, write a 1-3 sentence insight that cites specific numbers from the data
(no speculation beyond the data) and choose the best chart.
- chart.type is one of: bar | line | pie | table | metric.
- line only for time series; pie only for shares of <= 6 categories; metric for a single value; table if no chart fits.
- chart.x must be an exact column name; chart.y must be a list of exact NUMERIC column names.
Respond with JSON only: {"insight": "...", "chart": {"type": "bar", "x": "col", "y": ["col"]}}"""

CHART_TYPES = {"bar", "line", "pie", "table", "metric"}
ESCALATE_HINTS = ("does not exist", "not allowed", "not in the allowed")
ZERO_ROWS = "ZERO_ROWS: the query ran successfully but returned no rows."


@dataclass
class Usage:
    prompt_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add(self, r: LLMResult) -> None:
        self.prompt_tokens += r.prompt_tokens
        self.output_tokens += r.output_tokens
        self.calls += 1


@dataclass
class PipelineResult:
    success: bool
    sql: str | None
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    retries: int = 0
    tables: list[str] = field(default_factory=list)
    retrieval_method: str | None = None
    schema_chars: int = 0
    error: str | None = None


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _numeric_columns(columns: list[str], rows: list[dict[str, Any]]) -> list[str]:
    out = []
    for c in columns:
        vals = [r.get(c) for r in rows if r.get(c) is not None]
        if vals and all(_is_num(v) for v in vals):
            out.append(c)
    return out


def heuristic_chart(columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    table = {"type": "table", "x": None, "y": []}
    nums = _numeric_columns(columns, rows)
    if not rows or not nums:
        return table
    cats = [c for c in columns if c not in nums]
    if len(rows) == 1:
        return {"type": "metric", "x": None, "y": [nums[0]]} if len(columns) == 1 else table
    x = cats[0] if cats else nums[0]
    ys = [c for c in nums if c != x][:3]
    if not ys:
        return table
    if re.search(r"date|month|year|week|day|quarter|period", x, re.I):
        return {"type": "line", "x": x, "y": ys}
    if len(rows) <= 6 and len(ys) == 1 and all((r.get(ys[0]) or 0) >= 0 for r in rows):
        return {"type": "pie", "x": x, "y": ys}
    return {"type": "bar", "x": x, "y": ys}


def sanitize_chart(chart: Any, columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(chart, dict) or chart.get("type") not in CHART_TYPES:
        return heuristic_chart(columns, rows)
    ctype = chart["type"]
    if ctype == "table":
        return {"type": "table", "x": None, "y": []}
    nums = _numeric_columns(columns, rows)
    ys = chart.get("y") or []
    if isinstance(ys, str):
        ys = [ys]
    ys = [y for y in ys if y in nums]
    if ctype == "metric":
        return {"type": "metric", "x": None, "y": ys[:1]} if ys else heuristic_chart(columns, rows)
    x = chart.get("x")
    if x not in columns or not ys:
        return heuristic_chart(columns, rows)
    if ctype == "pie":
        ys = ys[:1]
    return {"type": ctype, "x": x, "y": ys[:4]}


class DataPilotAgent:
    def __init__(self, llm: LLMClient, retriever: SchemaRetriever) -> None:
        self.llm = llm
        self.retriever = retriever
        self.s = get_settings()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def route(self, question: str, usage: Usage) -> dict[str, Any]:
        obj, res = self.llm.generate_json(
            f"QUESTION: {question}", system=ROUTER_SYSTEM.format(overview=TABLE_OVERVIEW), max_output_tokens=512
        )
        usage.add(res)
        if obj.get("intent") not in ("data_question", "out_of_scope"):
            obj["intent"] = "data_question"
        return obj

    def generate_sql(self, question: str, schema_ctx: str, plan: str, usage: Usage) -> str:
        prompt = f"SCHEMA:\n{schema_ctx}\n\nBUSINESS RULES:\n{BUSINESS_RULES}\n\n"
        if plan:
            prompt += f"PLAN: {plan}\n\n"
        prompt += f"QUESTION: {question}"
        obj, res = self.llm.generate_json(prompt, system=SQL_GEN_SYSTEM)
        usage.add(res)
        sql = obj.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            raise LLMError("Model returned no SQL.")
        return sql

    def repair_sql(self, question: str, schema_ctx: str, history: list[tuple[str, str]], usage: Usage) -> dict[str, Any]:
        past = "\n\n".join(f"ATTEMPT {i}:\n{sql}\nPROBLEM: {prob}" for i, (sql, prob) in enumerate(history[-3:], 1))
        prompt = (
            f"SCHEMA:\n{schema_ctx}\n\nBUSINESS RULES:\n{BUSINESS_RULES}\n\n"
            f"QUESTION: {question}\n\n{past}\n\nReturn the corrected query."
        )
        obj, res = self.llm.generate_json(prompt, system=CRITIC_SYSTEM)
        usage.add(res)
        if not isinstance(obj.get("sql"), str) or not obj["sql"].strip():
            raise LLMError("Critic returned no SQL.")
        return obj

    def analyze(self, question: str, columns: list[str], rows: list[dict[str, Any]], usage: Usage) -> dict[str, Any]:
        sample = json.dumps(rows[:25], default=str)[:6000]
        prompt = f"QUESTION: {question}\nCOLUMNS: {columns}\nROW COUNT: {len(rows)}\nSAMPLE ROWS: {sample}"
        obj, res = self.llm.generate_json(prompt, system=ANALYST_SYSTEM, max_output_tokens=768)
        usage.add(res)
        return {"insight": str(obj.get("insight", "")).strip(), "chart": sanitize_chart(obj.get("chart"), columns, rows)}

    def run_sql_pipeline(
        self,
        question: str,
        use_retrieval: bool = True,
        max_retries: int | None = None,
        plan: str = "",
        usage: Usage | None = None,
    ) -> PipelineResult:
        usage = usage or Usage()
        max_retries = self.s.max_sql_retries if max_retries is None else max_retries
        retrieval = self.retriever.retrieve(question) if use_retrieval else self.retriever.full_schema()
        ctx, schema_label = retrieval.context, ("retrieved" if use_retrieval else "full")
        base = dict(tables=retrieval.tables, retrieval_method=retrieval.method, schema_chars=len(retrieval.context))

        sql = self.generate_sql(question, ctx, plan, usage)
        attempts: list[dict[str, Any]] = []
        history: list[tuple[str, str]] = []
        repairs = 0

        for attempt_no in range(1, max_retries + 2):
            entry: dict[str, Any] = {
                "n": attempt_no,
                "kind": "generate" if attempt_no == 1 else "repair",
                "schema": schema_label,
                "sql": sql,
                "error": None,
                "row_count": None,
                "diagnosis": None,
            }
            safe_sql, columns, rows = sql, [], []
            try:
                safe_sql = validate_sql(sql)
                entry["sql"] = safe_sql
                columns, rows = execute_readonly(safe_sql)
                entry["row_count"] = len(rows)
                if rows or attempt_no > max_retries:
                    attempts.append(entry)
                    return PipelineResult(True, safe_sql, columns, rows, attempts, repairs, **base)
                problem = ZERO_ROWS
            except GuardrailError as e:
                problem = f"Guardrail violation: {e}"
            except ExecutionError as e:
                problem = f"PostgreSQL error: {e}"

            entry["error"] = problem
            attempts.append(entry)
            history.append((entry["sql"], problem))
            if attempt_no > max_retries:
                break

            if schema_label == "retrieved" and any(h in problem.lower() for h in ESCALATE_HINTS):
                ctx, schema_label = self.retriever.full_schema().context, "full"

            fix = self.repair_sql(question, ctx, history, usage)
            repairs += 1
            new_sql = fix["sql"]
            entry["diagnosis"] = str(fix.get("diagnosis", ""))[:300]
            if problem == ZERO_ROWS and (fix.get("confident_empty") is True or new_sql.strip() == sql.strip()):
                return PipelineResult(True, safe_sql, columns, [], attempts, repairs, **base)
            sql = new_sql

        last = attempts[-1]
        return PipelineResult(False, last["sql"], [], [], attempts, repairs, error=last["error"], **base)

    def ask(self, question: str, mode: str = "full") -> dict[str, Any]:
        s = self.s
        question = " ".join(question.split())
        key = f"{mode}:{question.lower()}"
        hit = self._cache.get(key)
        if hit and (time.time() - hit[0]) < s.cache_ttl_seconds:
            cached = copy.deepcopy(hit[1])
            cached["metrics"]["cached"] = True
            return cached

        t0 = time.perf_counter()
        usage = Usage()
        resp: dict[str, Any] = {
            "id": None, "question": question, "mode": mode, "intent": None, "plan": "",
            "success": False, "message": "", "sql": None, "columns": [], "rows": [], "row_count": 0,
            "chart": None, "insight": "",
            "reasoning": {"retrieved_tables": [], "retrieval_method": None, "attempts": [], "retries": 0},
            "metrics": {},
        }
        cacheable = True
        try:
            plan = ""
            if mode == "full":
                route = self.route(question, usage)
                resp["intent"], plan = route["intent"], str(route.get("plan", ""))
                resp["plan"] = plan
                if resp["intent"] != "data_question":
                    resp["message"] = route.get("refusal") or "I can only answer questions about the Northwind sales database."
                    return self._finish(resp, usage, t0, cacheable=False)
            else:
                resp["intent"] = "data_question"

            pr = self.run_sql_pipeline(
                question,
                use_retrieval=(mode != "baseline"),
                max_retries=(s.max_sql_retries if mode == "full" else 0),
                plan=plan,
                usage=usage,
            )
            resp["sql"], resp["columns"], resp["rows"], resp["row_count"] = pr.sql, pr.columns, pr.rows, len(pr.rows)
            resp["reasoning"] = {
                "retrieved_tables": pr.tables,
                "retrieval_method": pr.retrieval_method,
                "attempts": pr.attempts,
                "retries": pr.retries,
            }
            if pr.success:
                resp["success"] = True
                resp["chart"] = heuristic_chart(pr.columns, pr.rows)
                if mode == "full" and pr.rows:
                    try:
                        analysis = self.analyze(question, pr.columns, pr.rows, usage)
                        resp["insight"], resp["chart"] = analysis["insight"], analysis["chart"]
                    except LLMError as e:
                        log.warning("Analyst failed: %s", e)
                if not pr.rows:
                    resp["message"] = "The query ran successfully but returned no rows."
            else:
                resp["message"] = f"I could not produce a working query after {pr.retries} repair attempt(s). Last error: {pr.error}"
        except LLMError as e:
            resp["message"] = f"The language model is unavailable right now: {e}"
            cacheable = False

        return self._finish(resp, usage, t0, cacheable=cacheable)

    def _finish(self, resp: dict[str, Any], usage: Usage, t0: float, cacheable: bool) -> dict[str, Any]:
        resp["metrics"] = {
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "prompt_tokens": usage.prompt_tokens,
            "output_tokens": usage.output_tokens,
            "llm_calls": usage.calls,
            "cached": False,
        }
        resp["id"] = self._log_trace(resp)
        if cacheable and resp["success"]:
            if len(self._cache) > 200:
                self._cache.pop(next(iter(self._cache)))
            self._cache[f"{resp['mode']}:{resp['question'].lower()}"] = (time.time(), copy.deepcopy(resp))
        return resp

    def _log_trace(self, resp: dict[str, Any]) -> int | None:
        r, m = resp["reasoning"], resp["metrics"]
        try:
            with admin_conn() as conn:
                row = conn.execute(
                    """
                    INSERT INTO query_traces
                      (question, mode, intent, plan, retrieved_tables, retrieval_method, attempts, final_sql,
                       success, retries, row_count, chart_type, insight, error,
                       prompt_tokens, output_tokens, latency_ms)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        resp["question"], resp["mode"], resp["intent"], resp["plan"],
                        r["retrieved_tables"], r["retrieval_method"], Jsonb(r["attempts"]), resp["sql"],
                        resp["success"], r["retries"], resp["row_count"],
                        (resp["chart"] or {}).get("type"), resp["insight"],
                        None if resp["success"] else resp["message"],
                        m["prompt_tokens"], m["output_tokens"], m["latency_ms"],
                    ),
                ).fetchone()
            return row["id"]
        except Exception as e:
            log.warning("Could not write trace: %s", e)
            return None
