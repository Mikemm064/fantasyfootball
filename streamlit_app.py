"""Native Streamlit fantasy-football draft board.

Milestone 1 deliberately keeps the draft manual: all active state lives in the
Streamlit session and no external service or custom web server is used.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

import yahoo_auth
from draft_utils import draft_timing, next_user_pick, snake_picks
from recommendation_engine import rank_recommendations


TEAMS = 10
MY_SLOT = 3
POSITIONS = ("ALL", "RB", "WR", "QB", "TE")
PLAYER_POSITIONS = set(POSITIONS[1:])

DEFAULT_CSV = """Player,Position,Team,Draft Key,Overall Rank,ADP,Expert Consensus Rank,Target,Sleeper,Fade,Drafted
Ja'Marr Chase,WR,CIN,chase,1,1.4,1,Yes,,,No
Bijan Robinson,RB,ATL,,2,2.1,2,Yes,,,No
Jahmyr Gibbs,RB,DET,,3,3.2,3,Yes,,,No
Justin Jefferson,WR,MIN,,4,4.8,4,,,,No
CeeDee Lamb,WR,DAL,,5,5.3,5,,,,No
Puka Nacua,WR,LAR,,6,7.1,6,Yes,,,No
Saquon Barkley,RB,PHI,,7,6.8,7,,,,No
Amon-Ra St. Brown,WR,DET,,8,8.2,8,,,,No
Josh Allen,QB,BUF,,9,18.0,10,,,,No
Brock Bowers,TE,LV,,10,13.4,9,Yes,,,No
Lamar Jackson,QB,BAL,,11,21.0,12,,,,No
Trey McBride,TE,ARI,,12,20.1,11,,Yes,,No
Malik Nabers,WR,NYG,,13,12.4,13,,Yes,,No
De'Von Achane,RB,MIA,,14,15.7,14,,,Yes,No
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
    draft_key: str = ""
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


@dataclass(frozen=True)
class YahooPick:
    """One completed selection extracted from a Yahoo draft-board paste."""

    name: str
    position: str
    team: str
    round: int
    draft_slot: int
    overall_pick: int
    explicit_user_pick: bool = False
    yahoo_team_id: str | None = None


@dataclass(frozen=True)
class YahooBoard:
    """Ephemeral metadata and selections from a single clipboard snapshot."""

    team_count: int | None
    managers: dict[int, str]
    detected_user_slot: int | None
    picks: tuple[YahooPick, ...]
    current_round: int | None = None
    current_slot: int | None = None
    current_overall_pick: int | None = None

    @property
    def current_manager(self) -> str | None:
        return self.managers.get(self.current_slot) if self.current_slot else None


_PICK_SLOT = re.compile(r"^(\d+)\.(\d+)$")
_URL = re.compile(r"(?:https?://|data:image/)[^\s)>]+", re.I)
_NOISE = {"svg", "image", "img", "...", "…", "draft board", "yahoo draft board"}


def _clean_yahoo_lines(content: str) -> list[str]:
    """Remove image links/Markdown decoration without damaging player apostrophes."""
    content = re.sub(r"!\[[^]]*]\([^)]*\)", "\n", content)
    content = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", content)
    content = re.sub(r"<img\b[^>]*>", "\n", content, flags=re.I)
    lines: list[str] = []
    for raw in content.splitlines():
        line = _URL.sub("", raw).strip()
        line = re.sub(r"^\s{0,3}(?:[-*+]\s+|#{1,6}\s*)", "", line)
        line = re.sub(r"[*_`~]", "", line).strip(" \t|>")
        if line and line.casefold() not in _NOISE:
            lines.append(line)
    return lines


def yahoo_overall_pick(round_number: int, draft_slot: int, team_count: int) -> int:
    """Convert Yahoo's round/manager-column label to chronological pick number."""
    within_round = draft_slot if round_number % 2 else team_count - draft_slot + 1
    return (round_number - 1) * team_count + within_round


