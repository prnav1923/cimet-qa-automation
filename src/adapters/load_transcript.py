"""Parses a transcript source into a Transcript object.

Sources this will handle: a Deepgram REST response (results.utterances[],
falling back to results.channels[0].alternatives[0].words), the synthetic
Deepgram-shaped JSON fixtures, and CIMET-supplied plain text with no timings
(the LEAD_NOTS.txt fallback path, aligned to Deepgram word timings).

The only place that knows any of these formats. Nothing outside
src/adapters/ may parse them directly.
"""

from src.models import Transcript


def load_transcript(path: str) -> Transcript:
    raise NotImplementedError(
        "load_transcript: parse a Deepgram-shaped or plain-text transcript "
        "source into a Transcript object. Implemented in P1 against the "
        "synthetic format; the real Deepgram REST mapping lands in P6."
    )
