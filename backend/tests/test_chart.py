from app.agent import heuristic_chart, sanitize_chart


def test_metric_and_bar_charts():
    m = heuristic_chart(["total_orders"], [{"total_orders": 830}])
    assert m["type"] == "metric"

    rows_7 = [{"category_name": f"Cat {i}", "total_revenue": 1000 * i} for i in range(1, 8)]
    b = heuristic_chart(["category_name", "total_revenue"], rows_7)
    assert b["type"] == "bar"
    assert b["x"] == "category_name"
    assert b["y"] == ["total_revenue"]

    two_rows = [
        {"category_name": "Beverages", "total_revenue": 100},
        {"category_name": "Dairy", "total_revenue": 200},
    ]
    s = sanitize_chart(
        {"type": "bar", "x": "bad_col", "y": ["total_revenue"]},
        ["category_name", "total_revenue"],
        two_rows,
    )
    assert s["x"] == "category_name"
