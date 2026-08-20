"""Request routing rules for the dedicated financial research agent."""

import re
from pathlib import Path
from typing import Any, List


def financial_file_paths(dialogue: Any) -> List[str]:
    ext_info = getattr(dialogue, "ext_info", None)
    if not isinstance(ext_info, dict):
        return []
    value = ext_info.get("file_paths") or ext_info.get("file_path")
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def should_route_financial_research(dialogue: Any) -> bool:
    """Route explicit or unambiguous uploaded-report requests to the agent."""
    ext_info = getattr(dialogue, "ext_info", None)
    if not isinstance(ext_info, dict):
        return False
    if ext_info.get("skill_name") == "financial-report-analyzer":
        return True
    if ext_info.get("agent_mode") == "financial-research":
        return True

    file_paths = financial_file_paths(dialogue)
    if not file_paths:
        return False
    user_input = str(getattr(dialogue, "user_input", "") or "").lower()
    financial_terms = (
        "财报",
        "年度报告",
        "年报",
        "季度报告",
        "季报",
        "财务分析",
        "营收",
        "净利润",
        "financial report",
        "annual report",
    )
    if any(term in user_input for term in financial_terms):
        return True

    report_name_pattern = re.compile(
        r"(?:年度|半年度|季度)报告|年报|季报|financial[_ -]?report|annual[_ -]?report",
        re.IGNORECASE,
    )
    return any(report_name_pattern.search(Path(path).name) for path in file_paths)
