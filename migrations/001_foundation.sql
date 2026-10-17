-- Fundacao auditavel: aplicada por uma ferramenta de migracao PostgreSQL em ordem lexicografica.
-- Nenhuma tabela desta migracao e atualizada em lugar; novos estados ganham novos registros.

CREATE TABLE schema_migration (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE raw_artifact (
    artifact_id TEXT PRIMARY KEY,
    election_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    http_status SMALLINT NOT NULL CHECK (http_status BETWEEN 100 AND 599),
    content_sha256 CHAR(64) NOT NULL,
    body_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    response_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX raw_artifact_content_sha256_idx ON raw_artifact (content_sha256);

CREATE TABLE ingestion_attempt (
    attempt_id TEXT PRIMARY KEY,
    artifact_id TEXT REFERENCES raw_artifact (artifact_id),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    error_class TEXT,
    retry_number INTEGER NOT NULL CHECK (retry_number >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE parser_run (
    parser_run_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES raw_artifact (artifact_id),
    parser_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE data_lineage (
    lineage_id TEXT PRIMARY KEY,
    output_type TEXT NOT NULL,
    output_id TEXT NOT NULL,
    input_hashes JSONB NOT NULL,
    code_version TEXT NOT NULL,
    configuration_hash CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (configuration_hash ~ '^[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX data_lineage_output_idx ON data_lineage (output_type, output_id, lineage_id);

CREATE TABLE count_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    observed_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('CONSISTENTE', 'DIVERGENTE')),
    total_electorate BIGINT NOT NULL CHECK (total_electorate >= 0),
    totalized_electorate BIGINT NOT NULL CHECK (totalized_electorate >= 0),
    pending_electorate BIGINT NOT NULL CHECK (pending_electorate >= 0),
    artifact_hashes JSONB NOT NULL,
    normalizer_version TEXT NOT NULL,
    reconciliation_rule_version TEXT NOT NULL,
    diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (totalized_electorate + pending_electorate = total_electorate)
);
