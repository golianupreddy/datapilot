import pytest
from app.guardrails import GuardrailError, validate_sql


def test_valid_select_adds_limit():
    sql = validate_sql("SELECT category_name FROM categories")
    assert "LIMIT" in sql.upper()
    assert "SELECT" in sql.upper()


@pytest.mark.parametrize(
    "bad_sql",
    [
        "DELETE FROM orders",
        "DROP TABLE products",
        "UPDATE products SET unit_price = 0",
        "INSERT INTO region (region_id, region_description) VALUES (99, 'x')",
        "SELECT * FROM pg_shadow",
        "SELECT current_setting('server_version')",
        "SELECT * FROM orders; SELECT * FROM customers",
        "",
    ],
)
def test_blocks_unsafe_sql(bad_sql):
    with pytest.raises(GuardrailError):
        validate_sql(bad_sql)
