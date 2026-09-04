"""Deterministic, explainable recommendations for a standard fantasy draft.

Ranks are market inputs (lower is better); component scores are 0--100 (higher
is better).  Manual CSV labels are deliberately not read by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Protocol


SCORING_WEIGHTS = {
    "expert": 0.35,
    "consensus": 0.25,
    "adp_value": 0.15,
    "situation": 0.15,
    "roster_fit": 0.10,
}


@dataclass(frozen=True)
class Expert:
    name: str
    accuracy_weight: float = 1.0
    position_weights: Mapping[str, float] = field(default_factory=dict)

    def weight_for(self, position: str) -> float:
        return max(0.0, self.accuracy_weight * self.position_weights.get(position, 1.0))


@dataclass(frozen=True)
class ExpertOpinion:
    expert: Expert
    rank: float


class PlayerLike(Protocol):
    player: str
    position: str
    rank: float | None
    adp: float | None
    ecr: float | None
    projection: float | None
    role_score: float | None
    opportunity_score: float | None
    risk_score: float | None
    expert_count: int | None
    expert_weighted_rank: float | None
    expert_rankings: Mapping[str, float]


@dataclass(frozen=True)
class Recommendation:
    expert_score: float
    consensus_score: float
    adp_value_score: float
    situation_score: float
    roster_fit_score: float
    final_score: int
    model_label: str
    positive_experts: int
    negative_experts: int
    expert_count: int
    weighted_rank: float | None
    explanation: str


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _market_rank(player: PlayerLike) -> float:
    return player.adp or player.ecr or player.rank or 150.0


def standard_scoring_adjustment(position: str, *, rushing_volume: float = 0,
                                goal_line: float = 0, touchdown_equity: float = 0,
                                deep_upside: float = 0, reception_dependency: float = 0) -> float:
    """Return a bounded standard-vs-PPR adjustment from explicit 0--1 traits."""
    positive = 5 * rushing_volume + 5 * goal_line + 4 * touchdown_equity
    if position == "WR":
        positive += 4 * deep_upside
    penalty = 6 * reception_dependency if position in {"RB", "WR"} else 0
    return max(-8.0, min(10.0, positive - penalty))


def roster_fit_score(position: str, roster: Iterable[PlayerLike], current_pick: int,
                     value_edge: float = 0) -> float:
    counts = {p: 0 for p in ("QB", "RB", "WR", "TE")}
    for player in roster:
        counts[player.position] = counts.get(player.position, 0) + 1
    score = 55.0
    if position == "QB":
        # Ten starters leave usable replacement QBs; prevent early expert-rank reaches.
        score = 18.0 if current_pick < 50 else (52.0 if counts["QB"] == 0 else 20.0)
    elif position == "WR":
        score += 14 if counts["RB"] >= 3 and counts["WR"] < 2 else 0
        score += 5 if counts["WR"] < counts["RB"] else 0
    elif position == "RB":
        score -= 12 if counts["RB"] >= 3 and counts["WR"] < 2 else 0
    elif position == "TE":
        score += 10 if counts["TE"] == 0 and value_edge >= 12 else 0
        score -= 18 if counts["TE"] else 0
    return _clamp(score)


def evaluate_player(player: PlayerLike, roster: Iterable[PlayerLike] = (), current_pick: int = 1,
                    experts: Mapping[str, Expert] | None = None) -> Recommendation:
    experts = experts or {}
    opinions: list[ExpertOpinion] = []
    for name, rank in getattr(player, "expert_rankings", {}).items():
        opinions.append(ExpertOpinion(experts.get(name, Expert(name)), rank))

    weighted_rank = getattr(player, "expert_weighted_rank", None)
    if opinions:
        denominator = sum(o.expert.weight_for(player.position) for o in opinions)
        if denominator:
            weighted_rank = sum(o.rank * o.expert.weight_for(player.position) for o in opinions) / denominator
    count = len(opinions) or (getattr(player, "expert_count", None) or 0)
    market = _market_rank(player)
    threshold = max(3.0, market * .10)
    positives = sum(o.rank <= market - threshold for o in opinions)
    negatives = sum(o.rank >= market + threshold for o in opinions)
    # Aggregated imports preserve corroboration count, without pretending to know each name.
    if not opinions and count >= 2 and weighted_rank is not None:
        positives = count if weighted_rank <= market - threshold else 0
        negatives = count if weighted_rank >= market + threshold else 0

    expert_basis = weighted_rank or player.ecr or player.rank or market
    expert_score = _clamp(60 + (market - expert_basis) * 2) if count else 50.0
    consensus_basis = player.ecr or player.rank or market
    consensus_score = _clamp(60 + (market - consensus_basis) * 1.5)
    value_basis = weighted_rank or player.ecr or player.rank or market
    value_edge = market - value_basis
    adp_score = _clamp(50 + value_edge * 3)
    role = player.role_score if player.role_score is not None else 50.0
    opportunity = player.opportunity_score if player.opportunity_score is not None else 50.0
    risk = player.risk_score if player.risk_score is not None else 50.0
    situation = _clamp(.45 * role + .45 * opportunity + .10 * (100 - risk))
    fit = roster_fit_score(player.position, roster, current_pick, value_edge)
    final = round(sum({"expert": expert_score, "consensus": consensus_score,
                       "adp_value": adp_score, "situation": situation,
                       "roster_fit": fit}[key] * weight for key, weight in SCORING_WEIGHTS.items()))

    disagreement = positives and negatives
    contradiction = consensus_score < 35 or situation < 35
    obvious_early = market <= 36
    if positives >= 2 and not contradiction and not disagreement:
        label = "Sleeper" if value_edge >= 12 and not obvious_early else "Target"
    elif negatives >= 2 and (value_edge <= -8 or situation < 40):
        label = "Fade"
    else:
        label = "Neutral"

    reasons = []
    if positives >= 2:
        reasons.append("Multiple historically accurate experts rank this player above market")
    elif disagreement:
        reasons.append("Expert evidence is divided")
    elif count < 2:
        reasons.append("The expert sample is not yet large enough for a strong label")
    if value_edge >= 8:
        reasons.append("the market price offers strong value")
    elif value_edge <= -8:
        reasons.append("ADP is expensive relative to weighted value")
    if situation >= 65:
        reasons.append("role and opportunity are favorable for standard scoring")
    if player.position == "QB" and current_pick < 50:
        reasons.append("QB replacement value argues against an early reach in this format")
    explanation = ". ".join(reason[0].upper() + reason[1:] for reason in reasons[:3]) + "."
    return Recommendation(expert_score, consensus_score, adp_score, situation, fit, final,
                          label, positives, negatives, count, weighted_rank, explanation)


def rank_recommendations(players: Iterable[PlayerLike], drafted_ids: set[str], roster=(),
                         current_pick: int = 1, experts: Mapping[str, Expert] | None = None):
    results = [(p, evaluate_player(p, roster, current_pick, experts))
               for p in players if p.id not in drafted_ids]
    return sorted(results, key=lambda item: (-item[1].final_score, item[0].rank or 9999))
