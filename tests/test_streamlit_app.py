import unittest
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

import streamlit_app
from streamlit_app import (
    match_pasted_name,
    parse_rankings_csv,
    parse_yahoo_draft_board,
    snake_picks,
    stable_player_id,
    yahoo_pick_is_mine,
)


SAMPLE = """Player,Position,Team,Overall Rank,ADP,Expert Consensus Rank,Target,Sleeper,Fade,Drafted
Runner One,RB,ATL,1,2.5,1,Yes,,,No
Receiver Two,WR,CIN,2,3.2,3,,Yes,,No
Quarterback Three,QB,BUF,3,18.4,4,,,,No
Tight End Four,TE,ARI,4,24.1,2,,,Yes,Yes
"""

EXTENDED = """Player,Position,Team,Overall Rank,ADP,Expert Consensus Rank,Projection,Role Score,Opportunity Score,Risk Score,Expert Count,Expert Weighted Rank,Recommendation Score,Recommendation Label,Notes
New Player,WR,SEA,20,31,22,180,75,80,20,2,19,88,Target,Deep role
"""

YAHOO_BOARD = """![manager](https://s.yimg.com/manager.svg)
**Adam**
Adam
Ray
Ray
Randall
Randall
okDen
okDen
Michael
You
WeaponXI
WeaponXI
Monje
Monje
Gridiron
Gridiron
Blitz
Blitz
Sunday
Sunday
Pearl
Pearl
Champion
Champion
Waivers
Waivers
Dynasty
Dynasty

Jahmyr
Gibbs
RB
Det
1.1

Puka
Nacua
WR
LAR
1.5

De'Von
Achane
RB
Mia
2.5

Breece
Hall
RB
NYJ
3.5

Tee
Higgins
WR
Cin
3.6

On the Clock
svg
3.7

3.8
3.9
"""