def parse_yahoo_draft_board(content: str) -> YahooBoard:
    """Parse a full Yahoo Draft Board clipboard snapshot.

    Yahoo repeats each manager display name in the header.  The special ``You``
    line occupies the repeated-name position and is deliberately retained as a
    stronger ownership signal than saved league settings.
    """
    lines = _clean_yahoo_lines(content)
    record_starts: list[int] = []
    for i in range(4, len(lines)):
        if (_PICK_SLOT.fullmatch(lines[i]) and lines[i - 2].upper() in PLAYER_POSITIONS
                and re.fullmatch(r"[A-Za-z]{2,4}", lines[i - 1])):
            record_starts.append(i - 4)
    header_end = min(record_starts) if record_starts else len(lines)
    header = lines[:header_end]

    managers: dict[int, str] = {}
    detected_user_slot = None
    i = 0
    while i < len(header):
        name = header[i]
        if i + 1 < len(header) and header[i + 1].casefold() == name.casefold():
            managers[len(managers) + 1] = name
            i += 2
        elif i + 1 < len(header) and header[i + 1].casefold() == "you":
            slot = len(managers) + 1
            managers[slot] = name
            detected_user_slot = slot
            i += 2
        else:
            # Presentation labels and orphaned image alt text are not managers.
            i += 1
    team_count = len(managers) or None

    current_round = current_slot = None
    picks: list[YahooPick] = []
    for i, line in enumerate(lines):
        slot_match = _PICK_SLOT.fullmatch(line)
        if not slot_match:
            continue
        round_number, draft_slot = map(int, slot_match.groups())
        if i and lines[i - 1].casefold() == "on the clock":
            current_round, current_slot = round_number, draft_slot
            continue
        if (i < 4 or lines[i - 2].upper() not in PLAYER_POSITIONS
                or not re.fullmatch(r"[A-Za-z]{2,4}", lines[i - 1])):
            continue  # A bare round.slot is a future pick, not a selection.
        if not team_count or not 1 <= draft_slot <= team_count:
            continue
        raw_context = lines[max(header_end, i - 6):i]
        context = [value.casefold() for value in raw_context]
        team_id_match = next((re.search(r"yahoo\s*team\s*id\s*[:=#-]?\s*([\w.-]+)", value, re.I)
                              for value in reversed(raw_context)
                              if re.search(r"yahoo\s*team\s*id", value, re.I)), None)
        picks.append(YahooPick(
            name=f"{lines[i - 4]} {lines[i - 3]}", position=lines[i - 2].upper(),
            team=lines[i - 1].upper(), round=round_number, draft_slot=draft_slot,
            overall_pick=yahoo_overall_pick(round_number, draft_slot, team_count),
            explicit_user_pick="your team" in context,
            yahoo_team_id=team_id_match.group(1) if team_id_match else None,
        ))
    current_overall = (yahoo_overall_pick(current_round, current_slot, team_count)
                       if current_round and current_slot and team_count else None)
    return YahooBoard(team_count, managers, detected_user_slot, tuple(picks),
                      current_round, current_slot, current_overall)


def yahoo_pick_is_mine(pick: YahooPick, board: YahooBoard, *, configured_slot: int,
                       fantasy_team_name: str = "", yahoo_team_id: str = "") -> bool:
    """Apply Yahoo clipboard ownership signals in descending precedence."""
    if board.detected_user_slot is not None:
        return pick.draft_slot == board.detected_user_slot
    if pick.explicit_user_pick:
        return True
    if yahoo_team_id and pick.yahoo_team_id == yahoo_team_id:
        return True
    if fantasy_team_name and board.managers.get(pick.draft_slot, "").casefold() == fantasy_team_name.casefold():
        return True
    return pick.draft_slot == configured_slot


def stable_player_id(player: str, position: str, team: str) -> str:
    """Create a deterministic, CSV-order-independent player identifier."""
    identity = "|".join((player.strip(), position.strip(), team.strip())).casefold()
    return f"p_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"


def _draft_key(name: str, team: str, used: set[str], supplied: str = "") -> str:
    """Return a short, unique, human-typeable key for an imported player."""
    base = supplied.strip() or "-".join(re.findall(r"[a-z0-9]+", name.casefold())[-2:])
    base = base or team.casefold() or "player"
    candidate, suffix = base, 2
    while candidate.casefold() in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate.casefold())
    return candidate


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
    used_keys: set[str] = set()
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
            draft_key=_draft_key(name, team, used_keys, value(row, "draftkey", "key")),
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


def draft_player(player_id: str, mine: bool, pick: int | None = None) -> None:
    drafted_ids = {entry["player"].id for entry in st.session_state.draft_log}
    player = next((p for p in st.session_state.players if p.id == player_id), None)
    if player and player.id not in drafted_ids:
        st.session_state.draft_log.append({
            "player": player,
            "pick": pick if pick is not None else len(st.session_state.draft_log) + 1,
            "mine": mine,
        })


