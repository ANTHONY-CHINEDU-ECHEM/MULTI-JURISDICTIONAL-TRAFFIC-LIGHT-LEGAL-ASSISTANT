"""Optional generation layer.

The evaluator and memo writer are fully deterministic and need no model. When
ANTHROPIC_API_KEY and TRAFFICLEGAL_LLM_MODEL are both set, this module asks a
Claude model to write a short narrative that is grounded only in the computed
facts and the retrieved provisions. The model is instructed to cite evidence
by number and never to introduce facts; the narrative is a presentation layer
over the deterministic findings, never a replacement for them.
"""

import json

from . import config
from .utils import get_logger, strip_dashes

LOG = get_logger("llm")

SYSTEM = (
    "You are an assistant to a traffic signal engineer and a litigation analyst. Write a neutral narrative "
    "summary of a signalized intersection crash analysis in no more than 220 words. Use only the facts, "
    "checks and numbered evidence supplied. Cite evidence as [E1], [E2] and so on. Distinguish mandatory "
    "Standards (shall) from Guidance (should). Do not state legal conclusions about fault or liability; describe "
    "whether each requirement was met. Never use hyphen or dash characters."
)


def _payload(result, question=None):
    evidence, numbered = [], 1
    for check_id, items in result.get("evidence", {}).items():
        for ev in items[:2]:
            evidence.append({"id": "E" + str(numbered), "check": check_id, "citation": ev["citation"],
                             "text": ev["text"][:500]})
            numbered += 1
    return {"question": question, "verdict": result["verdict"], "facts": result["facts"],
            "requirements": result.get("requirements"), "checks": result.get("checks"), "evidence": evidence}


def narrate(result, question=None):
    if not config.LLM_ENABLED:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic()
        message = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=700,
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(_payload(result, question), default=str)}],
        )
        text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
        return strip_dashes(text).strip()
    except Exception as exc:
        LOG.warning("Narrative generation skipped: %s", exc)
        return None


def answer_general(question, evidence):
    """Grounded answer to a regulatory question when a model is configured."""
    if not config.LLM_ENABLED or not evidence:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic()
        numbered = [{"id": "E" + str(i + 1), "citation": e.cite(), "text": e.text[:700]} for i, e in enumerate(evidence)]
        message = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=600,
            system=SYSTEM.replace("summary of a signalized intersection crash analysis", "answer to a regulatory question"),
            messages=[{"role": "user", "content": json.dumps({"question": question, "evidence": numbered})}],
        )
        text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
        return strip_dashes(text).strip()
    except Exception as exc:
        LOG.warning("Grounded answer skipped: %s", exc)
        return None
