"""Parses a transcript source into a Transcript object.

Two source shapes are implemented:

1. The synthetic Deepgram-shaped fixture format (see SYNTHETIC-DATA.md
   section 4): {"turns": [{"speaker", "text", "start", "end", "confidence",
   "words": [{"text", "punctuated", "start", "end", "confidence", "speaker",
   "speaker_confidence"}]}]}. Real, measured word timings.

2. CIMET's real supplied format: no audio, no timings at all, unreliable
   speaker separation (a turn's text can contain the other party's words with
   no break). Produced by scripts/extract_cimet_transcript.py as
   {"lines": [{"line_number", "speaker_label", "text"}]}. Since there is no
   real timing, every word's start/end is an ESTIMATE derived purely from its
   position in the transcript at ~150wpm -- Transcript.has_word_timings is
   False for this source specifically so nothing downstream mistakes an
   estimate for a measurement, even though Word.start/end are still numeric.

The real Deepgram REST response mapping (results.utterances[], falling back
to results.channels[0].alternatives[0].words, with the punctuated_word key
and int speaker roles) lands in P6.

The only place that knows any of these formats. Nothing outside
src/adapters/ may parse them directly.
"""

import json

from src.models import Transcript, Turn, Word

WORDS_PER_MINUTE = 150
SECONDS_PER_WORD = 60.0 / WORDS_PER_MINUTE

# Whoever's text contains the recording-disclaimer language is the AGENT (the
# only speaker who would say it); the other is the CUSTOMER. Same rule
# SCHEMA.md documents for the real-Deepgram path, reused here since this
# source's turn labels ("Speaker 1"/"Speaker 2") carry no role information.
_DISCLAIMER_MARKERS = ("recorded", "quality assurance", "quality and compliance")


def load_transcript(path: str) -> Transcript:
    with open(path) as f:
        data = json.load(f)

    if "lines" in data:
        return _load_cimet_text(data)
    return _load_synthetic(data)


def _load_synthetic(data: dict) -> Transcript:
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


def _resolve_agent_label(lines: list[dict]) -> str | None:
    for row in lines:
        lowered = row["text"].lower()
        if any(marker in lowered for marker in _DISCLAIMER_MARKERS):
            return row["speaker_label"]
    return None


def _load_cimet_text(data: dict) -> Transcript:
    lines = data["lines"]
    agent_label = _resolve_agent_label(lines)

    turns = []
    word_index = 0
    for row in lines:
        if agent_label is None:
            role = row["speaker_label"].replace("Speaker ", "SPK_")
        else:
            role = "AGENT" if row["speaker_label"] == agent_label else "CUSTOMER"

        words = []
        for tok in row["text"].split():
            start = round(word_index * SECONDS_PER_WORD, 3)
            end = round(start + SECONDS_PER_WORD, 3)
            words.append(Word(
                text=tok.strip(".,?!:;\"'()").lower(),
                start=start, end=end,
                confidence=1.0,  # not ASR output -- no confidence signal exists
                punctuated=tok,
                line_number=row["line_number"],
            ))
            word_index += 1

        if not words:
            continue  # e.g. a source row that's punctuation-only, no real words

        turns.append(Turn(
            speaker=role,
            text=row["text"],
            start=words[0].start,
            end=words[-1].end,
            confidence=1.0,
            words=words,
            line_number=row["line_number"],
        ))

    return Transcript(
        turns=turns,
        source="cimet_text",
        has_word_timings=False,  # estimated, never measured -- see module docstring
        has_speakers=True,
        audio_duration=turns[-1].end if turns else 0.0,
    )
