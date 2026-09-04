"""Native Streamlit fantasy-football draft board.

Milestone 1 deliberately keeps the draft manual: all active state lives in the
Streamlit session and no external service or custom web server is used.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
from dataclasses import dataclass, field
from typing import Any

import streamlit as st

import yahoo_auth
from draft_utils import draft_timing, next_user_pick, snake_picks
from recommendation_engine import rank_recommendations


TEAMS = 10
MY_SLOT = 3
POSITIONS = ("ALL", "RB", "WR", "QB", "TE")
PLAYER_POSITIONS = set(POSITIONS[1:])

DEFAULT_CSV = """Player,Position,Team,Overall Rank,ADP,Expert Consensus Rank,Target,Sleeper,Fade,Drafted
Ja'Marr Chase,WR,CIN,1,1.4,1,Yes,,,No
Bijan Robinson,RB,ATL,2,2.1,2,Yes,,,No
Jahmyr Gibbs,RB,DET,3,3.2,3,Yes,,,No
Justin Jefferson,WR,MIN,4,4.8,4,,,,No
CeeDee Lamb,WR,DAL,5,5.3,5,,,,No
Puka Nacua,WR,LAR,6,7.1,6,Yes,,,No
Saquon Barkley,RB,PHI,7,6.8,7,,,,No
Amon-Ra St. Brown,WR,DET,8,8.2,8,,,,No
Josh Allen,QB,BUF,9,18.0,10,,,,No
Brock Bowers,TE,LV,10,13.4,9,Yes,,,No
Lamar Jackson,QB,BAL,11,21.0,12,,,,No
Trey McBride,TE,ARI,12,20.1,11,,Yes,,No
Malik Nabers,WR,NYG,13,12.4,13,,Yes,,No
De'Von Achane,RB,MIA,14,15.7,14,,,Yes,No
"""


@dataclass(frozen=True)
class Player:
    id: str
    player: str
    position: str
    team: str
    rank: float | None
    adp: float | None
    ecr: float | None
    target: bool
    sleeper: bool
    fade: bool
    drafted: bool = False
    projection: float | None = None
    role_score: float | None = None
    opportunity_score: float | None = None
    risk_score: float | None = None
    expert_count: int | None = None
    expert_weighted_rank: float | None = None
    imported_recommendation_score: float | None = None
    imported_recommendation_label: str = ""
    notes: str = ""
    expert_rankings: dict[str, float] = field(default_factory=dict)


def stable_player_id(player: str, position: str, team: str) -> str:
    """Create a deterministic, CSV-order-independent player identifier."""
    identity = "|".join((player.strip(), position.strip(), team.strip())).casefold()
    return f"p_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"


def _number(value: str | None) -> float | None:
    try:
        number = float((value or "").strip())
        return number if number > 0 else None
    except ValueError:
        return None


def _truthy(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"true", "yes", "y", "1", "x"}


def parse_rankings_csv(content: str) -> list[Player]:
    """Parse supported ranking columns, ignoring rows without a valid position."""
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    if not reader.fieldnames:
        return []
    headers = {"".join(c for c in name.casefold() if c.isalnum()): name for name in reader.fieldnames}

    def value(row: dict[str, str], *aliases: str) -> str:
        for alias in aliases:
            if alias in headers:
                return row.get(headers[alias], "") or ""
        return ""

    players: list[tuple[int, Player]] = []
    seen: set[str] = set()
    for source_order, row in enumerate(reader):
        name = value(row, "player", "playername", "name").strip()
        position = value(row, "position", "pos").strip().upper()
        team = value(row, "team", "nflteam").strip().upper()
        if not name or position not in PLAYER_POSITIONS:
            continue
        player_id = stable_player_id(name, position, team)
        if player_id in seen:
            continue
        seen.add(player_id)
        players.append((source_order, Player(
            id=player_id, player=name, position=position, team=team,
            rank=_number(value(row, "overallrank", "rank", "overall")),
            adp=_number(value(row, "adp")),
            ecr=_number(value(row, "expertconsensusrank", "ecr")),
            target=_truthy(value(row, "target")),
            sleeper=_truthy(value(row, "sleeper")),
            fade=_truthy(value(row, "fade")),
            drafted=_truthy(value(row, "drafted")),
            projection=_number(value(row, "projection")),
            role_score=_number(value(row, "rolescore")),
            opportunity_score=_number(value(row, "opportunityscore")),
            risk_score=_number(value(row, "riskscore")),
            expert_count=int(_number(value(row, "expertcount")) or 0) or None,
            expert_weighted_rank=_number(value(row, "expertweightedrank")),
            imported_recommendation_score=_number(value(row, "recommendationscore")),
            imported_recommendation_label=value(row, "recommendationlabel").strip(),
            notes=value(row, "notes").strip(),
            expert_rankings={name[len("expertrank"):].strip(" :_-"): number
                             for normalized, name in headers.items()
                             if normalized.startswith("expertrank")
                             and (number := _number(row.get(name))) is not None},
        )))
    return [item[1] for item in sorted(players, key=lambda item: (item[1].rank or 9999, item[0]))]


def initial_draft(players: list[Player]) -> list[dict[str, Any]]:
    return [
        {"player": player, "pick": pick, "mine": False}
        for pick, player in enumerate((p for p in players if p.drafted), start=1)
    ]


def initialize_state() -> None:
    if "players" not in st.session_state:
        players = parse_rankings_csv(DEFAULT_CSV)
        st.session_state.players = players
        st.session_state.draft_log = initial_draft(players)
        st.session_state.upload_token = None


def draft_player(player_id: str, mine: bool) -> None:
    drafted_ids = {entry["player"].id for entry in st.session_state.draft_log}
    player = next((p for p in st.session_state.players if p.id == player_id), None)
    if player and player.id not in drafted_ids:
        st.session_state.draft_log.append({
            "player": player,
            "pick": len(st.session_state.draft_log) + 1,
            "mine": mine,
        })


def undo_last() -> None:
    if st.session_state.draft_log:
        st.session_state.draft_log.pop()


def _format_number(value: float | None) -> str:
    if value is None:
        return "—"
    return str(int(value)) if value.is_integer() else str(value)


def _inject_styles() -> None:
    st.markdown("""
    <style>
    .stApp {background:#f4f5ef;color:#14231e}
    [data-testid="stHeader"] {background:#102a22}
    .hero {background:#102a22;color:white;border-bottom:4px solid #dafa78;
      padding:1.5rem 2rem;border-radius:.7rem;margin-bottom:1rem}
    .hero h1 {font-family:Georgia,serif;margin:.15rem 0;font-size:2rem}
    .eyebrow {color:#9bb4aa;font-size:.68rem;font-weight:800;letter-spacing:.13rem}
    .player-card {background:white;border:1px solid #dfe4dc;border-radius:.55rem;
      padding:.65rem .8rem;min-height:4.4rem}
    .player-card strong {font-size:1rem}.muted {color:#68766f;font-size:.78rem}
    .tag {font-size:.65rem;font-weight:800;text-transform:uppercase;padding:.2rem .35rem;
      border-radius:.25rem;background:#edf0eb;margin-right:.25rem}
    .target {background:#dff2e4;color:#17623d}.sleeper {background:#e2ecf8;color:#315575}
    .fade {background:#f7ded9;color:#a34436}
    div[data-testid="stMetric"] {background:#115c43;border-radius:.6rem;padding:.65rem 1rem}
    div[data-testid="stMetric"] label, div[data-testid="stMetric"] div {color:white}
    div[data-testid="stButton"] button[kind="primary"] {background:#115c43;border-color:#115c43}
    </style>
    """, unsafe_allow_html=True)


def _query_value(name: str) -> str | None:
    """Read one callback parameter across supported Streamlit query APIs."""
    value = st.query_params.get(name)
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value is not None else None


def render_yahoo_auth() -> None:
    """Render and process Yahoo OAuth without exposing token data to the client."""
    try:
        credentials = yahoo_auth.credentials_from_secrets(st.secrets)
    except yahoo_auth.YahooAuthError:
        st.write("Yahoo not connected")
        st.caption("Configure Yahoo OAuth credentials in Streamlit Secrets to connect.")
        return

    code = _query_value("code")
    returned_state = _query_value("state")
    oauth_error = _query_value("error")
    if any(value is not None for value in (code, returned_state, oauth_error)):
        # Callback values, especially single-use codes, must not survive a refresh.
        st.query_params.clear()
    if oauth_error:
        st.error("Yahoo authentication was not completed. Please try again.")
    elif code:
        if not yahoo_auth.validate_signed_state(credentials, returned_state):
            st.session_state.pop("yahoo_token", None)
            st.session_state.pop("yahoo_verified", None)
            st.error(
                "Yahoo authentication could not be verified. The callback state was "
                "invalid or expired; please try again."
            )
        else:
            try:
                st.session_state.yahoo_token = yahoo_auth.exchange_code(credentials, code)
            except yahoo_auth.YahooAuthError as exc:
                st.session_state.pop("yahoo_token", None)
                st.session_state.pop("yahoo_verified", None)
                st.error(str(exc))
            else:
                try:
                    st.session_state.yahoo_verified = yahoo_auth.verify_fantasy_access(
                        credentials, st.session_state
                    )
                except yahoo_auth.YahooAuthError as exc:
                    st.session_state.yahoo_verified = False
                    st.error(str(exc))
                else:
                    st.rerun()

    if "yahoo_token" in st.session_state:
        try:
            yahoo_auth.ensure_fresh_token(credentials, st.session_state)
        except yahoo_auth.YahooAuthError as exc:
            st.session_state.pop("yahoo_token", None)
            st.session_state.pop("yahoo_verified", None)
            st.error(str(exc))

    if "yahoo_token" in st.session_state:
        st.write("🟢 Yahoo Connected")
        if st.session_state.get("yahoo_verified"):
            st.success("Yahoo Fantasy connection verified.")
        if st.button("Disconnect Yahoo"):
            for key in ("yahoo_token", "yahoo_verified"):
                st.session_state.pop(key, None)
            st.rerun()
    else:
        st.write("Yahoo not connected")
        st.link_button(
            "Connect Yahoo",
            yahoo_auth.authorization_url(credentials, yahoo_auth.new_signed_state(credentials)),
        )


def main() -> None:
    st.set_page_config(page_title="Fantasy Draft Assistant", page_icon="🏈", layout="wide")
    _inject_styles()
    initialize_state()

    st.markdown('<div class="hero"><span class="eyebrow">2026 · STANDARD · 10 TEAMS</span>'
                '<h1>Fantasy Draft Assistant</h1><span>Manual draft board · Team 3</span></div>',
                unsafe_allow_html=True)

    render_yahoo_auth()
    st.divider()

    uploaded = st.file_uploader("Import rankings CSV", type=["csv"],
                                help="Importing replaces the board and resets draft progress.")
    if uploaded is not None:
        content = uploaded.getvalue()
        token = hashlib.sha256(content).hexdigest()
        if token != st.session_state.upload_token:
            players = parse_rankings_csv(content.decode("utf-8-sig", errors="replace"))
            if players:
                st.session_state.players = players
                st.session_state.draft_log = initial_draft(players)
                st.session_state.upload_token = token
                st.success(f"Imported {len(players)} players from {uploaded.name}.")
            else:
                st.error("No valid players found. Include Player and Position (RB, WR, QB, or TE).")

    current_pick = len(st.session_state.draft_log) + 1
    future_picks = [pick for pick in snake_picks() if pick >= current_pick]
    next_pick = next_user_pick(current_pick)
    metrics = st.columns([1, 1, 1, 2])
    metrics[0].metric("CURRENT OVERALL PICK", current_pick)
    metrics[1].metric("PICKS UNTIL YOUR TURN", max(0, next_pick - current_pick) if next_pick else "—")
    metrics[2].metric("YOUR NEXT PICK", next_pick or "—")
    metrics[3].metric("YOUR PICK PATH", " · ".join(map(str, future_picks[:5])) or "Draft complete")

    drafted_ids = {entry["player"].id for entry in st.session_state.draft_log}
    roster = [entry["player"] for entry in st.session_state.draft_log if entry["mine"]]
    available = [p for p in st.session_state.players if p.id not in drafted_ids]
    board, sidebar = st.columns([2.25, 1], gap="large")
    with board:
        st.subheader("Top 5 Recommendations")
        recommendations = rank_recommendations(
            st.session_state.players, drafted_ids, roster, current_pick
        )[:5]
        if not recommendations:
            st.info("No available players to recommend.")
        for recommendation_rank, (player, result) in enumerate(recommendations, 1):
            action, likely_return, survival = draft_timing(
                current_pick=current_pick, next_pick=next_pick, adp=player.adp,
                rank=player.rank, position=player.position, model_label=result.model_label,
            )
            manual = next((label for enabled, label in (
                (player.target, "Target"), (player.sleeper, "Sleeper"), (player.fade, "Fade")
            ) if enabled), None)
            labels = f"Model: {result.model_label}"
            if manual:
                labels += f" · Manual: {manual}"
            value_basis = result.weighted_rank or player.ecr or player.rank
            value = (player.adp - value_basis) if player.adp and value_basis else None
            value_text = f"{value:+.0f} value vs ADP" if value is not None else "Value unavailable"
            safe = html.escape(player.player)
            explanation = result.explanation
            if likely_return:
                explanation += " Strong value may still remain at the next selection."
            st.markdown(
                f'<div class="player-card"><strong>{recommendation_rank}. {safe} — '
                f'{player.position} · {html.escape(player.team)} — {result.final_score}/100</strong><br>'
                f'<span class="tag {result.model_label.casefold()}">{html.escape(labels)}</span> '
                f'<span class="tag">{action}</span><br><span class="muted">ADP '
                f'{_format_number(player.adp)} · ECR {_format_number(player.ecr)} · {value_text} · '
                f'{survival}</span><br><span class="muted">{html.escape(explanation)}</span></div>',
                unsafe_allow_html=True,
            )
            with st.expander(f"Why {player.player}?", expanded=False):
                st.write({"Expert Score": round(result.expert_score),
                          "Consensus Score": round(result.consensus_score),
                          "ADP Value Score": round(result.adp_value_score),
                          "Situation Score": round(result.situation_score),
                          "Roster Fit Score": round(result.roster_fit_score)})

        st.subheader("Best available")
        filters, search = st.columns([1.2, 2])
        position = filters.segmented_control("Position", POSITIONS, default="ALL", key="position_filter")
        query = search.text_input("Player search", placeholder="Search player or team").strip().casefold()
        shown = [p for p in available if (position == "ALL" or p.position == position)
                 and (not query or query in f"{p.player} {p.team}".casefold())]
        st.caption(f"{len(available)} available")
        if not shown:
            st.info("No available players match these filters.")
        for player in shown:
            info, drafted_col, mine_col = st.columns([6, 1.35, 1.25], vertical_alignment="center")
            badges = "".join(
                f'<span class="tag {css}">{label}</span>'
                for enabled, label, css in ((player.target, "Target", "target"),
                                             (player.sleeper, "Sleeper", "sleeper"),
                                             (player.fade, "Fade", "fade")) if enabled
            ) or '<span class="tag">Neutral</span>'
            safe_name = html.escape(player.player)
            safe_team = html.escape(player.team)
            info.markdown(
                f'<div class="player-card"><strong>#{_format_number(player.rank)} &nbsp; '
                f'{safe_name}</strong><br><span class="muted">{player.position} · {safe_team} '
                f'&nbsp; ADP {_format_number(player.adp)} · ECR {_format_number(player.ecr)}</span><br>{badges}</div>',
                unsafe_allow_html=True,
            )
            if drafted_col.button("Drafted", key=f"draft_{player.id}", use_container_width=True):
                draft_player(player.id, False)
                st.rerun()
            if mine_col.button("+ Mine", key=f"mine_{player.id}", type="primary", use_container_width=True):
                draft_player(player.id, True)
                st.rerun()

    with sidebar:
        roster_entries = [entry for entry in st.session_state.draft_log if entry["mine"]]
        st.subheader(f"My roster ({len(roster_entries)})")
        if roster_entries:
            for entry in roster_entries:
                player = entry["player"]
                st.markdown(f"**{player.position} · {html.escape(player.player)}**  \n"
                            f"<span class='muted'>{html.escape(player.team)} · Pick {entry['pick']}</span>",
                            unsafe_allow_html=True)
        else:
            st.caption('Use “+ Mine” when you make a pick.')

        st.divider()
        log_title, undo_col = st.columns([2, 1])
        log_title.subheader("Draft log")
        if undo_col.button("↶ Undo", disabled=not st.session_state.draft_log,
                           help="Undo the last draft action", use_container_width=True):
            undo_last()
            st.rerun()
        if st.session_state.draft_log:
            for entry in reversed(st.session_state.draft_log):
                player = entry["player"]
                mine = " · YOUR PICK" if entry["mine"] else ""
                st.markdown(f"**{entry['pick']}. {html.escape(player.player)}**  \n"
                            f"<span class='muted'>{player.position} · {html.escape(player.team)}{mine}</span>",
                            unsafe_allow_html=True)
        else:
            st.caption("No picks recorded yet.")
        if st.button("Reset draft", disabled=not st.session_state.draft_log):
            st.session_state.draft_log = []
            st.rerun()


if __name__ == "__main__":
    main()
