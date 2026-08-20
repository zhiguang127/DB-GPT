"""Default adapter composition for the financial research workflow."""

from typing import Optional

from ..ports.workflow import Narrate, WorkflowDependencies
from .extraction import extract_annual_report_summary
from .narrator import create_narrator
from .parsers import ParserRegistry
from .reporting.charts import generate_charts
from .reporting.renderer import render_report
from .store import SQLiteResearchStore


def create_default_dependencies(
    narrate: Optional[Narrate] = None,
    complete=None,
) -> WorkflowDependencies:
    """Compose the adapters the workflow runs against.

    ``narrate`` accepts a ready-made narrator; ``complete`` is the simpler entry
    point that wraps a chat-completion callable. Both default to absent, which
    keeps the pipeline fully deterministic unless a caller opts in.
    """
    parser_registry = ParserRegistry()
    research_store = SQLiteResearchStore()
    return WorkflowDependencies(
        parse_document=parser_registry.parse,
        extract_document=extract_annual_report_summary,
        generate_charts=generate_charts,
        render_report=render_report,
        persist_state=research_store.persist,
        narrate=narrate or create_narrator(complete),
    )
