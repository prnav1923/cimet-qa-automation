"""Parses a transcript source into a Transcript object.

P1 implements only the synthetic Deepgram-shaped fixture format (see
SYNTHETIC-DATA.md section 4): {"turns": [{"speaker", "text", "start", "end",
"confidence", "words": [{"text", "punctuated", "start", "end", "confidence",
"speaker", "speaker_confidence"}]}]}.

The real Deepgram REST response mapping (results.utterances[], falling back
to results.channels[0].alternatives[0].words, with the punctuated_word key
and int speaker roles) and the CIMET plain-text fallback path (LEAD_NOTS.txt
aligned to Deepgram word timings) land in P6.

The only place that knows any of these formats. Nothing outside
src/adapters/ may parse them directly.
"""

import json

from src.models import Transcript, Turn, Word


def load_transcript(path: str) -> Transcript:
    with open(path) as f:
        data = json.load(f)

    turns = []
    for row in data.get("turns", []):
        words = [
            Word(
                text=w["text"],
                start=w["start"],
                end=w["end"],
                confidence=w.get("confidence", 1.0),
                speaker=w.get("speaker"),
                speaker_confidence=w.get("speaker_confidence", 0.0),
                punctuated=w.get("punctuated", w["text"]),
            )
            for w in row.get("words", [])
        ]
        turns.append(Turn(
            speaker=row["speaker"],
            text=row["text"],
            start=row["start"],
            end=row["end"],
            confidence=row.get("confidence", 1.0),
            words=words,
        ))

    return Transcript(
        turns=turns,
        source=data.get("source", "synthetic"),
        has_word_timings=data.get("has_word_timings", True),
        has_speakers=data.get("has_speakers", True),
        audio_duration=data.get("audio_duration", 0.0),
    )
