"""One-off, reproducible extraction of the CIMET-supplied redacted transcript
PDF into a plain JSON fixture that src/adapters/load_transcript.py can parse.

Not part of the live engine's fixed stack (pdfplumber is a recon-time-only
dependency) -- this script exists so the JSON fixture is regenerated from the
source PDF on demand, rather than a hand-typed, untrustworthy copy.

Usage: python scripts/extract_cimet_transcript.py
"""

import json
import re
from pathlib import Path

import pdfplumber

PDF_PATH = Path("data/cimet/call-transcript-redacted.pdf")
OUT_PATH = Path("data/cimet/call-transcript-redacted.json")

HEADER_LINE = "Redacted Call Transcript CONFIDENTIAL"
FOOTER_PREFIX = "De-identified - contains placeholder tags in place of personal information"

SPEAKER_SPLIT_RE = re.compile(r"(Speaker [12])\b")


def _page_body(page_index: int, text: str) -> str:
    lines = text.split("\n")
    if lines and lines[0] == HEADER_LINE:
        lines = lines[1:]
    if lines and lines[-1].startswith(FOOTER_PREFIX):
        lines = lines[:-1]
    return "\n".join(lines)


def extract() -> list[dict]:
    with pdfplumber.open(PDF_PATH) as pdf:
        pages_text = [_page_body(i, page.extract_text()) for i, page in enumerate(pdf.pages)]

    # Page 0 carries the masking legend and redaction notes before the
    # transcript itself starts, right after a "Transcript" section heading.
    first = pages_text[0]
    heading_idx = first.rfind("Transcript")
    if heading_idx == -1:
        raise ValueError("could not find the 'Transcript' section heading on page 1")
    pages_text[0] = first[heading_idx + len("Transcript"):]

    full_text = "\n".join(pages_text)

    parts = SPEAKER_SPLIT_RE.split(full_text)
    # re.split with a capturing group yields: [pre-text, label, chunk, label, chunk, ...]
    # pre-text before the first "Speaker N" should be empty/whitespace-only.
    if parts[0].strip():
        raise ValueError(f"unexpected text before the first speaker marker: {parts[0]!r}")

    lines = []
    line_number = 0
    for label, chunk in zip(parts[1::2], parts[2::2]):
        text = " ".join(chunk.split())  # collapse newlines/wrapped-line whitespace
        if not text:
            continue
        line_number += 1
        lines.append({"line_number": line_number, "speaker_label": label, "text": text})

    return lines


def main():
    lines = extract()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump({"lines": lines}, f, indent=2)
        f.write("\n")
    print(f"Wrote {len(lines)} lines to {OUT_PATH}")


if __name__ == "__main__":
    main()
