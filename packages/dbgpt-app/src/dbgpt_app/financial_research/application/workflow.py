"""Checkpointed stage runner for controlled financial research."""

import inspect
from typing import Awaitable, Callable, Optional, Sequence

from ..domain.models import (
    PlanStatus,
    ResearchPlanItem,
    ResearchRequest,
    ResearchStage,
    ResearchState,
    ResearchStatus,
    StageEvent,
    StageStatus,
)
from ..ports.workflow import WorkflowDependencies
from .planning import ResearchTaskPlanner
from .stages.base import WorkflowStage

ProgressCallback = Callable[[StageEvent, ResearchState], Optional[Awaitable[None]]]


class FinancialResearchWorkflow:
    """Execute an injectable sequence of typed stages with durable checkpoints."""

    def __init__(
        self,
        dependencies: WorkflowDependencies,
        stages: Optional[Sequence[WorkflowStage]] = None,
        planner: Optional[ResearchTaskPlanner] = None,
    ) -> None:
        self._dependencies = dependencies
        self._stages = tuple(stages) if stages is not None else None
        self._planner = planner or ResearchTaskPlanner()
        if self._stages is not None:
            self._validate_stages(self._stages)

    @staticmethod
    def _validate_stages(stages: Sequence[WorkflowStage]) -> None:
        stage_names = [stage.stage for stage in stages]
        if len(stage_names) != len(set(stage_names)):
            raise ValueError("Financial research stages must have unique stage names.")

    def _checkpoint(self, state: ResearchState) -> None:
        output_dir = state.request.resolved_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        state.fact_store_path = self._dependencies.persist_state(state, output_dir)
        target = output_dir / "research_state.json"
        temporary = output_dir / ".research_state.json.tmp"
        temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(target)

    async def _emit(
        self,
        state: ResearchState,
        stage: ResearchStage,
        status: StageStatus,
        message: str,
        callback: Optional[ProgressCallback],
    ) -> None:
        state.stage = stage
        event = StageEvent(stage=stage, status=status, message=message)
        state.events.append(event)
        self._checkpoint(state)
        if callback:
            result = callback(event, state)
            if inspect.isawaitable(result):
                await result

    def _create_plan(self, stages: Sequence[WorkflowStage]) -> list[ResearchPlanItem]:
        dependencies = self._planner.dependencies(stages)
        return [
            ResearchPlanItem(
                stage=stage.stage,
                title=stage.title,
                description=stage.description,
                category=stage.category,
                deliverable=stage.deliverable,
                depends_on=dependencies.get(stage.stage, []),
            )
            for stage in stages
        ]

    @staticmethod
    def _set_plan_status(
        state: ResearchState,
        stage: ResearchStage,
        status: PlanStatus,
        result_summary: Optional[str] = None,
    ) -> None:
        item = next((item for item in state.plan if item.stage == stage), None)
        if item:
            item.status = status
            if result_summary is not None:
                item.result_summary = result_summary

    async def run(
        self,
        request: ResearchRequest,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> ResearchState:
        stages = list(self._stages or self._planner.plan(request))
        self._validate_stages(stages)
        state = ResearchState(
            request=request,
            status=ResearchStatus.RUNNING,
            mode=self._planner.mode_for(request),
            plan=self._create_plan(stages),
        )
        try:
            stage_index = 0
            while stage_index < len(stages):
                stage = stages[stage_index]
                self._set_plan_status(state, stage.stage, PlanStatus.RUNNING)
                await self._emit(
                    state,
                    stage.stage,
                    StageStatus.STARTED,
                    stage.start_message,
                    progress_callback,
                )

                completion_message = await stage.execute(state, self._dependencies)
                self._set_plan_status(
                    state,
                    stage.stage,
                    PlanStatus.COMPLETED,
                    completion_message,
                )
                await self._emit(
                    state,
                    stage.stage,
                    StageStatus.COMPLETED,
                    completion_message,
                    progress_callback,
                )
                if stage.stage == ResearchStage.NORMALIZE and self._stages is None:
                    replanned_stages = list(
                        self._planner.plan(request, actual_mode=state.mode)
                    )
                    self._validate_stages(replanned_stages)
                    previous_plan = {item.stage: item for item in state.plan}
                    replanned_items = self._create_plan(replanned_stages)
                    for item in replanned_items:
                        previous = previous_plan.get(item.stage)
                        if previous:
                            item.status = previous.status
                            item.result_summary = previous.result_summary
                    state.plan = replanned_items
                    stages = replanned_stages
                    stage_index = next(
                        index
                        for index, item in enumerate(stages)
                        if item.stage == ResearchStage.NORMALIZE
                    )
                stage_index += 1

            state.status = ResearchStatus.COMPLETED
            await self._emit(
                state,
                ResearchStage.COMPLETE,
                StageStatus.COMPLETED,
                "可追溯财务研究完成",
                progress_callback,
            )
            return state
        except Exception as exc:
            state.status = ResearchStatus.FAILED
            state.error = str(exc)
            self._set_plan_status(state, state.stage, PlanStatus.FAILED)
            await self._emit(
                state,
                state.stage,
                StageStatus.FAILED,
                f"研究任务失败：{exc}",
                progress_callback,
            )
            raise