class AttrDict(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class QueryParams(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clear_calls = 0

    def clear(self):
        self.clear_calls += 1
        super().clear()


class DraftEngineTest(unittest.TestCase):
    def test_snake_picks_for_slot_three(self):
        self.assertEqual(snake_picks(rounds=10), [3, 18, 23, 38, 43, 58, 63, 78, 83, 98])

    def test_csv_import_and_stable_ids(self):
        players = parse_rankings_csv(SAMPLE)
        self.assertEqual([p.position for p in players], ["RB", "WR", "QB", "TE"])
        self.assertTrue(players[-1].drafted)
        self.assertTrue(players[0].target)
        self.assertEqual(players[0].id, stable_player_id("Runner One", "RB", "ATL"))
        self.assertEqual(players[0].id, parse_rankings_csv(SAMPLE)[0].id)

    def test_csv_extended_columns_and_backwards_compatibility(self):
        old = parse_rankings_csv("Player,Position,Rank\nOld,RB,1\n")[0]
        self.assertIsNone(old.role_score)
        new = parse_rankings_csv(EXTENDED)[0]
        self.assertEqual((new.projection, new.role_score, new.expert_count), (180, 75, 2))
        self.assertEqual(new.imported_recommendation_label, "Target")
        self.assertEqual(new.notes, "Deep role")

    def test_draft_keys_are_imported_or_generated_uniquely(self):
        csv_text = """Player,Position,Team,Draft Key,Rank
Same Name,RB,ATL,custom,1
Same Name,WR,CIN,,2
Same Name,QB,BUF,,3
"""
        players = parse_rankings_csv(csv_text)
        self.assertEqual([p.draft_key for p in players], ["custom", "same-name", "same-name-2"])

    def test_paste_matching_is_conservative(self):
        players = parse_rankings_csv(SAMPLE)
        match, status = match_pasted_name("Receiver Two", players)
        self.assertEqual((match.player, status), ("Receiver Two", "confirmed"))
        match, status = match_pasted_name("nobody remotely similar", players)
        self.assertIsNone(match)
        self.assertIn(status, {"ambiguous", "unmatched"})

    def test_complete_yahoo_board_header_ownership_and_clock(self):
        board = parse_yahoo_draft_board(YAHOO_BOARD)
        self.assertEqual(board.team_count, 14)
        self.assertEqual(board.managers[1], "Adam")
        self.assertEqual(board.managers[5], "Michael")
        self.assertEqual(board.detected_user_slot, 5)

        by_name = {pick.name: pick for pick in board.picks}
        for name in ("Puka Nacua", "De'Von Achane", "Breece Hall"):
            self.assertTrue(yahoo_pick_is_mine(
                by_name[name], board, configured_slot=3,
                fantasy_team_name="Sippin' On Jeanty Juice",
            ))
        self.assertFalse(yahoo_pick_is_mine(
            by_name["Tee Higgins"], board, configured_slot=3))
        self.assertEqual((board.current_round, board.current_slot), (3, 7))
        self.assertEqual(board.current_overall_pick, 35)
        self.assertEqual(board.current_manager, "Monje")
        self.assertEqual(len(board.picks), 5)  # Bare 3.8/3.9 slots are not picks.

    def test_yahoo_preview_confirm_updates_session_and_only_offers_new_picks(self):
        app = AppTest.from_file("../streamlit_app.py", default_timeout=10).run()
        app.text_area(key="pasted_names_0").set_value(YAHOO_BOARD).run()
        app.button(key="preview_pasted").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.button(key="confirm_pasted").label, "Mark 3 confirmed drafted")

        app.button(key="confirm_pasted").click().run()
        self.assertFalse(app.exception)
        imported = {entry["player"].player: entry for entry in app.session_state["draft_log"]}
        self.assertTrue(imported["Puka Nacua"]["mine"])
        self.assertTrue(imported["De'Von Achane"]["mine"])
        self.assertFalse(imported["Jahmyr Gibbs"]["mine"])
        self.assertEqual(app.session_state["yahoo_board"].current_overall_pick, 35)

        app.text_area(key="pasted_names_1").set_value(YAHOO_BOARD).run()
        app.button(key="preview_pasted").click().run()
        self.assertEqual(app.button(key="confirm_pasted").label, "Mark 0 confirmed drafted")

    def test_quick_draft_selection_records_and_clears(self):
        app = AppTest.from_file("../streamlit_app.py", default_timeout=10).run()
        player_id = stable_player_id("Ja'Marr Chase", "WR", "CIN")
        app.selectbox(key="quick_search_0").set_value(player_id).run()
        app.button(key="quick_drafted").click().run()
        self.assertTrue(any(entry["player"].id == player_id
                            for entry in app.session_state["draft_log"]))
        self.assertIsNone(app.selectbox(key="quick_search_1").value)

    def test_app_filters_drafts_mine_and_undo(self):
        app = AppTest.from_file("../streamlit_app.py", default_timeout=10).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.button(key="draft_" + stable_player_id("Ja'Marr Chase", "WR", "CIN")).label,
                         "Drafted")

        app.segmented_control(key="position_filter").set_value("QB").run()
        self.assertEqual(app.button(key="draft_" + stable_player_id("Josh Allen", "QB", "BUF")).label,
                         "Drafted")
        self.assertFalse(any(button.key == "draft_" + stable_player_id("Bijan Robinson", "RB", "ATL")
                             for button in app.button))

        josh_id = stable_player_id("Josh Allen", "QB", "BUF")
        app.button(key="draft_" + josh_id).click().run()
        self.assertFalse(any(button.key == "draft_" + josh_id for button in app.button))

        app.segmented_control(key="position_filter").set_value("TE").run()
        brock_id = stable_player_id("Brock Bowers", "TE", "LV")
        app.button(key="mine_" + brock_id).click().run()
        self.assertFalse(any(button.key == "mine_" + brock_id for button in app.button))
        self.assertTrue(any(entry["player"].id == brock_id and entry["mine"]
                            for entry in app.session_state["draft_log"]))

        next(button for button in app.button if button.label == "↶ Undo").click().run()
        self.assertEqual(app.button(key="mine_" + brock_id).label, "+ Mine")
        self.assertFalse(any(entry["player"].id == brock_id
                             for entry in app.session_state["draft_log"]))

    def test_top_five_updates_after_manual_draft(self):
        app = AppTest.from_file("../streamlit_app.py", default_timeout=10).run()
        before = [entry.value for entry in app.markdown
                  if '<div class="player-card"><strong>' in entry.value][:5]
        top_name = "Trey McBride"
        app.button(key="draft_" + stable_player_id(top_name, "TE", "ARI")).click().run()
        after = [entry.value for entry in app.markdown
                 if '<div class="player-card"><strong>' in entry.value][:5]
        self.assertNotEqual(before, after)
        self.assertFalse(any(f">1. {top_name} —" in card for card in after))


