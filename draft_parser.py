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
    for pick in picks:
        _set_ownership(pick, teams, my_team_name, str(yahoo_team_id), draft_slot)
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
                                   position, lines[i + 3].upper()))
    return picks


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _set_ownership(pick: DraftPick, teams: int, team_name: str,
                   team_id: str, draft_slot: int) -> None:
    manager = _key(pick.fantasy_team)
    signals = [
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
    explicit_other = bool(manager) and manager != "yourteam" and not any(
        yes for yes, _, _ in signals[1:3])
    if explicit_other and signals[-1][0]:
        pick.needs_review = True
        pick.review_reasons.append("ownership signals conflict")
    elif any(yes for yes, _, _ in signals[:3]) and not signals[-1][0]:
        pick.needs_review = True
        pick.review_reasons.append("ownership signals conflict")


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


def incremental_import(picks: Iterable[DraftPick], existing: Iterable[object]) -> ImportResult:
    """Return unseen selections and conflicts, never duplicates."""
    parsed = sorted(picks, key=lambda pick: pick.overall_pick)
    by_number: dict[int, object] = {}
    for entry in existing:
        number = getattr(entry, "overall_pick", getattr(entry, "pick", None))
        if number is None and isinstance(entry, dict):
            number = entry.get("overall_pick", entry.get("pick"))
        if number is not None:
            by_number[int(number)] = entry
    new, conflicts = [], []
    for pick in parsed:
        old = by_number.get(pick.overall_pick)
        if old is None:
            new.append(pick)
            continue
        old_player = (old.get("player") if isinstance(old, dict) else getattr(old, "player", ""))
        if hasattr(old_player, "player"):
            old_player = old_player.player
        current = pick.matched_player.player if pick.matched_player else pick.player_name
        if _key(str(old_player)) != _key(current):
            pick.needs_review = True
            pick.review_reasons.append("pick conflicts with draft log")
            conflicts.append(pick)
    return ImportResult(parsed, new, conflicts)


# Short aliases for integrations which do not need to mention Yahoo explicitly.
parse_clipboard = parse_yahoo_clipboard
reconcile_draft_log = incremental_import
