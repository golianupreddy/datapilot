from __future__ import annotations

import datetime as dt
import decimal
from typing import Any
import psycopg
from psycopg.rows import dict_row
from .config import get_settings


class ExecutionError(Exception):
    """A database error raised while running the generated SQL."""


def admin_conn() -> psycopg.Connection:
    """Autocommit admin connection (traces, embeddings, evals). Returns dict rows."""
    s = get_settings()
    return psycopg.connect(
        s.database_url_admin,
        autocommit=True,
        row_factory=dict_row,
        prepare_threshold=None,
        connect_timeout=15,
    )


def to_jsonable(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "<binary>"
    return v


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
    return out


def _clean_error(e: psycopg.Error) -> str:
    diag = getattr(e, "diag", None)
    msg = getattr(diag, "message_primary", None) or str(e).splitlines()[0]
    hint = getattr(diag, "message_hint", None)
    return f"{msg} (hint: {hint})" if hint else msg


def execute_readonly(sql: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Run validated SQL as the read-only role, in a READ ONLY transaction with a timeout."""
    s = get_settings()
    try:
        with psycopg.connect(s.database_url_ro, prepare_threshold=None, connect_timeout=15) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL statement_timeout = {int(s.statement_timeout_ms)}")
                cur.execute(sql)
                if cur.description is None:
                    raise ExecutionError("Query did not return a result set.")
                columns = _unique([d.name for d in cur.description])
                raw = cur.fetchmany(s.max_rows)
            conn.rollback()
    except psycopg.Error as e:
        raise ExecutionError(_clean_error(e)) from e
    rows = [dict(zip(columns, (to_jsonable(v) for v in r))) for r in raw]
    return columns, rows
