"""Dedicated financial research agent.

This agent deliberately does not inherit the ReAct loop. It owns a typed research
state and delegates execution to a controlled, checkpointed workflow.
"""

from typing import Optional

from .application.workflow import FinancialResearchWorkflow, ProgressCallback
from .domain.models import ResearchRequest, ResearchState
from .infrastructure.dependencies import create_default_dependencies


class FinancialResearchAgent:
    """A task-specific agent with deterministic execution boundaries."""

    name = "financial-research-agent"
    description = "可追溯的财报指标抽取、校验、分析、图表和报告 Agent"

    def __init__(self, workflow: Optional[FinancialResearchWorkflow] = None) -> None:
        self._workflow = workflow or FinancialResearchWorkflow(
            create_default_dependencies()
        )

    async def run(
        self,
        request: ResearchRequest,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> ResearchState:
        return await self._workflow.run(request, progress_callback)
