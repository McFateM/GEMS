from __future__ import annotations

import csv
import html
import re
import xml.etree.ElementTree as element_tree
from pathlib import Path

# Legacy Digital Grinnell oral-history markup inside cue text.
SPEAKER_SPAN = re.compile(
    r"<span class=['\"]oh_speaker_\d+['\"]>\s*(.*?):\s*<span class=['\"]oh_speaker_text['\"]>(.*?)</span>\s*</span>",
    re.DOTALL,
)
VOICE = re.compile(r"<v(?:\.[^ >]*)?\s+([^>]+)>")
TAG = re.compile(r"<[^>]+>")


def is_transcript_file(filename: str) -> bool:
    name = filename.lower()
    return name.endswith(".vtt") or (name.endswith(".xml") and "transcript" in name)


def format_timestamp(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


def parse_clock(value: str) -> float:
    total = 0.0
    for part in value.strip().split(":"):
        total = total * 60 + float(part)
    return total


def cue_rows(start: float, speaker: str, text: str, aliases: dict[str, str]) -> list[dict[str, str]]:
    """Split one cue into rows per tagged speaker turn, falling back to the cue's own speaker."""
    timestamp = format_timestamp(start)
    speaker = " ".join(html.unescape(speaker).split())
    turns = [(name, body) for name, body in SPEAKER_SPAN.findall(text)]
    if not turns:
        turns = [(speaker, text)]
    elif len({name for name, _ in turns}) == 1 and speaker and "&" not in speaker:
        # A single-speaker cue shows which full name ("Judy Hunter") a short label ("Judy") stands for.
        aliases.setdefault(" ".join(html.unescape(TAG.sub("", turns[0][0])).split()), speaker)
    rows = []
    for name, body in turns:
        words = " ".join(html.unescape(TAG.sub(" ", body)).split())
        if words:
            rows.append({"timestamp": timestamp, "speaker": " ".join(html.unescape(TAG.sub("", name)).split()), "words": words})
    return rows


def parse_vtt(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    aliases: dict[str, str] = {}
    for block in re.split(r"\r?\n\s*\r?\n", text):
        lines = [line for line in block.strip().splitlines() if line.strip()]
        timing = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        start = parse_clock(lines[timing].split("-->")[0])
        body = "\n".join(lines[timing + 1 :])
        voice = VOICE.search(body)
        rows.extend(cue_rows(start, voice.group(1) if voice else "", body, aliases))
    return apply_aliases(rows, aliases)


def parse_cue_xml(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    aliases: dict[str, str] = {}
    for cue in element_tree.fromstring(text).iter("cue"):
        start = cue.findtext("start") or "0"
        rows.extend(cue_rows(parse_clock(start), cue.findtext("speaker") or "", cue.findtext("transcript") or "", aliases))
    return apply_aliases(rows, aliases)


def apply_aliases(rows: list[dict[str, str]], aliases: dict[str, str]) -> list[dict[str, str]]:
    for row in rows:
        row["speaker"] = aliases.get(row["speaker"], row["speaker"])
    return rows


def write_transcript_csv(source: Path, destination: Path) -> bool:
    """Convert a WebVTT or legacy cue-XML transcript to the site's timestamp/speaker/words CSV."""
    text = source.read_text(encoding="utf-8-sig", errors="replace")
    try:
        rows = parse_vtt(text) if source.suffix.lower() == ".vtt" else parse_cue_xml(text)
    except (element_tree.ParseError, ValueError):
        return False
    if not rows:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "speaker", "words"])
        writer.writeheader()
        writer.writerows(rows)
    return True
