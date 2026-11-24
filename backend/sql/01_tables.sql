CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS query_traces (
    id               BIGSERIAL PRIMARY KEY,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    question         TEXT        NOT NULL,
    mode             TEXT        NOT NULL DEFAULT 'full',
    intent           TEXT,
    plan             TEXT,
    retrieved_tables TEXT[],
    retrieval_method TEXT,
    attempts         JSONB       NOT NULL DEFAULT '[]'::jsonb,
    final_sql        TEXT,
    success          BOOLEAN     NOT NULL DEFAULT FALSE,
    retries          INT         NOT NULL DEFAULT 0,
    row_count        INT,
    chart_type       TEXT,
    insight          TEXT,
    error            TEXT,
    prompt_tokens    INT         NOT NULL DEFAULT 0,
    output_tokens    INT         NOT NULL DEFAULT 0,
    latency_ms       INT         NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS query_traces_created_idx ON query_traces (created_at DESC);

CREATE TABLE IF NOT EXISTS schema_embeddings (
    table_name TEXT PRIMARY KEY,
    doc        TEXT        NOT NULL,
    embedding  vector(768) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    git_sha     TEXT,
    n_questions INT,
    results     JSONB NOT NULL
);
