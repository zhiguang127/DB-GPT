"""Evidence-first financial research workflow.

The workflow in this package is intentionally deterministic.  LLMs may enrich the
final narrative, but they do not own parsing, calculations, charts, or citations.
"""

from .agent import FinancialResearchAgent
from .application.workflow import FinancialResearchWorkflow
from .domain.models import ResearchRequest, ResearchState

__all__ = [
    "FinancialResearchAgent",
    "FinancialResearchWorkflow",
    "ResearchRequest",
    "ResearchState",
]
