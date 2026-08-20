"""Constrained narrative layer over already-verified findings.

The pipeline's guarantee is that no number is produced by a language model. That
guarantee is preserved here by construction:

* The model receives finished findings — titles, summaries, computed figures and
  verbatim evidence quotes — and is asked only to connect them in prose.
* Its output is attached to :class:`ResearchFinding.narrative`, a display-only
  field. No metric, computation or evidence record is created from it.
* Every produced paragraph must map to an existing finding id, and any figure it
  contains must already appear in that finding's own text. Anything else is
  discarded before it reaches the report.

The last rule is the important one: a fabricated figure cannot survive, because
a figure the deterministic layer never wrote is not in the allowed set.
"""

import re
from typing import Dict, Iterable, List, Optional, Sequence

from .models import Evidence, ResearchFinding

# A number token as it would appear in generated prose: digits with optional
# thousands separators, decimals, sign and percent marker.
_NUMBER_RE = re.compile(r"[-+−]?\d[\d,]*(?:\.\d+)?%?")

MAX_NARRATIVE_CHARS = 200


def _numbers_in(text: str) -> set:
    return {
        token.replace(",", "").replace("−", "-").lstrip("+")
        for token in _NUMBER_RE.findall(text)
    }


def finding_prompt_payload(
    finding: ResearchFinding,
    evidence_by_id: Dict[str, Evidence],
) -> dict:
    """The complete, self-contained input a narrator is allowed to see."""

    quotes = [
        evidence_by_id[evidence_id].quote
        for evidence_id in finding.evidence_ids[:6]
        if evidence_id in evidence_by_id
    ]
    return {
        "finding_id": finding.id,
        "title": finding.title,
        "summary": finding.summary,
        "calculation": finding.calculation or "",
        "reasoning_steps": list(finding.reasoning_steps),
        "counter_evidence": list(finding.counter_evidence),
        "unanswered_questions": list(finding.unanswered_questions),
        "evidence_quotes": quotes,
    }


def allowed_numbers(
    finding: ResearchFinding,
    evidence_by_id: Dict[str, Evidence],
) -> set:
    """Figures the narrator may restate from deterministic finding text only.

    Evidence quotes are sent as context, but can contain dates, page numbers or
    adjacent table values that the finding never adopted. Letting those through
    would allow the narrator to promote an unrelated disclosed number into a
    conclusion, so only figures already selected by deterministic analysis are
    eligible for restatement.
    """

    del evidence_by_id

    sources = [
        finding.title,
        finding.summary,
        finding.calculation or "",
        *finding.reasoning_steps,
        *finding.counter_evidence,
        *finding.unanswered_questions,
    ]
    return {number for text in sources for number in _numbers_in(text)}


def accept_narrative(
    finding: ResearchFinding,
    narrative: str,
    evidence_by_id: Dict[str, Evidence],
) -> Optional[str]:
    """Return the narrative if it introduces no new figure, else ``None``.

    Rejection is silent by design: the report is complete without narration, so
    a failed narrative degrades to the deterministic summary rather than
    blocking delivery or, worse, publishing an unverifiable number.
    """
    text = (narrative or "").strip()
    if not text:
        return None
    if len(text) > MAX_NARRATIVE_CHARS:
        text = text[:MAX_NARRATIVE_CHARS].rstrip()
    permitted = allowed_numbers(finding, evidence_by_id)
    if not _numbers_in(text) <= permitted:
        return None
    return text


def apply_narratives(
    findings: Iterable[ResearchFinding],
    narratives: Dict[str, str],
    evidence: Sequence[Evidence],
) -> List[str]:
    """Attach accepted narratives in place; return the ids that were rejected."""

    evidence_by_id = {item.id: item for item in evidence}
    rejected: List[str] = []
    for finding in findings:
        candidate = narratives.get(finding.id)
        if candidate is None:
            continue
        accepted = accept_narrative(finding, candidate, evidence_by_id)
        if accepted is None:
            rejected.append(finding.id)
            continue
        finding.narrative = accepted
    return rejected
