"""Model-backed narrator for already-verified findings.

The model is given finished conclusions and the verbatim evidence behind them,
and is asked only to write connective prose. It is never asked to compute, and
:mod:`..domain.narration` discards any paragraph that contains a figure the
deterministic layer did not produce, so a fabricated number cannot reach the
report even if the model emits one.
"""

import json
import logging
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

MAX_FINDINGS_PER_CALL = 12

_SYSTEM_PROMPT = """你是一名财报研究助理，负责把已经过校验的研究结论
改写为连贯的中文叙述。

严格约束：
1. 只能使用输入中已经出现的数字。禁止计算、推算、四舍五入或引入任何新数字。
2. 不得给出投资建议、评级、目标价或买卖判断。
3. 不得引入输入之外的公司、行业或市场信息。
4. 每条结论输出一段不超过 200 字的中文叙述，说明该结论的含义与依据之间的关系。
5. 如果输入不足以形成叙述，该条返回空字符串。

输出必须是 JSON 对象，键为 finding_id，值为叙述字符串，不要输出其他内容。"""


def _build_user_prompt(payloads: Sequence[dict]) -> str:
    return "请为以下每条已验证结论撰写叙述。\n\n" + json.dumps(
        list(payloads), ensure_ascii=False, indent=2
    )


def _parse_response(content: str) -> Dict[str, str]:
    text = (content or "").strip()
    if text.startswith("```"):
        # Strip a fenced block without assuming a language tag is present.
        lines = [line for line in text.splitlines() if not line.startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Narrator returned non-JSON content; discarding narration")
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in parsed.items()
        if isinstance(value, str) and value.strip()
    }


class LlmNarrator:
    """Adapter around a chat-completion callable.

    ``complete`` takes ``(system_prompt, user_prompt)`` and returns raw text.
    Keeping the boundary this small means the narrator can be pointed at any
    model client without this module importing one.
    """

    def __init__(self, complete, batch_size: int = MAX_FINDINGS_PER_CALL) -> None:
        self._complete = complete
        self._batch_size = max(1, batch_size)

    def __call__(
        self, payloads: Sequence[dict], locale: str = "zh_CN"
    ) -> Dict[str, str]:
        del locale  # Only zh_CN prose is defined today; see localization notes.
        results: Dict[str, str] = {}
        batch: List[dict] = []
        for payload in payloads:
            batch.append(payload)
            if len(batch) >= self._batch_size:
                results.update(self._narrate_batch(batch))
                batch = []
        if batch:
            results.update(self._narrate_batch(batch))
        return results

    def _narrate_batch(self, batch: Sequence[dict]) -> Dict[str, str]:
        try:
            content = self._complete(_SYSTEM_PROMPT, _build_user_prompt(batch))
        except Exception as exc:
            # One failed batch must not lose the narration of the others.
            logger.warning("Narration batch failed: %s", exc)
            return {}
        return _parse_response(content)


def create_narrator(complete=None) -> Optional[LlmNarrator]:
    """Build a narrator, or ``None`` when no completion backend is supplied."""

    if complete is None:
        return None
    return LlmNarrator(complete)
