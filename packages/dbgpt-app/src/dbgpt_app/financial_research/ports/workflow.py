"""Typed dependency boundary used by the application workflow."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..domain.models import (
    ChartArtifact,
    Evidence,
    FinancialMetric,
    ParsedDocument,
    ReportArtifact,
    ResearchSource,
    ResearchState,
)

# The second argument is a per-request OCR override; ``None`` defers to the
# adapter's own default so the shared registry stays reusable across requests.
ParseDocument = Callable[[ResearchSource, Optional[bool]], ParsedDocument]
ExtractDocument = Callable[
    [ParsedDocument], Tuple[List[Evidence], List[FinancialMetric]]
]
GenerateCharts = Callable[[List[FinancialMetric], Path], List[ChartArtifact]]
RenderReport = Callable[[ResearchState, Path], ReportArtifact]
PersistState = Callable[[ResearchState, Path], str]
# Maps a finding id to a prose paragraph. The payloads it receives are already
# verified; see :mod:`..domain.narration` for the acceptance contract that keeps
# a narrator from introducing a figure the deterministic layer never computed.
Narrate = Callable[[Sequence[dict], str], Dict[str, str]]


@dataclass(frozen=True)
class WorkflowDependencies:
    parse_document: ParseDocument
    extract_document: ExtractDocument
    generate_charts: GenerateCharts
    render_report: RenderReport
    persist_state: PersistState
    # Optional: narration is an enhancement, and the report is complete without
    # it. When absent the narrate stage is not planned at all.
    narrate: Optional[Narrate] = None
