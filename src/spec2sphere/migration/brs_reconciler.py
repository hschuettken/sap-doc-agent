"""BRS Reconciler: compare BRS docs with chain IntentCards to find deltas."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Template

from spec2sphere.llm.base import LLMProvider
from spec2sphere.llm.structured import generate_json_with_retry
from spec2sphere.migration.models import BRSDelta, BRSReference, IntentCard

_PROMPT_DIR = Path(__file__).parent / "prompts"

_RECONCILE_SYSTEM = (
    "You are an SAP BW migration expert comparing business requirement "
    "specifications with actual BW implementations. Respond with valid JSON only."
)

_RECONCILE_SCHEMA = {
    "type": "object",
    "properties": {
        "brs_says": {"type": "string"},
        "bw_does": {"type": "string"},
        "deltas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "area": {"type": "string"},
                    "brs_requirement": {"type": "string"},
                    "bw_implementation": {"type": "string"},
                    "delta_type": {"type": "string"},
                    "impact": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
        },
        "matched_requirements": {"type": "array", "items": {"type": "string"}},
        "unmatched_requirements": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["brs_says", "bw_does", "confidence"],
}


def _load_template() -> Template:
    return Template((_PROMPT_DIR / "reconcile_brs.md").read_text())


def _build_prompt(intent_card: IntentCard, brs_document: str, brs_content: str) -> str:
    template = _load_template()
    return template.render(
        brs_document=brs_document,
        brs_content=brs_content,
        chain_id=intent_card.chain_id,
        business_purpose=intent_card.business_purpose,
        data_domain=intent_card.data_domain,
        grain=intent_card.grain,
        key_measures=intent_card.key_measures,
        transformations=[
            {
                "step_number": t.step_number,
                "intent": t.intent,
                "implementation": t.implementation,
            }
            for t in intent_card.transformations
        ],
    )


async def reconcile_brs(
    intent_card: IntentCard,
    brs_document: str,
    brs_content: str,
    llm: LLMProvider,
) -> dict:
    """Compare a BRS document with a chain's IntentCard.

    Args:
        intent_card: Interpreted chain intent.
        brs_document: Filename/identifier of the BRS document.
        brs_content: Text content of the BRS document.
        llm: LLM provider for analysis.

    Returns:
        Dict with brs_says, bw_does, deltas, matched/unmatched requirements,
        confidence, and updated BRSReference objects.
    """
    prompt = _build_prompt(intent_card, brs_document, brs_content)

    data = await generate_json_with_retry(
        llm, prompt, schema=_RECONCILE_SCHEMA, system=_RECONCILE_SYSTEM, tier="brs_reconciler"
    )

    if data is None:
        return {
            "brs_says": "",
            "bw_does": "",
            "deltas": [],
            "brs_references": [],
            "confidence": 0.0,
        }

    # Build BRSReference objects from matched requirements
    brs_references = []
    for req_id in data.get("matched_requirements", []):
        brs_references.append(
            BRSReference(
                brs_document=brs_document,
                requirement_id=req_id,
                match_confidence=data.get("confidence", 0.0),
            )
        )

    # Build BRSDelta objects
    brs_deltas = []
    for delta in data.get("deltas", []):
        brs_deltas.append(
            BRSDelta(
                chain_id=intent_card.chain_id,
                brs_document=brs_document,
                brs_says=delta.get("brs_requirement", ""),
                bw_does=delta.get("bw_implementation", ""),
                delta=delta.get("notes", ""),
                delta_type=delta.get("delta_type", ""),
                confidence=data.get("confidence", 0.0),
            )
        )

    return {
        "brs_says": data.get("brs_says", ""),
        "bw_does": data.get("bw_does", ""),
        "deltas": brs_deltas,
        "brs_references": brs_references,
        "unmatched_requirements": data.get("unmatched_requirements", []),
        "confidence": data.get("confidence", 0.0),
    }


async def reconcile_brs_folder(
    intent_card: IntentCard,
    brs_folder: Path,
    llm: LLMProvider,
) -> list[dict]:
    """Reconcile an IntentCard against all BRS documents in a folder."""
    results = []
    if not brs_folder.exists():
        return results

    for brs_file in sorted(brs_folder.glob("*.md")):
        brs_content = brs_file.read_text()
        result = await reconcile_brs(intent_card, brs_file.name, brs_content, llm)
        results.append(result)

    return results
