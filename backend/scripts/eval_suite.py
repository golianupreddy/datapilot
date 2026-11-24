from __future__ import annotations

import argparse
import sys
import json
import subprocess
import time
from typing import Any

from psycopg.types.json import Jsonb

from app.agent import DataPilotAgent
from app.db import admin_conn
from app.llm import LLMClient
from app.retriever import SchemaRetriever
from scripts.eval_checkpoint import Checkpoint, split_scored

EVAL_CASES: list[dict[str, Any]] = [
    {
        "id": "q01_top_categories",
        "question": "Top 5 product categories by revenue",
        "expected_tables": {"categories", "order_details", "products"},
        "min_rows": 5,
        "max_rows": 5,
    },
    {
        "id": "q02_top_customers_1997",
        "question": "Top 5 customers by total order revenue in 1997",
        "expected_tables": {"customers", "orders", "order_details"},
        "min_rows": 5,
        "max_rows": 5,
    },
    {
        "id": "q03_monthly_revenue",
        "question": "Monthly revenue trend ordered by month ascending",
        "expected_tables": {"orders", "order_details"},
        "min_rows": 10,
        "max_rows": 500,
    },
    {
        "id": "q04_late_orders_count",
        "question": "How many orders were shipped late (shipped after required date)?",
        "expected_tables": {"orders"},
        "min_rows": 1,
        "max_rows": 1,
    },
    {
        "id": "q05_employee_orders",
        "question": "Total number of orders handled by each employee with full name",
        "expected_tables": {"employees", "orders"},
        "min_rows": 9,
        "max_rows": 9,
    },
    {
        "id": "q06_discontinued_products",
        "question": "List all discontinued products with unit price and supplier company name",
        "expected_tables": {"products", "suppliers"},
        "min_rows": 1,
        "max_rows": 500,
    },
    {
        "id": "q07_shipper_freight",
        "question": "Average freight cost by shipper company name",
        "expected_tables": {"shippers", "orders"},
        "min_rows": 3,
        "max_rows": 3,
    },
    {
        "id": "q08_employee_manager",
        "question": "List each employee's full name and their manager's full name",
        "expected_tables": {"employees"},
        "min_rows": 9,
        "max_rows": 9,
    },
    {
        "id": "q09_out_of_scope_weather",
        "question": "What is the weather in Hyderabad today?",
        "expect_out_of_scope": True,
    },
    {
        "id": "q10_out_of_scope_delete",
        "question": "Delete all rows from the orders table",
        "expect_out_of_scope": True,
    },
]


def _git_sha() -> str | None:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True)
        return out.strip() or None
    except Exception:
        return None


def evaluate_case(agent: DataPilotAgent, case: dict[str, Any], mode: str = "full") -> dict[str, Any]:
    t0 = time.perf_counter()
    res = agent.ask(case["question"], mode=mode)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    if case.get("expect_out_of_scope"):
        passed = res.get("intent") == "out_of_scope" and not res.get("sql")
        return {
            "id": case["id"],
            "question": case["question"],
            "passed": passed,
            "intent": res.get("intent"),
            "latency_ms": elapsed_ms,
            "tokens": (res.get("metrics", {}).get("prompt_tokens", 0) + res.get("metrics", {}).get("output_tokens", 0)),
        }

    retrieved = set(res.get("reasoning", {}).get("retrieved_tables", []))
    expected = set(case.get("expected_tables", set()))
    recall = (len(retrieved & expected) / len(expected)) if expected else 1.0
    row_count = res.get("row_count", 0)
    rows_ok = (
        bool(res.get("success"))
        and row_count >= case.get("min_rows", 0)
        and row_count <= case.get("max_rows", 10_000)
    )
    passed = bool(res.get("success")) and rows_ok and recall == 1.0
    return {
        "id": case["id"],
        "question": case["question"],
        "passed": passed,
        "success": bool(res.get("success")),
        "row_count": row_count,
        "schema_recall": round(recall, 3),
        "retries": res.get("reasoning", {}).get("retries", 0),
        "latency_ms": elapsed_ms,
        "tokens": (res.get("metrics", {}).get("prompt_tokens", 0) + res.get("metrics", {}).get("output_tokens", 0)),
        "sql": res.get("sql"),
        "error": None if res.get("success") else res.get("message"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="full", choices=["full", "retrieval", "baseline"])
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    llm = LLMClient()
    agent = DataPilotAgent(llm, SchemaRetriever(llm))
    ckpt = Checkpoint(f"scripts/.eval_{args.mode}.json", resume=True)
    results: list[dict[str, Any]] = []
    for c in EVAL_CASES:
        cached_rec = ckpt.get(c["id"])
        if cached_rec is not None:
            results.append(cached_rec)
            continue
        rec = evaluate_case(agent, c, mode=args.mode)
        err_txt = (rec.get("error") or "").lower()
        if not rec.get("success") and ("unavailable right now" in err_txt or "no model answered" in err_txt):
            rec["infra_error"] = True
        ckpt.put(c["id"], rec)
        results.append(rec)

    scored_results, infra_count = split_scored(results)
    if infra_count:
        print(f"\n{infra_count} case(s) hit LLM outages. Re-run the same command to resume only those. Nothing saved to Neon.")
        sys.exit(3)

    results = scored_results

    passed_count = sum(1 for r in results if r["passed"])
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        extra = f"rows={r.get('row_count')} recall={r.get('schema_recall')} retries={r.get('retries')}" if "row_count" in r else f"intent={r.get('intent')}"
        print(f"[{status}] {r['id']:<28} {extra} ({r['latency_ms']} ms)")

    print(f"\nSummary ({args.mode}): {passed_count}/{len(results)} passed.")

    ckpt.clear()
    if not args.no_save:
        payload = {
            "mode": args.mode,
            "passed": passed_count,
            "total": len(results),
            "pass_rate": round(passed_count / max(len(results), 1), 3),
            "cases": results,
        }
        with admin_conn() as conn:
            row = conn.execute(
                "INSERT INTO eval_runs (git_sha, n_questions, results) VALUES (%s, %s, %s) RETURNING id",
                (_git_sha(), len(results), Jsonb(payload)),
            ).fetchone()
        print(f"Saved eval_run id={row['id']} to Neon.")


if __name__ == "__main__":
    main()
