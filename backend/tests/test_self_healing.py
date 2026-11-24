import pytest

import app.agent as agent_mod
from app.agent import DataPilotAgent
from app.db import ExecutionError
from app.llm import LLMResult
from app.retriever import RetrievalResult


class FakeRetriever:
    def retrieve(self, q, top_k=None):
        return RetrievalResult(["orders"], "hybrid", "TABLE orders: ...")

    def full_schema(self, method="full"):
        return RetrievalResult(["orders", "customers"], method, "TABLE orders: ...\nTABLE customers: ...")


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)

    def generate_json(self, prompt, system=None, max_output_tokens=2048, **kw):
        return self.replies.pop(0), LLMResult(text="", prompt_tokens=10, output_tokens=5)


def make_agent(replies):
    return DataPilotAgent(FakeLLM(replies), FakeRetriever())


@pytest.fixture
def fake_db(monkeypatch):
    def run(sql):
        if "bad_col" in sql or "nope" in sql:
            raise ExecutionError('column "bad_col" does not exist')
        if "empty_marker" in sql:
            return ["n"], []
        return ["order_id"], [{"order_id": 1}]

    monkeypatch.setattr(agent_mod, "execute_readonly", run)


def test_db_error_is_repaired_and_escalates_to_full_schema(fake_db):
    agent = make_agent([
        {"sql": "SELECT bad_col FROM orders"},
        {"diagnosis": "wrong column", "sql": "SELECT order_id FROM orders"},
    ])
    pr = agent.run_sql_pipeline("q", use_retrieval=True, max_retries=3)
    assert pr.success and pr.retries == 1
    assert pr.attempts[0]["error"].startswith("PostgreSQL error")
    assert pr.attempts[1]["schema"] == "full"


def test_guardrail_violation_is_repaired(fake_db):
    agent = make_agent([
        {"sql": "DROP TABLE orders"},
        {"diagnosis": "write attempt", "sql": "SELECT order_id FROM orders"},
    ])
    pr = agent.run_sql_pipeline("q", max_retries=3)
    assert pr.success and pr.retries == 1
    assert pr.attempts[0]["error"].startswith("Guardrail violation")


def test_confident_empty_result_is_accepted(fake_db):
    agent = make_agent([
        {"sql": "SELECT 1 AS n FROM orders WHERE order_id = -1 AND 'empty_marker' = 'empty_marker'"},
        {"diagnosis": "truly empty", "sql": "SELECT 1 FROM orders", "confident_empty": True},
    ])
    pr = agent.run_sql_pipeline("q", max_retries=3)
    assert pr.success and pr.rows == [] and pr.retries == 1


def test_retries_are_bounded(fake_db):
    agent = make_agent([
        {"sql": "SELECT nope FROM orders"},
        {"diagnosis": "x", "sql": "SELECT nope FROM orders"},
        {"diagnosis": "x", "sql": "SELECT nope FROM orders"},
    ])
    pr = agent.run_sql_pipeline("q", max_retries=2)
    assert not pr.success and pr.retries == 2 and len(pr.attempts) == 3


def test_baseline_mode_never_repairs(fake_db):
    agent = make_agent([{"sql": "SELECT nope FROM orders"}])
    pr = agent.run_sql_pipeline("q", use_retrieval=False, max_retries=0)
    assert not pr.success and pr.retries == 0