def undo_last() -> None:
    if st.session_state.draft_log:
        st.session_state.draft_log.pop()


def player_search_score(player: Player, query: str) -> tuple[int, float, float]:
    """Rank partial name/team/key matches, with deterministic rank tie-breaking."""
    query = query.strip().casefold()
    name = player.player.casefold()
    last = name.split()[-1]
    team = player.team.casefold()
    key = player.draft_key.casefold()
    if not query:
        quality = 1
    elif query in {name, last, key}:
        quality = 100
    elif name.startswith(query) or last.startswith(query) or key.startswith(query):
        quality = 90
    elif query in name:
        quality = 80
    elif query in team or query in key:
        quality = 70
    else:
        quality = 0
    similarity = max(SequenceMatcher(None, query, name).ratio(),
                     SequenceMatcher(None, query, last).ratio()) if query else 0
    return quality, similarity, -(player.rank or 9999)


def match_pasted_name(name: str, available: list[Player]) -> tuple[Player | None, str]:
    """Conservatively fuzzy-match one pasted Yahoo name."""
    query = name.strip()
    if not query:
        return None, "unmatched"
    scored = sorted(((player_search_score(p, query), p) for p in available),
                    key=lambda item: item[0], reverse=True)
    if not scored:
        return None, "unmatched"
    best_score, best = scored[0]
    # Exact/partial matches are safe; fuzzy matches require a strong, clear lead.
    if best_score[0] >= 80:
        same_quality = [p for score, p in scored if score[:2] == best_score[:2]]
        return (best, "confirmed") if len(same_quality) == 1 else (None, "ambiguous")
    second_similarity = scored[1][0][1] if len(scored) > 1 else 0
    if best_score[1] >= .82 and best_score[1] - second_similarity >= .12:
        return best, "confirmed"
    return None, "ambiguous" if best_score[1] >= .6 else "unmatched"


