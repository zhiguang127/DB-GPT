"""Financial run and immutable report snapshot in the existing metadata DB."""

from sqlalchemy import Column, Index, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT

from dbgpt.storage.metadata import Model


class FinancialRunEntity(Model):
    __tablename__ = "dbgpt_financial_analysis_run"
    __table_args__ = (Index("idx_financial_run_scope", "owner_id", "session_id"),)

    id = Column(String(36), primary_key=True)
    owner_id = Column(String(255), nullable=False)
    session_id = Column(String(255), nullable=False)
    file_id = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False)
    stage = Column(String(32), nullable=False)
    created_at = Column(String(40), nullable=False)
    updated_at = Column(String(40), nullable=False)
    completed_at = Column(String(40), nullable=True)
    error = Column(Text, nullable=True)
    report_json = Column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True)


class FinancialExportEntity(Model):
    """Immutable generated files; ownership is inherited from the parent run."""

    __tablename__ = "dbgpt_financial_analysis_export"
    __table_args__ = (Index("idx_financial_export_run", "run_id", "revision"),)
    id = Column(String(64), primary_key=True)
    run_id = Column(String(36), nullable=False)
    revision = Column(String(255), nullable=False)
    format = Column(String(8), nullable=False)
    file_name = Column(String(255), nullable=False)
    created_at = Column(String(40), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    content = Column(Text().with_variant(LONGTEXT(), "mysql"), nullable=False)
