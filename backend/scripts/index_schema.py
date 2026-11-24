from app.db import admin_conn
from app.llm import LLMClient
from app.schema_docs import SCHEMA_DOCS, embedding_text


def main() -> None:
    llm = LLMClient()
    names = list(SCHEMA_DOCS)
    texts = [embedding_text(n) for n in names]
    print(f"Embedding {len(texts)} table docs ...")
    vectors = llm.embed(texts, "RETRIEVAL_DOCUMENT")
    with admin_conn() as conn:
        for name, text, vec in zip(names, texts, vectors):
            literal = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
            conn.execute(
                """
                INSERT INTO schema_embeddings (table_name, doc, embedding)
                VALUES (%s, %s, %s::vector)
                ON CONFLICT (table_name) DO UPDATE
                SET doc = EXCLUDED.doc, embedding = EXCLUDED.embedding, updated_at = now()
                """,
                (name, text, literal),
            )
        conn.execute("DELETE FROM schema_embeddings WHERE table_name <> ALL(%s)", (names,))
        n = conn.execute("SELECT count(*) AS n FROM schema_embeddings").fetchone()["n"]
    print(f"Done. {n} rows in schema_embeddings (dimension {len(vectors[0])}).")


if __name__ == "__main__":
    main()
