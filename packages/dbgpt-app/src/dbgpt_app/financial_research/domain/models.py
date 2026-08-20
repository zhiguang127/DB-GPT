"""Domain state and provenance models for financial research."""

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from dbgpt._private.pydantic import BaseModel, Field


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ResearchMode(str, Enum):
    SINGLE_COMPANY = "single_company"
    MULTI_COMPANY = "multi_company"


class ResearchStage(str, Enum):
    INITIALIZE = "initialize"
    PARSE = "parse"
    EXTRACT = "extract"
    NORMALIZE = "normalize"
    DERIVE = "derive"
    VALIDATE = "validate"
    DETECT_ANOMALIES = "detect_anomalies"
    INVESTIGATE_EARNINGS = "investigate_earnings"
    INVESTIGATE_CASH = "investigate_cash"
    INVESTIGATE_CAPITAL = "investigate_capital"
    REVIEW_DISCLOSURES = "review_disclosures"
    INVESTIGATE_NOTES = "investigate_notes"
    CROSS_CHECK = "cross_check"
    NARRATE = "narrate"
    # Kept for persisted jobs created by the first MVP. New plans use the
    # investigation stages above instead of independent metric chapters.
    ANALYZE_GROWTH = "analyze_growth"
    ANALYZE_PROFITABILITY = "analyze_profitability"
    ANALYZE_CASH_QUALITY = "analyze_cash_quality"
    ANALYZE_EFFICIENCY = "analyze_efficiency"
    ANALYZE_SOLVENCY = "analyze_solvency"
    ANALYZE_SEGMENTS = "analyze_segments"
    ANALYZE_PEERS = "analyze_peers"
    ASSESS_RISKS = "assess_risks"
    VERIFY_FINDINGS = "verify_findings"
    ANALYZE = "analyze"
    VISUALIZE = "visualize"
    RENDER = "render"
    COMPLETE = "complete"


class StageStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class PlanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceKind(str, Enum):
    LOCAL_FILE = "local_file"
    URL = "url"


class MetricUnit(str, Enum):
    # ``MONEY`` and ``MONEY_PER_SHARE`` are the canonical members: the currency
    # itself lives on ``FinancialMetric.currency`` so non-CNY filings (HKD, TWD,
    # JPY, KRW …) are representable. ``CNY``/``CNY_PER_SHARE`` are retained so
    # research states persisted before multi-currency support still load; use
    # the ``MONEY_UNITS``/``PER_SHARE_UNITS`` sets rather than comparing members.
    MONEY = "money"
    PERCENT = "percent"
    MONEY_PER_SHARE = "money/share"
    RATIO = "ratio"
    CNY = "CNY"
    CNY_PER_SHARE = "CNY/share"


MONEY_UNITS = frozenset({MetricUnit.MONEY, MetricUnit.CNY})
PER_SHARE_UNITS = frozenset({MetricUnit.MONEY_PER_SHARE, MetricUnit.CNY_PER_SHARE})
MONETARY_UNITS = MONEY_UNITS | PER_SHARE_UNITS
# Units whose magnitude is already dimensionless and must never be rescaled by a
# table's 单位 multiplier.
UNSCALED_UNITS = frozenset({MetricUnit.PERCENT, MetricUnit.RATIO, *PER_SHARE_UNITS})

SUPPORTED_CURRENCIES = frozenset(
    {"CNY", "HKD", "MOP", "TWD", "JPY", "KRW", "USD", "EUR", "SGD"}
)


class StatementType(str, Enum):
    SUMMARY = "summary"
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW_STATEMENT = "cash_flow_statement"
    SEGMENT_DISCLOSURE = "segment_disclosure"
    NON_RECURRING_DISCLOSURE = "non_recurring_disclosure"
    NOTE = "note"
    COMPUTED = "computed"


class ConsolidationScope(str, Enum):
    CONSOLIDATED = "consolidated"
    PARENT_COMPANY = "parent_company"
    UNSPECIFIED = "unspecified"


class PeriodType(str, Enum):
    INSTANT = "instant"
    DURATION = "duration"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class AnalysisStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    INSUFFICIENT_DATA = "insufficient_data"


