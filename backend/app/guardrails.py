from __future__ import annotations

import re
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from .config import get_settings
from .schema_docs import ALLOWED_TABLES

MAX_SQL_CHARS = 4000


class GuardrailError(ValueError):
    """The generated SQL violates a safety rule."""


_ALLOWED_ROOTS = (exp.Select, getattr(exp, "SetOperation", exp.Union))
_FORBIDDEN_NODE_NAMES = (
    "Insert", "Update", "Delete", "Drop", "Create", "Alter", "Command", "Merge", "Copy",
    "TruncateTable", "Into", "Lock", "Set", "Grant", "Transaction", "Commit", "Rollback", "Use", "Pragma",
)
_FORBIDDEN_NODES = tuple(
    cls for cls in (getattr(exp, n, None) for n in _FORBIDDEN_NODE_NAMES) if isinstance(cls, type)
)

_BLOCKED_FUNCS = {
    "set_config", "current_setting", "dblink", "dblink_exec", "lo_import", "lo_export",
    "query_to_xml", "table_to_xml", "cursor_to_xml", "database_to_xml", "schema_to_xml",
}
_BLOCKED_PREFIXES = (
    "pg_", "lo_", "dblink", "txid_", "query_to_", "table_to_", "schema_to_", "database_to_", "cursor_to_",
)


def _strip_fences(sql: str) -> str:
    return re.sub(r"^`(?:sql)?\s*|\s*`$", "", sql.strip(), flags=re.I)


def _func_name(fn: exp.Expression) -> str:
    if isinstance(fn, exp.Anonymous):
        return str(fn.this).lower()
    try:
        return fn.sql_name().lower()
    except Exception:
        return fn.key.lower()


def _enforce_limit(tree: exp.Expression, max_rows: int) -> exp.Expression:
    if isinstance(tree, exp.Select):
        limit = tree.args.get("limit")
        if limit is None:
            return tree.limit(max_rows)
        value = limit.expression
        if isinstance(value, exp.Literal) and value.is_int:
            if int(value.this) > max_rows:
                limit.set("expression", exp.Literal.number(max_rows))
        else:
            tree.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
        return tree
    return exp.select("*").from_(tree.subquery("_q")).limit(max_rows)


def validate_sql(sql: str) -> str:
    """Return a safe, LIMIT-bounded Postgres SQL string, or raise GuardrailError."""
    s = get_settings()
    if not sql or not sql.strip():
        raise GuardrailError("The SQL is empty.")

    cleaned = _strip_fences(sql).strip().rstrip(";").strip()
    if len(cleaned) > MAX_SQL_CHARS:
        raise GuardrailError("The SQL is too long.")

    try:
        statements = [t for t in sqlglot.parse(cleaned, read="postgres") if t is not None]
    except SqlglotError as e:
        raise GuardrailError(f"SQL could not be parsed: {str(e)[:200]}") from e

    if len(statements) != 1:
        raise GuardrailError("Exactly one SQL statement is allowed.")

    tree = statements[0]
    while isinstance(tree, exp.Subquery):
        tree = tree.this

    if not isinstance(tree, _ALLOWED_ROOTS):
        raise GuardrailError(
            f"Only SELECT queries (optionally with CTEs) are allowed, got {type(tree).__name__.upper()}."
        )

    for cls in _FORBIDDEN_NODES:
        if tree.find(cls):
            raise GuardrailError(f"Forbidden SQL construct: {cls.__name__.upper()}.")

    for fn in tree.find_all(exp.Func):
        name = _func_name(fn)
        if name in _BLOCKED_FUNCS or name.startswith(_BLOCKED_PREFIXES):
            raise GuardrailError(f"Function '{name}' is not allowed.")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = (table.name or "").lower()
        if not name:
            raise GuardrailError("Table-valued functions and unnamed relations are not allowed.")
        if table.db and table.db.lower() != "public":
            raise GuardrailError(
                f"Schema '{table.db}' is not allowed; only the public Northwind tables can be queried."
            )
        if name in cte_names:
            continue
        if name not in ALLOWED_TABLES:
            raise GuardrailError(
                f"Table '{name}' is not in the allowed schema (allowed: {', '.join(sorted(ALLOWED_TABLES))})."
            )

    tree = _enforce_limit(tree, s.max_rows)
    return tree.sql(dialect="postgres")
