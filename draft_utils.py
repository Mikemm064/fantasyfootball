"""Snake-draft timing utilities, kept independent of Streamlit."""

from __future__ import annotations


def snake_picks(teams: int = 10, slot: int = 3, rounds: int = 20) -> list[int]:
    return [(r - 1) * teams + (slot if r % 2 else teams - slot + 1)
            for r in range(1, rounds + 1)]


def next_user_pick(current_pick: int, teams: int = 10, slot: int = 3) -> int | None:
    return next((pick for pick in snake_picks(teams, slot) if pick >= current_pick), None)


def draft_timing(*, current_pick: int, next_pick: int | None, adp: float | None,
                 rank: float | None, position: str, model_label: str = "Neutral") -> tuple[str, bool, str]:
    """Return action, survival estimate and a concise deterministic explanation."""
    if next_pick is None:
        return "FAIR VALUE", False, "No later user pick is scheduled."
    gap = max(0, next_pick - current_pick)
    market = adp or rank or current_pick
    # QB/TE runs are less predictable, so require an extra cushion to wait.
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
    text = (f"Likely available at pick {next_pick}" if likely_return
            else f"Unlikely to survive to pick {next_pick}")
    return action, likely_return, text