class FindingTone(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    WATCH = "watch"
    WARNING = "warning"


class InvestigationStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNRESOLVED = "unresolved"
    REJECTED = "rejected"


class ResearchRequest(BaseModel):
    job_id: str = Field(default_factory=lambda: _id("research"))
    file_paths: List[str] = Field(default_factory=list)
    source_urls: List[str] = Field(default_factory=list)
    question: str = ""
    requested_mode: Optional[ResearchMode] = None
    output_dir: Optional[str] = None
    locale: str = "zh_CN"
    # OCR and model narration are both off unless explicitly requested: OCR
    # because it introduces lower-confidence evidence, narration because the
    # deterministic pipeline must remain the default source of report prose.
    enable_ocr: bool = False
    enable_narration: bool = False

    def resolved_output_dir(self) -> Path:
        if self.output_dir:
            return Path(self.output_dir).expanduser().resolve()
        return (
            Path.cwd() / "pilot" / "tmp" / "financial_research" / self.job_id
        ).resolve()


class ResearchSource(BaseModel):
    id: str = Field(default_factory=lambda: _id("source"))
    kind: SourceKind
    location: str
    display_name: str
    collected_at: datetime = Field(default_factory=utc_now)


class ParsedPage(BaseModel):
    page_number: int
    text: str
    width: Optional[float] = None
    height: Optional[float] = None
    # "digital" for an embedded text layer, "ocr" when the text was recognized
    # from a raster page. OCR-derived pages downgrade evidence confidence.
    text_source: str = "digital"


class BoundingBox(BaseModel):
    x0: float
    top: float
    x1: float
    bottom: float


class DocumentSection(BaseModel):
    id: str = Field(default_factory=lambda: _id("section"))
    title: str
    start_page: int
    end_page: int
    level: int = 1
    kind: str = "section"


class ParsedTableValue(BaseModel):
    column_index: int
    column_label: str
    raw_value: str
    page_number: int
    bbox: Optional[BoundingBox] = None


class ParsedTableRow(BaseModel):
    row_index: int
    label: str
    dimension_type: Optional[str] = None
    values: List[ParsedTableValue] = Field(default_factory=list)
    page_number: int
    raw_text: str
    bbox: Optional[BoundingBox] = None


class ParsedTable(BaseModel):
    id: str = Field(default_factory=lambda: _id("table"))
    name: str
    statement_type: StatementType
    scope: ConsolidationScope = ConsolidationScope.UNSPECIFIED
    start_page: int
    end_page: int
    unit_label: str = "元"
    currency: str = "CNY"
    scale: float = 1.0
    columns: List[str] = Field(default_factory=list)
    rows: List[ParsedTableRow] = Field(default_factory=list)
    # Which extraction strategy produced this table. "text_layout" is the
    # line-and-regex reader; "geometry" is the ruling-based reader used as an
    # independent second opinion during cross-checking.
    strategy: str = "text_layout"
    note_kind: Optional[str] = None


class ParsedDocument(BaseModel):
    id: str = Field(default_factory=lambda: _id("document"))
    source_id: str
    file_name: str
    media_type: str
    company_name: Optional[str] = None
    report_year: Optional[int] = None
    content_sha256: Optional[str] = None
    pages: List[ParsedPage] = Field(default_factory=list)
    sections: List[DocumentSection] = Field(default_factory=list)
    tables: List[ParsedTable] = Field(default_factory=list)
    # Independent geometry-based reading of the same statement pages, kept
    # separate so it can contradict `tables` instead of silently replacing it.
    geometric_tables: List[ParsedTable] = Field(default_factory=list)
    report_kind: str = "annual"
    reporting_quarter: Optional[int] = None
    currency: str = "CNY"
    ocr_page_count: int = 0


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: _id("evidence"))
    document_id: str
    source_id: str
    page_number: int
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    table_id: Optional[str] = None
    table_name: Optional[str] = None
    statement_type: Optional[StatementType] = None
    row_index: Optional[int] = None
    column_index: Optional[int] = None
    row_label: Optional[str] = None
    column_label: Optional[str] = None
    cell_value: Optional[str] = None
    bbox: Optional[BoundingBox] = None
    quote: str
    extraction_method: str
    confidence: float = 1.0
    extracted_at: datetime = Field(default_factory=utc_now)


class FinancialMetric(BaseModel):
    id: str = Field(default_factory=lambda: _id("metric"))
    document_id: str
    company_name: str
    period: str
    name: str
    display_name: str
    value: float
    unit: MetricUnit
    raw_value: Optional[str] = None
    currency: Optional[str] = None
    scale: float = 1.0
    period_type: PeriodType = PeriodType.DURATION
    scope: ConsolidationScope = ConsolidationScope.UNSPECIFIED
    statement_type: StatementType = StatementType.SUMMARY
    row_label: Optional[str] = None
    dimensions: Dict[str, str] = Field(default_factory=dict)
    is_restated: bool = False
    confidence: float = 1.0
    evidence_ids: List[str] = Field(default_factory=list)
    reported_growth_pct: Optional[float] = None
    is_reported: bool = True


