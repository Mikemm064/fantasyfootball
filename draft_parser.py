"""Parse and reconcile Yahoo draft clipboard exports.

Yahoo currently exposes two different text layouts depending on which draft
view is copied.  This module deliberately deals in plain text: presentational
Markdown and image markup are discarded before records are recognised.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Protocol


POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF", "DST"}
SUFFIXES = {"ii", "iii", "iv", "jr", "sr"}


class PlayerLike(Protocol):
    player: str
    position: str
    team: str


@dataclass
class DraftPick:
    overall_pick: int
    player_name: str
    position: str
    nfl_team: str
    fantasy_team: str = ""
    bye_week: int | None = None
    mine: bool = False
    ownership_source: str = ""
    confidence: str = ""
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    matched_player: PlayerLike | None = None
    yahoo_slot: str = ""

    # Convenient names for callers which use the ranking-file vocabulary.
    @property
    def player(self) -> str:
        return self.player_name

    @property
    def team(self) -> str:
        return self.nfl_team

    @property
    def pick(self) -> int:
        return self.overall_pick


@dataclass
class ImportResult:
    picks: list[DraftPick]
    new_picks: list[DraftPick]
    conflicts: list[DraftPick]
    unchanged: list[DraftPick] = field(default_factory=list)


def _plain_lines(content: str) -> list[str]:
    """Remove common clipboard presentation noise without consuming data."""
    content = re.sub(r"!\[[^]]*]\([^)]*\)", "\n", content)
    content = re.sub(r"https?://\S+", "\n", content)
    content = re.sub(r"<svg\b.*?</svg\s*>", "\n", content, flags=re.I | re.S)
    content = re.sub(r"<[^>]+>", "\n", content)
    lines: list[str] = []
    for raw in content.splitlines():
        # A table row becomes the same sequence of tokens as vertical text.
        cells = raw.split("|") if "|" in raw else [raw]
        for cell in cells:
            value = re.sub(r"[*_`~]", "", cell).strip()
            if not value or re.fullmatch(r"[-: ]{3,}", value):
                continue
            if value.casefold() in {"svg", "image"}:
                continue
            lines.append(value)
    return lines


def _overall(value: str, teams: int) -> int | None:
    if value.isdigit():
        return int(value)
    match = re.fullmatch(r"(\d+)\.(\d+)", value)
    if match:
        round_number, round_pick = map(int, match.groups())
        return (round_number - 1) * teams + round_pick
    return None


def parse_yahoo_clipboard(content: str, *, teams: int = 10,
                          my_team_name: str = "Sippin' On Jeanty Juice",
                          yahoo_team_id: str | int = 6,
                          draft_slot: int = 3) -> list[DraftPick]:
    """Auto-detect both confirmed Yahoo formats and return picks in pick order."""
    lines = _plain_lines(content)
    picks = _parse_manager_format(lines, teams)
    if not picks:
        picks = _parse_board_format(lines, teams)
    # A mock-draft clipboard can explicitly identify a different temporary slot.
    # It applies only to this parse call and never mutates saved league settings.
    explicit = next((pick for pick in picks if _key(pick.fantasy_team) in {"you", "yourteam"}), None)
    session_slot = _slot_for_pick(explicit.overall_pick, teams) if explicit else draft_slot
    for pick in picks:
        _set_ownership(pick, teams, my_team_name, str(yahoo_team_id), session_slot)
    return sorted(picks, key=lambda item: item.overall_pick)


def _parse_manager_format(lines: list[str], teams: int) -> list[DraftPick]:
    picks: list[DraftPick] = []
    # Locate records by the highly distinctive pick/name/position/team spine;
    # the immediately preceding value is the fantasy manager label.
    for i in range(1, len(lines) - 3):
        overall = _overall(lines[i], teams)
        position = lines[i + 2].upper()
        if overall is None or position not in POSITIONS:
            continue
        bye = None
        if i + 4 < len(lines):
            match = re.fullmatch(r"Bye\s+(\d+)", lines[i + 4], re.I)
            bye = int(match.group(1)) if match else None
        picks.append(DraftPick(overall, lines[i + 1], position,
                               lines[i + 3].upper(), lines[i - 1], bye))
    return picks


def _parse_board_format(lines: list[str], teams: int) -> list[DraftPick]:
    picks: list[DraftPick] = []
    for i in range(len(lines) - 4):
        position = lines[i + 2].upper()
        overall = _overall(lines[i + 4], teams)
        if position in POSITIONS and overall is not None:
            picks.append(DraftPick(overall, f"{lines[i]} {lines[i + 1]}",
                                   position, lines[i + 3].upper(), yahoo_slot=lines[i + 4] if "." in lines[i + 4] else ""))
    return picks


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _set_ownership(pick: DraftPick, teams: int, team_name: str,
                   team_id: str, draft_slot: int) -> None:
    manager = _key(pick.fantasy_team)
    signals = [
        (manager == "you", "yahoo_you", "very_high"),
        (manager == "yourteam", "yahoo_your_team", "very_high"),
        (bool(manager) and manager in {_key(team_id), _key(f"Team {team_id}")},
         "yahoo_team_id", "high"),
        (bool(manager) and manager == _key(team_name), "configured_team_name", "high"),
        (_snake_owned(pick.overall_pick, teams, draft_slot), "snake_pick", "medium"),
    ]
    positives = [(source, confidence) for yes, source, confidence in signals if yes]
    # The priority is encoded by list order.
    if positives:
        pick.mine = True
        pick.ownership_source, pick.confidence = positives[0]
    explicit_other = bool(manager) and manager not in {"you", "yourteam"} and not any(
        yes for yes, _, _ in signals[2:4])
    if explicit_other and signals[-1][0]:
        pick.needs_review = True
        pick.review_reasons.append("ownership signals conflict")
    elif any(yes for yes, _, _ in signals[:4]) and not signals[-1][0]:
        pick.needs_review = True
        pick.review_reasons.append("ownership signals conflict")


def _slot_for_pick(overall: int, teams: int) -> int:
    round_number, offset = divmod(overall - 1, teams)
    return offset + 1 if round_number % 2 == 0 else teams - offset


def _snake_owned(overall: int, teams: int, slot: int) -> bool:
    round_number, offset = divmod(overall - 1, teams)
    expected = slot if round_number % 2 == 0 else teams - slot + 1
    return offset + 1 == expected


def _name_parts(name: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", name.casefold())


def _abbreviation_matches(abbreviated: str, full: str) -> bool:
    short, long = _name_parts(abbreviated), _name_parts(full)
    if not short or not long:
        return False
    if short[-1] in SUFFIXES:
        if long[-1] != short[-1]:
            return False
        short, long = short[:-1], long[:-1]
    # Every abbreviated token must align in order. Initials match initials;
    # complete tokens match exactly, supporting St. Brown and Smith-Njigba.
    cursor = 0
    for token in short:
        found = False
        while cursor < len(long):
            candidate = long[cursor]
            cursor += 1
            if (len(token) == 1 and candidate.startswith(token)) or token == candidate:
                found = True
                break
        if not found:
            return False
    return True


def match_players(picks: Iterable[DraftPick], candidates: Iterable[PlayerLike]) -> list[DraftPick]:
    """Match only on the combined Yahoo name, position and NFL-team identity."""
    picks = list(picks)
    pool = list(candidates)
    for pick in picks:
        matches = [player for player in pool
                   if player.position.upper() == pick.position
                   and player.team.upper() == pick.nfl_team
                   and _abbreviation_matches(pick.player_name, player.player)]
        if len(matches) == 1:
            pick.matched_player = matches[0]
        else:
            pick.needs_review = True
            pick.review_reasons.append("ambiguous player" if matches else "unmatched player")
    return picks


def _identity(value: object) -> tuple[str, str, str, str]:
    """Stable ID first, then normalized name/position/team identity."""
    if isinstance(value, dict):
        player = value.get("player", value.get("player_name", ""))
        player_id = value.get("player_id", "")
        position, team = value.get("position", ""), value.get("team", value.get("nfl_team", ""))
    else:
        player = getattr(value, "matched_player", None) or getattr(value, "player", "")
        player_id = getattr(player, "id", "") or getattr(value, "player_id", "")
        position = getattr(player, "position", "") or getattr(value, "position", "")
        team = getattr(player, "team", "") or getattr(value, "nfl_team", "")
    if hasattr(player, "player"):
        player_id = player_id or getattr(player, "id", "")
        position, team = getattr(player, "position", position), getattr(player, "team", team)
        player = player.player
    return str(player_id), _key(str(player)), str(position).casefold(), str(team).casefold()


def _same_player(left: object, right: object) -> bool:
    lid, *lfallback = _identity(left)
    rid, *rfallback = _identity(right)
    return lid == rid if lid and rid else lfallback == rfallback


def incremental_import(picks: Iterable[DraftPick], existing: Iterable[object]) -> ImportResult:
    """Reconcile existing and incoming picks with one accepted record per number."""
    parsed = sorted(picks, key=lambda pick: pick.overall_pick)
    by_number: dict[int, object] = {}
    for entry in existing:
        number = getattr(entry, "overall_pick", getattr(entry, "pick", None))
        if number is None and isinstance(entry, dict):
            number = entry.get("overall_pick", entry.get("pick"))
        if number is not None:
            by_number[int(number)] = entry
    accepted: dict[int, DraftPick] = {}
    new: list[DraftPick] = []
    conflicts: list[DraftPick] = []
    unchanged: list[DraftPick] = []
    conflicted_numbers: set[int] = set()
    for pick in parsed:
        number = pick.overall_pick
        if number in conflicted_numbers:
            pick.needs_review = True
            pick.review_reasons.append("duplicate incoming pick conflicts")
            conflicts.append(pick)
            continue
        old = by_number.get(number)
        if old is not None:
            if _same_player(old, pick):
                unchanged.append(pick)
            else:
                pick.needs_review = True
                pick.review_reasons.append("pick conflicts with draft log")
                conflicts.append(pick)
            continue
        prior = accepted.get(number)
        if prior is None:
            accepted[number] = pick
            new.append(pick)
        elif _same_player(prior, pick):
            unchanged.append(pick)
        else:
            prior.needs_review = pick.needs_review = True
            reason = "duplicate incoming pick conflicts"
            prior.review_reasons.append(reason); pick.review_reasons.append(reason)
            new.remove(prior)
            accepted.pop(number)
            conflicted_numbers.add(number)
            conflicts.extend([prior, pick])
    return ImportResult(parsed, new, conflicts, unchanged)


# Short aliases for integrations which do not need to mention Yahoo explicitly.
parse_clipboard = parse_yahoo_clipboard
reconcile_draft_log = incremental_import


# Plain-list compatibility API. Structured Yahoo imports must use the functions above.
def normalize_name(value: str) -> str:
    import unicodedata
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    value = value.replace("\'", "").replace(".", "").replace("-", " ")
    return " ".join(word for word in re.findall(r"[a-z0-9]+", value) if word not in {"jr", "sr", "ii", "iii"})

def parse_pasted_picks(text: str, starting_pick: int = 1) -> list[dict]:
    records = []
    for offset, line in enumerate(line for line in text.splitlines() if line.strip()):
        match = re.match(r"^(?:pick\s*)?(\d+)\s*(?:[.)#:\-]\s*|\s+)(.*)$", line.strip(), re.I)
        pick, name = (int(match.group(1)), match.group(2).strip()) if match else (starting_pick + offset, line.strip())
        records.append({"pick": pick, "raw_name": name, "position": "", "team": "", "fantasy_team": "", "yahoo_team_id": "", "raw": line.strip()})
    return records

def match_player(name: str, players: Iterable[PlayerLike]):
    from difflib import SequenceMatcher
    normalized = normalize_name(name); candidates = list(players)
    exact = [p for p in candidates if normalize_name(p.player) == normalized]
    if len(exact) == 1: return exact[0], "Exact", "Ready"
    if len(exact) > 1: return None, "Ambiguous", "Ambiguous name"
    scores = sorted(((SequenceMatcher(None, normalized, normalize_name(p.player)).ratio(), p) for p in candidates), key=lambda x:x[0], reverse=True)
    if not scores or scores[0][0] < .78: return None, "Low", "Unmatched name"
    if len(scores)>1 and scores[0][0]-scores[1][0] < .10: return None, "Ambiguous", "Ambiguous name"
    return scores[0][1], "Fuzzy", "Ready"
