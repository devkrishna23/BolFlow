"""Regex cleanup: strips filler sounds and repairs transcription artifacts.

Script-safe for every language (it only ever removes English filler sounds
and fixes punctuation spacing, never rewrites words). The earlier local-LLM
(Ollama) cleanup pass was removed 2026-07-23 at the owner's request: a 2 GB
dependency for English-only polish that sometimes rewrote what was said.
"""

import re

# um/uh/umm/uhh/hmm as standalone words, with any neighboring punctuation
_FILLER = re.compile(r"\s*\b(?:um+|uh+|hm+)\b[,.]?\s*", re.IGNORECASE)


def light_clean(raw: str) -> str:
    """Strip English filler sounds and repair the stray ', ,' / double-space
    artifacts Saaras leaves where it dropped a filler itself."""
    out = _FILLER.sub(" ", raw)
    out = re.sub(r"\s*,(\s*,)+", ",", out)    # ", ," -> ","
    out = re.sub(r"\s+([,.!?])", r"\1", out)  # no space before punctuation
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"^[,.\s]+", "", out)        # can't start with punctuation
    return out or raw