def _keyboard_listener(focus_search: bool = False) -> None:
    """Progressive enhancement only: draft state remains in Python/button callbacks."""
    components.html(f"""<script>
    (() => {{
      const w = window.parent, d = w.document;
      const editable = e => e && (e.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(e.tagName));
      const findButton = label => [...d.querySelectorAll('button')].find(b => b.innerText.trim() === label);
      const search = () => d.querySelector('[aria-label="Quick Draft Search"]');
      if (!w.__quickDraftKeys) {{
        w.__quickDraftKeys = e => {{
          const inQuick = e.target === search();
          if (editable(e.target) && !inQuick) return;
          if ((e.key === '/' && !editable(e.target)) || (e.ctrlKey && e.key.toLowerCase() === 'k')) {{
            e.preventDefault(); search()?.focus(); return;
          }}
          if (inQuick && e.key === 'Enter') {{ setTimeout(() => search()?.blur(), 25); return; }}
          if (inQuick && e.key === 'Escape') return;
          if (editable(e.target)) return;
          const key = e.key.toLowerCase();
          const label = key === 'd' ? 'Draft selected' : key === 'm' ? 'Mine selected' : key === 'u' ? '↶ Undo' : '';
          if (label) {{ const b = findButton(label); if (b && !b.disabled) {{ e.preventDefault(); b.click(); }} }}
        }};
        w.addEventListener('keydown', w.__quickDraftKeys);
      }}
      if ({str(focus_search).lower()}) setTimeout(() => search()?.focus(), 50);
    }})();
    </script>""", height=0)


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

    paste_board: YahooBoard | None = st.session_state.get("yahoo_board")
    session_teams = paste_board.team_count if paste_board and paste_board.team_count else TEAMS
    session_slot = (paste_board.detected_user_slot
                    if paste_board and paste_board.detected_user_slot else MY_SLOT)
    current_pick = (paste_board.current_overall_pick if paste_board else None)
    current_pick = current_pick or len(st.session_state.draft_log) + 1
    future_picks = [pick for pick in snake_picks(session_teams, session_slot) if pick >= current_pick]
    next_pick = next_user_pick(current_pick, session_teams, session_slot)
    metrics = st.columns([1, 1, 1, 2, 1.5])
    metrics[0].metric("CURRENT OVERALL PICK", current_pick)
    metrics[1].metric("PICKS UNTIL YOUR TURN", max(0, next_pick - current_pick) if next_pick else "—")
    metrics[2].metric("YOUR NEXT PICK", next_pick or "—")
    metrics[3].metric("YOUR PICK PATH", " · ".join(map(str, future_picks[:5])) or "Draft complete")
    metrics[4].metric("ON THE CLOCK", paste_board.current_manager or "—" if paste_board else "—")

    drafted_ids = {entry["player"].id for entry in st.session_state.draft_log}
    roster = [entry["player"] for entry in st.session_state.draft_log if entry["mine"]]
    available = [p for p in st.session_state.players if p.id not in drafted_ids]

    st.subheader("Quick Draft Entry")
    st.caption("Type a player, last name, NFL team, or Draft Key. Enter selects; then D drafts or M adds to your roster.")
    quick_version = st.session_state.get("quick_version", 0)
    selected_id = st.selectbox(
        "Quick Draft Search",
        options=[p.id for p in available],
        index=None,
        key=f"quick_search_{quick_version}",
        placeholder="Search available players…  ( / or Ctrl+K )",
        format_func=lambda player_id: next(
            f"{p.player} — {p.position} · {p.team} · {p.draft_key}"
            for p in available if p.id == player_id
        ),
    )
    selected = next((p for p in available if p.id == selected_id), None)
    quick_drafted, quick_mine = st.columns(2)
    if quick_drafted.button("Draft selected", disabled=selected is None,
                            use_container_width=True, key="quick_drafted"):
        draft_player(selected.id, False)
        st.session_state.quick_version = quick_version + 1
        st.session_state.quick_refocus = True
        st.rerun()
    if quick_mine.button("Mine selected", disabled=selected is None, type="primary",
                         use_container_width=True, key="quick_mine"):
        draft_player(selected.id, True)
        st.session_state.quick_version = quick_version + 1
        st.session_state.quick_refocus = True
        st.rerun()
    _keyboard_listener(st.session_state.pop("quick_refocus", False))

    with st.expander("Paste Draft Picks"):
        paste_version = st.session_state.get("paste_version", 0)
        pasted = st.text_area("Yahoo Draft Board", key=f"pasted_names_{paste_version}",
                              placeholder="Paste the entire Yahoo Draft Board")
        if st.button("Preview", disabled=not pasted.strip(), key="preview_pasted"):
            st.session_state.yahoo_preview = parse_yahoo_draft_board(pasted)
        preview: YahooBoard | None = st.session_state.get("yahoo_preview")
        if preview and preview.team_count:
            user_text = (f" · You are Slot {preview.detected_user_slot}"
                         if preview.detected_user_slot else "")
            st.info(f"Detected Yahoo board: {preview.team_count} teams{user_text}")
            if (preview.team_count != TEAMS
                    or (preview.detected_user_slot and preview.detected_user_slot != MY_SLOT)):
                st.warning("This pasted board appears to be a mock or different league. "
                           "Using detected board settings for this import only.")
            if preview.current_overall_pick:
                manager = f" · {preview.current_manager}" if preview.current_manager else ""
                st.caption(f"On the clock: {preview.current_round}.{preview.current_slot}{manager} "
                           f"(overall pick {preview.current_overall_pick})")
        preview_picks = list(preview.picks) if preview else []
        paste_matches = [(pick, *match_pasted_name(pick.name, available)) for pick in preview_picks]
        confirmed = [(pick, player) for pick, player, status in paste_matches
                     if status == "confirmed" and player is not None]
        for pick, player, status in paste_matches:
            if status == "confirmed":
                owner = " · YOUR PICK" if yahoo_pick_is_mine(
                    pick, preview, configured_slot=MY_SLOT) else ""
                st.success(f"{pick.round}.{pick.draft_slot} {pick.name} → {player.player} "
                           f"({player.position}, {player.team}){owner}")
            elif status == "ambiguous":
                st.warning(f"{pick.name} — ambiguous; not selected")
            else:
                st.error(f"{pick.name} — no available match")
        if st.button(f"Mark {len(confirmed)} confirmed drafted", disabled=not confirmed,
                     key="confirm_pasted"):
            for pick, player in sorted(confirmed, key=lambda item: item[0].overall_pick):
                draft_player(player.id, yahoo_pick_is_mine(
                    pick, preview, configured_slot=MY_SLOT), pick.overall_pick)
            st.session_state.yahoo_board = preview
            st.session_state.pop("yahoo_preview", None)
            st.session_state.paste_version = paste_version + 1
            st.session_state.quick_version = quick_version + 1
            st.session_state.quick_refocus = True
            st.rerun()

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