class YahooCallbackTest(unittest.TestCase):
    def _streamlit(self, state):
        fake = Mock()
        fake.secrets = {"yahoo": {
            "client_id": "client-id", "client_secret": "client-secret",
            "redirect_uri": "https://example.test/",
        }}
        fake.query_params = QueryParams(code="one-time-code", state=state)
        fake.session_state = AttrDict()
        return fake

    @patch("streamlit_app.yahoo_auth.verify_fantasy_access", return_value=True)
    @patch("streamlit_app.yahoo_auth.exchange_code", return_value={"access_token": "server-only"})
    def test_exchange_requires_valid_state_and_callback_is_cleared(self, exchange, _verify):
        credentials = streamlit_app.yahoo_auth.YahooCredentials(
            "client-id", "client-secret", "https://example.test/"
        )
        state = streamlit_app.yahoo_auth.new_signed_state(credentials)
        fake = self._streamlit(state)
        with patch.object(streamlit_app, "st", fake):
            streamlit_app.render_yahoo_auth()
        exchange.assert_called_once_with(credentials, "one-time-code")
        self.assertEqual(fake.query_params.clear_calls, 1)
        self.assertNotIn("code", fake.query_params)
        self.assertNotIn("state", fake.query_params)

    @patch("streamlit_app.yahoo_auth.exchange_code")
    def test_invalid_state_never_exchanges_code_and_is_cleared(self, exchange):
        fake = self._streamlit("malformed")
        with patch.object(streamlit_app, "st", fake):
            streamlit_app.render_yahoo_auth()
        exchange.assert_not_called()
        self.assertEqual(fake.query_params.clear_calls, 1)


if __name__ == "__main__":
    unittest.main()

class YahooPasteIntegrationTest(unittest.TestCase):
    YAHOO = """Opponent Manager
1
Ja'Marr Chase
WR
Cin
Bye 10
You
2
Bijan Robinson
RB
Atl
Bye 12
On the Clock
3
"""

    def test_structured_import_uses_parser_and_never_plain_line_matcher(self):
        players = parse_rankings_csv(streamlit_app.DEFAULT_CSV)
        settings = dict(streamlit_app.DEFAULT_LEAGUE_SETTINGS)
        with patch("streamlit_app.draft_parser.parse_yahoo_clipboard",
                   wraps=streamlit_app.draft_parser.parse_yahoo_clipboard) as parser, \
             patch("streamlit_app.match_player", side_effect=AssertionError("structured lines used plain matcher")):
            format_name, rows = streamlit_app.prepare_paste_import(self.YAHOO, 1, players, [], settings)
        parser.assert_called_once()
        self.assertEqual(format_name, "yahoo")
        self.assertEqual([row["Player"] for row in rows], ["Ja'Marr Chase", "Bijan Robinson"])
        self.assertEqual([row["Match status"] for row in rows], ["MATCHED", "MATCHED"])
        self.assertNotIn("Opponent Manager", [row["Player"] for row in rows])
        self.assertNotIn("On the Clock", [row["Player"] for row in rows])
        self.assertTrue(rows[1]["enabled"])
        self.assertEqual(rows[1]["Ownership"], "YOUR PICK")

    def test_confirm_and_repeated_full_board_are_incremental(self):
        app = AppTest.from_file("../streamlit_app.py", default_timeout=10).run()
        before_cards = [item.value for item in app.markdown if '<div class="player-card"><strong>' in item.value][:5]
        app.text_area(key="pasted_names").set_value(self.YAHOO).run()
        app.button(key="confirm_pasted").click().run()
        log = app.session_state["draft_log"]
        self.assertEqual([(entry["pick"], entry["player"].player, entry["mine"]) for entry in log],
                         [(1, "Ja'Marr Chase", False), (2, "Bijan Robinson", True)])
        self.assertEqual(streamlit_app.current_overall_pick(log), 3)
        after_cards = [item.value for item in app.markdown if '<div class="player-card"><strong>' in item.value][:5]
        self.assertTrue(after_cards)
        self.assertFalse(any("Ja&#x27;Marr Chase" in card or "Bijan Robinson" in card for card in after_cards))
        app.text_area(key="pasted_names").set_value(self.YAHOO).run()
        self.assertTrue(app.button(key="confirm_pasted").disabled)
        self.assertEqual(len(app.session_state["draft_log"]), 2)

    def test_plain_list_fallback_remains_available(self):
        players = parse_rankings_csv(streamlit_app.DEFAULT_CSV)
        kind, rows = streamlit_app.prepare_paste_import("Ja'Marr Chase\nBijan Robinson", 1, players, [],
                                                        dict(streamlit_app.DEFAULT_LEAGUE_SETTINGS))
        self.assertEqual(kind, "plain")
        self.assertEqual([row["Player"] for row in rows], ["Ja'Marr Chase", "Bijan Robinson"])
