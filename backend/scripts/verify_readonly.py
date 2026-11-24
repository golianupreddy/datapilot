import psycopg
from app.config import get_settings

MUST_SUCCEED = [
    ("read orders", "SELECT count(*) FROM orders"),
]

MUST_FAIL = [
    ("INSERT", "INSERT INTO region (region_id, region_description) VALUES (99, 'x')"),
    ("UPDATE", "UPDATE products SET unit_price = 0"),
    ("DELETE", "DELETE FROM orders"),
    ("DROP TABLE", "DROP TABLE orders"),
    ("CREATE TABLE", "CREATE TABLE hack (id int)"),
    ("read query_traces", "SELECT * FROM query_traces"),
    ("read pg_shadow", "SELECT * FROM pg_shadow"),
]


def run(sql: str) -> tuple[bool, str]:
    s = get_settings()
    try:
        with psycopg.connect(s.database_url_ro, autocommit=True, connect_timeout=15) as conn:
            conn.execute(sql)
        return True, ""
    except psycopg.Error as e:
        return False, str(e).splitlines()[0]


def main() -> None:
    bad = 0
    for label, sql in MUST_SUCCEED:
        ok, err = run(sql)
        print(f"[{'PASS' if ok else 'FAIL'}] {label} {err}")
        bad += 0 if ok else 1
    for label, sql in MUST_FAIL:
        ok, err = run(sql)
        print(f"[{'PASS' if not ok else 'FAIL'}] {label} blocked -> {err or 'WAS ALLOWED!'}")
        bad += 1 if ok else 0
    print("\nAll checks passed." if bad == 0 else f"\n{bad} check(s) failed. Fix the role grants before continuing.")


if __name__ == "__main__":
    main()
