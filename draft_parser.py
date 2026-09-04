"""Conservative parser for pasted Yahoo-style draft-board text."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable


SUFFIXES = {"jr", "sr", "ii", "iii"}
POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF", "DST"}


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    value = value.replace("'", "").replace(".", "").replace("-", " ")
    words = re.findall(r"[a-z0-9]+", value)
    return " ".join(word for word in words if word not in SUFFIXES)


def parse_line(line: str, assigned_pick: int) -> dict[str, Any]:
    raw = line.strip()
    match = re.match(r"^(?:pick\s*)?(\d+)\s*(?:[.)#:\-]\s*|\s+)(.*)$", raw, re.I)
    pick, body = (int(match.group(1)), match.group(2).strip()) if match else (assigned_pick, raw)
    tokens = body.split()
    position = next((token.upper().strip("(),") for token in tokens if token.upper().strip("(),") in POSITIONS), "")
    pos_index = next((i for i, token in enumerate(tokens) if token.upper().strip("(),") in POSITIONS), None)
    team = tokens[pos_index - 1].upper().strip("(),") if pos_index and len(tokens[pos_index - 1].strip("(),")) in (2, 3) else ""
    name_tokens = tokens[:pos_index - 1 if team else pos_index] if pos_index is not None else tokens
    name = " ".join(name_tokens).strip(" -|,") or body
    # Optional common Yahoo separators: player | position/team | fantasy team | team id.
    fantasy_team = ""; team_id = ""
    trailing = " ".join(tokens[pos_index + 1:]).strip(" -|,") if pos_index is not None else ""
    id_anywhere = re.search(r"(?:yahoo\s*)?team\s*(?:id)?\s*[#:]?\s*(\d+)", body, re.I)
    if id_anywhere:
        team_id = id_anywhere.group(1)
        trailing = (trailing[:trailing.casefold().find(id_anywhere.group(0).casefold())]
                    if id_anywhere.group(0).casefold() in trailing.casefold() else trailing).strip(" -|,")
    if trailing:
        fantasy_team = trailing
    parts = [part.strip() for part in re.split(r"\s+[|\t]\s*", body)]
    if len(parts) >= 2:
        name = parts[0]
        for part in parts[1:]:
            id_match = re.search(r"(?:team\s*(?:id)?\s*[#:]?\s*)(\d+)", part, re.I)
            if id_match: team_id = id_match.group(1)
            elif not re.search(r"\b(?:QB|RB|WR|TE|K|DEF|DST)\b", part, re.I): fantasy_team = part
    return {"pick": pick, "raw_name": name, "position": position, "team": team,
            "fantasy_team": fantasy_team, "yahoo_team_id": team_id, "raw": raw}


def parse_pasted_picks(text: str, starting_pick: int = 1) -> list[dict[str, Any]]:
    records = []
    for offset, line in enumerate(line for line in text.splitlines() if line.strip()):
        records.append(parse_line(line, starting_pick + offset))
    return records


def match_player(name: str, players: Iterable[Any]) -> tuple[Any | None, str, str]:
    """Return player, confidence, status; fuzzy ties are always ambiguous."""
    normalized = normalize_name(name)
    candidates = list(players)
    exact = [p for p in candidates if normalize_name(p.player) == normalized]
    if len(exact) == 1: return exact[0], "Exact", "Ready"
    if len(exact) > 1: return None, "Ambiguous", "Ambiguous name"
    scores = sorted(((SequenceMatcher(None, normalized, normalize_name(p.player)).ratio(), p)
                     for p in candidates), key=lambda pair: pair[0], reverse=True)
    if not scores or scores[0][0] < .78: return None, "Low", "Unmatched name"
    runner_up = scores[1][0] if len(scores) > 1 else 0
    if scores[0][0] - runner_up < .10: return None, "Ambiguous", "Ambiguous name"
    return scores[0][1], "Fuzzy", "Ready"
