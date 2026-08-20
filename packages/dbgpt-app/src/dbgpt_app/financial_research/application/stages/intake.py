"""Research source intake stage."""

from pathlib import Path

from ...domain.models import ResearchSource, ResearchStage, ResearchState, SourceKind
from ...ports.workflow import WorkflowDependencies


class InitializeSourcesStage:
    stage = ResearchStage.INITIALIZE
    title = "建立研究任务"
    description = "规范化输入文件，去重并建立来源清单"
    category = "资料准备"
    deliverable = "去重后的来源清单"
    start_message = "正在建立研究任务和来源清单"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        del dependencies
        seen = set()
        for raw_path in state.request.file_paths:
            path = Path(raw_path).expanduser().resolve()
            if path in seen:
                continue
            seen.add(path)
            state.sources.append(
                ResearchSource(
                    kind=SourceKind.LOCAL_FILE,
                    location=str(path),
                    display_name=path.name,
                )
            )
        if state.request.source_urls:
            raise ValueError("当前工作流尚未配置公开 URL 采集适配器。")
        if not state.sources:
            raise ValueError("财报研究至少需要一个本地文件。")
        return f"已登记 {len(state.sources)} 个去重后的研究来源"
