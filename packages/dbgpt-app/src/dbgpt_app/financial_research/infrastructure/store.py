"""SQLite persistence for reproducible financial-research runs."""

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..domain.models import ResearchState


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, default=str)


SCHEMA = """
CREATE TABLE IF NOT EXISTS research_runs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    question TEXT NOT NULL,
    current_stage TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    location TEXT NOT NULL,
    display_name TEXT NOT NULL,
    collected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    company_name TEXT,
    report_year INTEGER,
    content_sha256 TEXT,
    page_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS document_sections (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    title TEXT NOT NULL,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    level INTEGER NOT NULL,
    kind TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parsed_tables (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    name TEXT NOT NULL,
    statement_type TEXT NOT NULL,
    scope TEXT NOT NULL,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    unit_label TEXT NOT NULL,
    currency TEXT NOT NULL,
    scale REAL NOT NULL,
    columns_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parsed_table_rows (
    job_id TEXT NOT NULL,
    table_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    label TEXT NOT NULL,
    dimension_type TEXT,
    raw_text TEXT NOT NULL,
    values_json TEXT NOT NULL,
    PRIMARY KEY (table_id, row_index)
);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    section_title TEXT,
    table_id TEXT,
    table_name TEXT,
    statement_type TEXT,
    row_index INTEGER,
    column_index INTEGER,
    row_label TEXT,
    column_label TEXT,
    cell_value TEXT,
    quote TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    confidence REAL NOT NULL,
    extracted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS financial_facts (
    id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    period TEXT NOT NULL,
    concept TEXT NOT NULL,
    display_name TEXT NOT NULL,
    raw_value TEXT,
    normalized_value REAL NOT NULL,
    unit TEXT NOT NULL,
    currency TEXT,
    scale REAL NOT NULL,
    period_type TEXT NOT NULL,
    scope TEXT NOT NULL,
    statement_type TEXT NOT NULL,
    row_label TEXT,
    dimensions_json TEXT NOT NULL,
    is_restated INTEGER NOT NULL,
    is_reported INTEGER NOT NULL,
    confidence REAL NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    fact_layer TEXT NOT NULL,
    PRIMARY KEY (id, fact_layer)
);
CREATE INDEX IF NOT EXISTS idx_financial_facts_lookup
    ON financial_facts(job_id, company_name, period, concept, scope);
CREATE TABLE IF NOT EXISTS computations (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    metric_id TEXT NOT NULL,
    formula_id TEXT NOT NULL,
    formula_version TEXT NOT NULL,
    expression TEXT NOT NULL,
    input_metric_ids_json TEXT NOT NULL,
    result REAL NOT NULL,
    engine TEXT NOT NULL,
    program_hash TEXT NOT NULL,
    executed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS validation_issues (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    metric_ids_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_tasks (
    job_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    deliverable TEXT NOT NULL,
    depends_on_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_summary TEXT,
    PRIMARY KEY (job_id, stage)
);
CREATE TABLE IF NOT EXISTS research_anomalies (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    topic_key TEXT NOT NULL,
    company_name TEXT NOT NULL,
    period TEXT NOT NULL,
    signal TEXT NOT NULL,
    materiality REAL NOT NULL,
    metric_ids_json TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_hypotheses (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    anomaly_id TEXT NOT NULL,
    topic_key TEXT NOT NULL,
    company_name TEXT NOT NULL,
    question TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    status TEXT NOT NULL,
    required_metrics_json TEXT NOT NULL,
    metric_ids_json TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    resolution TEXT
);
"""


