import urllib.request
import psycopg
from app.config import get_settings

URL = "https://raw.githubusercontent.com/pthom/northwind_psql/master/northwind.sql"

EXPECTED = {
    "customers": 91,
    "orders": 830,
    "order_details": 2155,
    "products": 77,
    "employees": 9,
}


def main() -> None:
    s = get_settings()
    print("Downloading Northwind dump ...")
    raw = urllib.request.urlopen(URL, timeout=60).read().decode("utf-8")
    sql = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("\\"))
    print("Loading into Neon (~10-30 seconds) ...")
    with psycopg.connect(s.database_url_admin, autocommit=True, prepare_threshold=None) as conn:
        conn.execute(sql)
        for table, expected in EXPECTED.items():
            n = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            flag = "OK" if n == expected else f"(expected {expected})"
            print(f"  {table:<15} {n:>6} rows {flag}")
    print("Done.")


if __name__ == "__main__":
    main()
