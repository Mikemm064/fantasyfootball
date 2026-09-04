import unittest

from streamlit.testing.v1 import AppTest

from streamlit_app import parse_rankings_csv, snake_picks, stable_player_id


SAMPLE = """Player,Position,Team,Overall Rank,ADP,Expert Consensus Rank,Target,Sleeper,Fade,Drafted
Runner One,RB,ATL,1,2.5,1,Yes,,,No
Receiver Two,WR,CIN,2,3.2,3,,Yes,,No
Quarterback Three,QB,BUF,3,18.4,4,,,,No
Tight End Four,TE,ARI,4,24.1,2,,,Yes,Yes
"""


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


if __name__ == "__main__":
    unittest.main()
