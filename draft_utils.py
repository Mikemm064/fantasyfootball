"""Pure draft timing, ownership, and state-transition helpers."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


DEFAULT_LEAGUE_SETTINGS = {
    "season": 2026,
    "league_name": "Party on Pearl Street",
    "yahoo_league_id": "557989",
    "my_team_name": "Sippin' On Jeanty Juice",
    "yahoo_team_id": "6",
    "teams": 10,
    "draft_slot": 3,
    "draft_type": "Snake",
    "scoring": "Standard / Non-PPR",
    "qb_format": "1 QB",
}


def snake_picks(teams: int = 10, slot: int = 3, rounds: int = 20) -> list[int]:
    """Return a team's overall picks in a snake draft."""
    if teams < 2 or not 1 <= slot <= teams or rounds < 1:
        raise ValueError("teams, slot, and rounds must describe a valid draft")
    return [(r - 1) * teams + (slot if r % 2 else teams - slot + 1)
            for r in range(1, rounds + 1)]


def pick_context(current_pick: int, teams: int = 10) -> tuple[int, int]:
    """Return (round, drafting slot) for an overall pick."""
    if current_pick < 1:
        raise ValueError("current_pick must be positive")
    round_number = (current_pick - 1) // teams + 1
    within_round = (current_pick - 1) % teams + 1
    slot = within_round if round_number % 2 else teams - within_round + 1
    return round_number, slot


def next_user_pick(current_pick: int, teams: int = 10, slot: int = 3,
                   rounds: int = 30) -> int | None:
    return next((pick for pick in snake_picks(teams, slot, rounds) if pick >= current_pick), None)


def identify_ownership(*, pick: int | None, fantasy_team: str | None,
                       yahoo_team_id: str | None, settings: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Resolve independent ownership signals without guessing through conflicts.

    Returns ``YOUR PICK``, ``Opponent``, or ``REVIEW`` plus the matching signals.
    Empty imported identifiers are neutral rather than opponent evidence.
    """
    positives: list[str] = []
    negatives: list[str] = []
    teams, slot = int(settings["teams"]), int(settings["draft_slot"])
    if pick is not None:
        (positives if pick in snake_picks(teams, slot, max(30, pick // teams + 2)) else negatives).append("pick")
    if fantasy_team and fantasy_team.strip():
        (positives if fantasy_team.strip().casefold() == str(settings["my_team_name"]).strip().casefold()
         else negatives).append("team name")
    if yahoo_team_id is not None and str(yahoo_team_id).strip():
        (positives if str(yahoo_team_id).strip() == str(settings["yahoo_team_id"]).strip()
         else negatives).append("team id")
    if positives and negatives:
        return "REVIEW", positives
    if positives:
        return "YOUR PICK", positives
    return "Opponent", []


def record_pick(log: list[dict[str, Any]], player_id: str, *, pick: int | None = None,
                mine: bool = False, batch_id: str | None = None,
                source: str = "manual") -> bool:
    """Append a unique selection. Returns False without mutation for duplicates."""
    if any(entry["player_id"] == player_id for entry in log):
        return False
    assigned = pick if pick is not None else (max((e["pick"] for e in log), default=0) + 1)
    if any(entry["pick"] == assigned for entry in log):
        return False
    log.append({"player_id": player_id, "pick": int(assigned), "mine": bool(mine),
                "batch_id": batch_id, "source": source})
    log.sort(key=lambda entry: entry["pick"])
    return True


def current_overall_pick(log: Iterable[Mapping[str, Any]]) -> int:
    """First unrecorded overall pick, robust to catch-up imports with gaps."""
    used = {int(entry["pick"]) for entry in log}
    current = 1
    while current in used:
        current += 1
    return current


def export_state(settings: Mapping[str, Any], players: Iterable[Mapping[str, Any]],
                 draft_log: Iterable[Mapping[str, Any]], manual_labels: Mapping[str, Any] | None = None) -> str:
    return json.dumps({"schema_version": 1, "league_settings": dict(settings),
                       "players": list(players), "draft_log": list(draft_log),
                       "manual_labels": dict(manual_labels or {})}, indent=2, sort_keys=True)


def restore_state(content: str) -> dict[str, Any]:
    payload = json.loads(content)
    if payload.get("schema_version") != 1 or not isinstance(payload.get("players"), list):
        raise ValueError("Unsupported or invalid draft-state file")
    if not isinstance(payload.get("draft_log"), list) or not isinstance(payload.get("league_settings"), dict):
        raise ValueError("Draft-state file is incomplete")
    ids = {player.get("id") for player in payload["players"]}
    seen_players, seen_picks = set(), set()
    for entry in payload["draft_log"]:
        if entry.get("player_id") not in ids or entry.get("player_id") in seen_players:
            raise ValueError("Draft-state log contains an unknown or duplicate player")
        pick = entry.get("pick")
        if not isinstance(pick, int) or pick < 1 or pick in seen_picks:
            raise ValueError("Draft-state log contains an invalid or duplicate pick")
        seen_players.add(entry["player_id"]); seen_picks.add(pick)
    return payload


def draft_timing(*, current_pick: int, next_pick: int | None, adp: float | None,
                 rank: float | None, position: str, model_label: str = "Neutral") -> tuple[str, bool, str]:
    if next_pick is None:
        return "FAIR VALUE", False, "No later user pick is scheduled."
    gap = max(0, next_pick - current_pick)
    market = adp or rank or current_pick
    cushion = 3 if position in {"QB", "TE"} else 1
    likely_return = market >= next_pick + cushion
    if model_label == "Fade" and market < current_pick + max(3, gap * .4):
        action = "FADE AT THIS PRICE"
    elif likely_return:
        action = "WAIT"
    elif model_label in {"Target", "Sleeper"} and market <= next_pick + max(2, gap * .25):
        action = "TAKE NOW"
    elif market > current_pick + max(4, gap * .55):
        action = "LIKELY TO RETURN"
    else:
        action = "FAIR VALUE"
    delta = market - next_pick
    probability = ("Very likely to return" if delta >= 18 else "Likely to return" if likely_return
                   else "Very unlikely to return" if delta <= -12 else "Unlikely to return" if delta <= -3
                   else "Toss-up")
    return action, likely_return, f"{probability} to pick {next_pick}"
