"""Traceable HTML report renderer."""

from pathlib import Path
from typing import Dict

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ...domain.localization import get_labels
from ...domain.models import (
    Evidence,
    FinancialMetric,
    ReportArtifact,
    ResearchMode,
    ResearchState,
)
from ...domain.normalization import identified_company_names
from ...domain.periods import period_sort_key


def render_report(state: ResearchState, output_dir: Path) -> ReportArtifact:
    template_dir = Path(__file__).with_name("templates")
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = environment.get_template("research_report.html")
    # Enum members were previously printed by `.value`, putting hundreds of raw
    # English tokens (consolidated, balance_sheet, supported …) into a zh-CN
    # document. The template now resolves every one through this map.
    labels = get_labels(state.request.locale)
    evidence_by_id: Dict[str, Evidence] = {item.id: item for item in state.evidence}
    evidence_index = {
        item.id: index for index, item in enumerate(state.evidence, start=1)
    }
    sources_by_id = {source.id: source for source in state.sources}
    documents_by_source = {document.source_id: document for document in state.documents}
    source_rows = []
    document_maps = []
    for source in state.sources:
        document = documents_by_source.get(source.id)
        source_rows.append(
            {
                "source": source,
                "company": document.company_name if document else None,
                "report_year": document.report_year if document else None,
                "page_count": len(document.pages) if document else 0,
                "evidence_count": sum(
                    evidence.source_id == source.id for evidence in state.evidence
                ),
            }
        )
        if document:
            document_maps.append(
                {
                    "source": source,
                    "document": document,
                    "sections": document.sections,
                    "tables": document.tables,
                }
            )
    metrics_by_company: dict[str, dict[str, list[FinancialMetric]]] = {}
    for metric in state.metrics:
        company_metrics = metrics_by_company.setdefault(metric.company_name, {})
        company_metrics.setdefault(metric.name, []).append(metric)
    for company_metrics in metrics_by_company.values():
        for items in company_metrics.values():
            items.sort(key=lambda item: period_sort_key(item.period), reverse=True)

    companies = identified_company_names(state.metrics, state.documents)
    for company in companies:
        metrics_by_company.setdefault(company, {})
    metric_by_id = {metric.id: metric for metric in state.metrics}
    computation_rows = [
        {
            "computation": computation,
            "output": metric_by_id.get(computation.metric_id),
            "inputs": [
                metric_by_id[input_id]
                for input_id in computation.input_metric_ids
                if input_id in metric_by_id
            ],
        }
        for computation in state.computations
    ]
    top_finding_ids = {
        finding["id"]
        for finding in state.analysis.get("top_findings", [])
        if finding.get("id")
    }
    if len(companies) > 1:
        research_scope_label = f"{len(companies)} 家公司"
        report_title = f"{len(companies)} 家公司可追溯财务对比报告"
    elif state.mode == ResearchMode.MULTI_COMPANY and len(state.documents) > 1:
        research_scope_label = f"{len(state.documents)} 份财报（公司身份未完整识别）"
        report_title = f"{len(state.documents)} 份财报可追溯财务对比报告"
    else:
        company = companies[0] if companies else "财报"
        research_scope_label = (
            f"{len(companies)} 家公司"
            if companies
            else f"{len(state.documents)} 份财报（公司身份未识别）"
        )
        report_title = f"{company}可追溯财务研究报告"

    report_path = output_dir / "financial_research_report.html"
    chart_svgs = [Path(item.path).read_text(encoding="utf-8") for item in state.charts]
    report_path.write_text(
        template.render(
            state=state,
            report_title=report_title,
            research_scope_label=research_scope_label,
            companies=companies,
            metrics_by_company=metrics_by_company,
            evidence_by_id=evidence_by_id,
            evidence_index=evidence_index,
            sources_by_id=sources_by_id,
            source_rows=source_rows,
            document_maps=document_maps,
            computation_rows=computation_rows,
            top_finding_ids=top_finding_ids,
            chart_svgs=chart_svgs,
            labels=labels,
        ),
        encoding="utf-8",
    )
    return ReportArtifact(path=str(report_path), title=report_title)