class Computation(BaseModel):
    id: str = Field(default_factory=lambda: _id("computation"))
    metric_id: str
    formula_id: str
    formula_version: str = "1.0"
    expression: str
    input_metric_ids: List[str] = Field(default_factory=list)
    result: float
    engine: str = "python_deterministic"
    program_hash: str
    executed_at: datetime = Field(default_factory=utc_now)


class ValidationIssue(BaseModel):
    id: str = Field(default_factory=lambda: _id("issue"))
    severity: IssueSeverity
    code: str
    message: str
    metric_ids: List[str] = Field(default_factory=list)


class ChartArtifact(BaseModel):
    id: str = Field(default_factory=lambda: _id("chart"))
    title: str
    path: str
    media_type: str = "image/svg+xml"


class ReportArtifact(BaseModel):
    path: str
    media_type: str = "text/html"
    title: str


class StageEvent(BaseModel):
    stage: ResearchStage
    status: StageStatus
    message: str
    created_at: datetime = Field(default_factory=utc_now)


class ResearchPlanItem(BaseModel):
    stage: ResearchStage
    title: str
    description: str
    category: str = "研究执行"
    deliverable: str = ""
    depends_on: List[ResearchStage] = Field(default_factory=list)
    status: PlanStatus = PlanStatus.PENDING
    result_summary: Optional[str] = None


class ResearchFinding(BaseModel):
    id: str = Field(default_factory=lambda: _id("finding"))
    title: str
    summary: str
    tone: FindingTone = FindingTone.NEUTRAL
    company_name: Optional[str] = None
    period: Optional[str] = None
    calculation: Optional[str] = None
    metric_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    topic_key: str = "general"
    status: InvestigationStatus = InvestigationStatus.SUPPORTED
    reasoning_steps: List[str] = Field(default_factory=list)
    counter_evidence: List[str] = Field(default_factory=list)
    unanswered_questions: List[str] = Field(default_factory=list)
    # Ranking weight for headline selection. Expressed in whatever scale the
    # producing investigation uses (percentage points, share of profit, …) and
    # only compared within the same topic.
    materiality: float = 0.0
    # Model-written prose. Always optional, always derived from the fields
    # above, and dropped entirely if it fails citation validation.
    narrative: Optional[str] = None


class FinancialAnomaly(BaseModel):
    id: str = Field(default_factory=lambda: _id("anomaly"))
    topic_key: str
    company_name: str
    period: str
    signal: str
    materiality: float = 0.0
    metric_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)


class ResearchHypothesis(BaseModel):
    id: str = Field(default_factory=lambda: _id("hypothesis"))
    anomaly_id: str
    topic_key: str
    company_name: str
    question: str
    hypothesis: str
    status: InvestigationStatus = InvestigationStatus.UNRESOLVED
    required_metrics: List[str] = Field(default_factory=list)
    metric_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    resolution: Optional[str] = None


class AnalysisSection(BaseModel):
    key: str
    title: str
    objective: str
    methodology: str
    status: AnalysisStatus
    findings: List[ResearchFinding] = Field(default_factory=list)
    missing_inputs: List[str] = Field(default_factory=list)


class ResearchState(BaseModel):
    request: ResearchRequest
    status: ResearchStatus = ResearchStatus.PENDING
    mode: ResearchMode = ResearchMode.SINGLE_COMPANY
    stage: ResearchStage = ResearchStage.INITIALIZE
    plan: List[ResearchPlanItem] = Field(default_factory=list)
    sources: List[ResearchSource] = Field(default_factory=list)
    documents: List[ParsedDocument] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    raw_metrics: List[FinancialMetric] = Field(default_factory=list)
    metrics: List[FinancialMetric] = Field(default_factory=list)
    computations: List[Computation] = Field(default_factory=list)
    anomalies: List[FinancialAnomaly] = Field(default_factory=list)
    hypotheses: List[ResearchHypothesis] = Field(default_factory=list)
    analysis_sections: List[AnalysisSection] = Field(default_factory=list)
    analysis: Dict[str, Any] = Field(default_factory=dict)
    validation_issues: List[ValidationIssue] = Field(default_factory=list)
    # IDs quarantined by the validation gate.  Reported source facts remain in
    # ``raw_metrics`` for audit, while ``metrics`` contains only facts allowed
    # to participate in investigations and synthesis.
    excluded_metric_ids: List[str] = Field(default_factory=list)
    charts: List[ChartArtifact] = Field(default_factory=list)
    report: Optional[ReportArtifact] = None
    fact_store_path: Optional[str] = None
    events: List[StageEvent] = Field(default_factory=list)
    error: Optional[str] = None
