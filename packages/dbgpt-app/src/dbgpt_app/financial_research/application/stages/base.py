"""Stage contract for the controlled research workflow."""

from typing import Protocol

from ...domain.models import ResearchStage, ResearchState
from ...ports.workflow import WorkflowDependencies


class WorkflowStage(Protocol):
    stage: ResearchStage
    title: str
    description: str
    category: str
    deliverable: str
    start_message: str

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str: ...
