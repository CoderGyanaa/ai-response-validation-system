"""
Shared helpers for LLM-as-judge agents: building prompts that force JSON
output, and safely parsing that output back into Python.
"""
import json
import logging
import re

logger = logging.getLogger(__name__)


def extract_json(raw_text: str) -> dict:
    """
    LLMs sometimes wrap JSON in markdown fences or add stray text.
    This pulls out the first {...} block and parses it.
    Raises ValueError if nothing parseable is found.
    """
    text = raw_text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM output: {raw_text[:200]}")

    return json.loads(match.group(0))


def format_evidence(evidence: list[str], max_items: int = 5) -> str:
    if not evidence:
        return "(no evidence retrieved)"
    numbered = [f"[{i+1}] {chunk.strip()[:800]}" for i, chunk in enumerate(evidence[:max_items])]
    return "\n".join(numbered)
