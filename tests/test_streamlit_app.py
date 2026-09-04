import unittest
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

import streamlit_app
from streamlit_app import parse_rankings_csv, snake_picks, stable_player_id


SAMPLE = """Player,Position,Team,Overall Rank,ADP,Expert Consensus Rank,Target,Sleeper,Fade,Drafted
Runner One,RB,ATL,1,2.5,1,Yes,,,No
Receiver Two,WR,CIN,2,3.2,3,,Yes,,No
Quarterback Three,QB,BUF,3,18.4,4,,,,No
Tight End Four,TE,ARI,4,24.1,2,,,Yes,Yes
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

    def test_app_filters_drafts_mine_and_undo(self):
        app = AppTest.from_file("streamlit_app.py", default_timeout=10).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.button(key="draft_" + stable_player_id("Ja'Marr Chase", "WR", "CIN"))), 1)

        app.segmented_control(key="position_filter").set_value("QB").run()
        self.assertEqual(len(app.button(key="draft_" + stable_player_id("Josh Allen", "QB", "BUF"))), 1)
        self.assertEqual(len(app.button(key="draft_" + stable_player_id("Bijan Robinson", "RB", "ATL"))), 0)

        josh_id = stable_player_id("Josh Allen", "QB", "BUF")
        app.button(key="draft_" + josh_id).click().run()
        self.assertEqual(len(app.button(key="draft_" + josh_id)), 0)

        app.segmented_control(key="position_filter").set_value("TE").run()
        brock_id = stable_player_id("Brock Bowers", "TE", "LV")
        app.button(key="mine_" + brock_id).click().run()
        self.assertEqual(len(app.button(key="mine_" + brock_id)), 0)
        self.assertTrue(any(entry["player"].id == brock_id and entry["mine"]
                            for entry in app.session_state["draft_log"]))

        app.button(label="↶ Undo").click().run()
        self.assertEqual(len(app.button(key="mine_" + brock_id)), 1)
        self.assertFalse(any(entry["player"].id == brock_id
                             for entry in app.session_state["draft_log"]))


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
