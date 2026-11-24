from app.retriever import SchemaRetriever


def test_keyword_and_join_expansion():
    r = SchemaRetriever(llm=None)
    res = r.retrieve("Top 5 product categories by revenue")
    assert "categories" in res.tables
    assert "order_details" in res.tables
    assert "products" in res.tables