class SQLiteResearchStore:
    """Persist one current, queryable snapshot for each research run."""

    file_name = "financial_research.sqlite3"

    def persist(self, state: ResearchState, output_dir: Path) -> str:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / self.file_name
        job_id = state.request.job_id
        with sqlite3.connect(target) as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                """
                INSERT INTO research_runs(job_id, status, mode, question, current_stage)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status=excluded.status,
                    mode=excluded.mode,
                    question=excluded.question,
                    current_stage=excluded.current_stage,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    job_id,
                    state.status.value,
                    state.mode.value,
                    state.request.question,
                    state.stage.value,
                ),
            )
            child_tables = (
                "sources",
                "documents",
                "document_sections",
                "parsed_tables",
                "parsed_table_rows",
                "evidence",
                "financial_facts",
                "computations",
                "validation_issues",
                "research_tasks",
                "research_anomalies",
                "research_hypotheses",
            )
            for table in child_tables:
                connection.execute(f"DELETE FROM {table} WHERE job_id = ?", (job_id,))

            connection.executemany(
                "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.id,
                        job_id,
                        item.kind.value,
                        item.location,
                        item.display_name,
                        item.collected_at.isoformat(),
                    )
                    for item in state.sources
                ],
            )
            for document in state.documents:
                connection.execute(
                    "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        document.id,
                        job_id,
                        document.source_id,
                        document.file_name,
                        document.media_type,
                        document.company_name,
                        document.report_year,
                        document.content_sha256,
                        len(document.pages),
                    ),
                )
                connection.executemany(
                    "INSERT INTO document_sections VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            section.id,
                            job_id,
                            document.id,
                            section.title,
                            section.start_page,
                            section.end_page,
                            section.level,
                            section.kind,
                        )
                        for section in document.sections
                    ],
                )
                for table in document.tables:
                    connection.execute(
                        "INSERT INTO parsed_tables VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            table.id,
                            job_id,
                            document.id,
                            table.name,
                            table.statement_type.value,
                            table.scope.value,
                            table.start_page,
                            table.end_page,
                            table.unit_label,
                            table.currency,
                            table.scale,
                            _json(table.columns),
                        ),
                    )
                    connection.executemany(
                        "INSERT INTO parsed_table_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            (
                                job_id,
                                table.id,
                                row.row_index,
                                row.page_number,
                                row.label,
                                row.dimension_type,
                                row.raw_text,
                                _json(row.values),
                            )
                            for row in table.rows
                        ],
                    )

            connection.executemany(
                "INSERT INTO evidence VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.id,
                        job_id,
                        item.document_id,
                        item.source_id,
                        item.page_number,
                        item.section_title,
                        item.table_id,
                        item.table_name,
                        item.statement_type.value if item.statement_type else None,
                        item.row_index,
                        item.column_index,
                        item.row_label,
                        item.column_label,
                        item.cell_value,
                        item.quote,
                        item.extraction_method,
                        item.confidence,
                        item.extracted_at.isoformat(),
                    )
                    for item in state.evidence
                ],
            )
            all_facts = [
                *((item, "raw") for item in state.raw_metrics),
                *((item, "normalized") for item in state.metrics),
            ]
            connection.executemany(
                "INSERT INTO financial_facts VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.id,
                        job_id,
                        item.document_id,
                        item.company_name,
                        item.period,
                        item.name,
                        item.display_name,
                        item.raw_value,
                        item.value,
                        item.unit.value,
                        item.currency,
                        item.scale,
                        item.period_type.value,
                        item.scope.value,
                        item.statement_type.value,
                        item.row_label,
                        _json(item.dimensions),
                        int(item.is_restated),
                        int(item.is_reported),
                        item.confidence,
                        _json(item.evidence_ids),
                        fact_layer,
                    )
                    for item, fact_layer in all_facts
                ],
            )
            connection.executemany(
                "INSERT INTO computations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.id,
                        job_id,
                        item.metric_id,
                        item.formula_id,
                        item.formula_version,
                        item.expression,
                        _json(item.input_metric_ids),
                        item.result,
                        item.engine,
                        item.program_hash,
                        item.executed_at.isoformat(),
                    )
                    for item in state.computations
                ],
            )
            connection.executemany(
                "INSERT INTO validation_issues VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.id,
                        job_id,
                        item.severity.value,
                        item.code,
                        item.message,
                        _json(item.metric_ids),
                    )
                    for item in state.validation_issues
                ],
            )
            connection.executemany(
                "INSERT INTO research_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        job_id,
                        item.stage.value,
                        item.title,
                        item.description,
                        item.category,
                        item.deliverable,
                        _json([stage.value for stage in item.depends_on]),
                        item.status.value,
                        item.result_summary,
                    )
                    for item in state.plan
                ],
            )
            connection.executemany(
                "INSERT INTO research_anomalies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.id,
                        job_id,
                        item.topic_key,
                        item.company_name,
                        item.period,
                        item.signal,
                        item.materiality,
                        _json(item.metric_ids),
                        _json(item.evidence_ids),
                    )
                    for item in state.anomalies
                ],
            )
            connection.executemany(
                "INSERT INTO research_hypotheses VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.id,
                        job_id,
                        item.anomaly_id,
                        item.topic_key,
                        item.company_name,
                        item.question,
                        item.hypothesis,
                        item.status.value,
                        _json(item.required_metrics),
                        _json(item.metric_ids),
                        _json(item.evidence_ids),
                        item.resolution,
                    )
                    for item in state.hypotheses
                ],
            )
        return str(target)
