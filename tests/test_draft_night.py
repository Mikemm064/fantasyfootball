import json
import unittest

from draft_parser import match_player, normalize_name, parse_pasted_picks
from draft_utils import (DEFAULT_LEAGUE_SETTINGS, current_overall_pick, export_state,
                         identify_ownership, pick_context, record_pick, restore_state,
                         snake_picks)
from recommendation_engine import rank_recommendations
from streamlit_app import parse_rankings_csv


POOL = """Player,Position,Team,Rank,ADP,ECR
A.J. Brown,WR,PHI,10,11,9
Chase Brown,RB,CIN,25,28,24
Chase Browne,WR,TST,99,100,100
Brock Bowers,TE,LV,15,17,14
Zay Flowers,WR,BAL,30,40,28
"""


class DraftNightReliabilityTest(unittest.TestCase):
    def setUp(self):
        self.settings = dict(DEFAULT_LEAGUE_SETTINGS)
        self.players = parse_rankings_csv(POOL)

    def test_first_fifty_snake_simulation_and_context(self):
        picks = snake_picks(10, 3, 10)
        self.assertEqual(picks[:10], [3, 18, 23, 38, 43, 58, 63, 78, 83, 98])
        mine = {p for p in picks if p <= 50}
        self.assertTrue({3, 18, 23, 38, 43}.issubset(mine))
        self.assertFalse({17, 19}.intersection(mine))
        self.assertEqual(pick_context(50, 10), (5, 10))

    def test_slot_change_regenerates_sequence(self):
        self.assertEqual(snake_picks(10, 1, 4), [1, 20, 21, 40])
        self.assertEqual(snake_picks(10, 5, 4), [5, 16, 25, 36])

    def test_three_independent_ownership_signals(self):
        self.assertEqual(identify_ownership(pick=3, fantasy_team=None, yahoo_team_id=None,
                                            settings=self.settings)[0], "YOUR PICK")
        self.assertEqual(identify_ownership(pick=None, fantasy_team="Sippin' On Jeanty Juice",
                                            yahoo_team_id=None, settings=self.settings)[0], "YOUR PICK")
        self.assertEqual(identify_ownership(pick=None, fantasy_team=None, yahoo_team_id="6",
                                            settings=self.settings)[0], "YOUR PICK")

    def test_conflicting_ownership_is_review(self):
        result, signals = identify_ownership(pick=3, fantasy_team="Opponent", yahoo_team_id="99",
                                             settings=self.settings)
        self.assertEqual(result, "REVIEW")
        self.assertEqual(signals, ["pick"])

    def test_numbered_and_plain_paste(self):
        numbered = parse_pasted_picks("18. A.J. Brown\nPick 19 - Chase Brown", 1)
        self.assertEqual([(r["pick"], r["raw_name"]) for r in numbered],
                         [(18, "A.J. Brown"), (19, "Chase Brown")])
        plain = parse_pasted_picks("Brock Bowers\nZay Flowers", 34)
        self.assertEqual([r["pick"] for r in plain], [34, 35])

    def test_normalized_suffixes_punctuation(self):
        self.assertEqual(normalize_name("A.J. Brown Jr."), normalize_name("AJ-Brown JR"))

    def test_ambiguous_fuzzy_match_not_accepted(self):
        matched, confidence, status = match_player("Chase Brow", self.players)
        self.assertIsNone(matched)
        self.assertEqual((confidence, status), ("Ambiguous", "Ambiguous name"))

    def test_duplicate_recording_and_current_pick(self):
        log = []
        self.assertTrue(record_pick(log, self.players[0].id, pick=1))
        self.assertFalse(record_pick(log, self.players[0].id, pick=2))
        self.assertFalse(record_pick(log, self.players[1].id, pick=1))
        for pick, player in zip(range(2, 5), self.players[1:]):
            record_pick(log, player.id, pick=pick)
        self.assertEqual(current_overall_pick(log), 5)

    def test_batch_mine_roster_and_recommendations_update(self):
        log = []
        record_pick(log, self.players[0].id, pick=3, mine=True, batch_id="batch")
        record_pick(log, self.players[1].id, pick=4, mine=False, batch_id="batch")
        roster_ids = {e["player_id"] for e in log if e["mine"]}
        self.assertEqual(roster_ids, {self.players[0].id})
        ranked = rank_recommendations(self.players, {e["player_id"] for e in log})
        self.assertNotIn(self.players[0].id, {p.id for p, _ in ranked})
        self.assertNotIn(self.players[1].id, {p.id for p, _ in ranked})

    def test_undo_restores_availability_and_current_pick(self):
        log = []
        record_pick(log, self.players[0].id, pick=1)
        log.pop()
        self.assertEqual(current_overall_pick(log), 1)
        self.assertIn(self.players[0].id, {p.id for p, _ in rank_recommendations(self.players, set())})

    def test_export_restore_complete_round_trip(self):
        player_rows = [p.__dict__ for p in self.players]
        log = [{"player_id": self.players[0].id, "pick": 3, "mine": True,
                "batch_id": None, "source": "manual"}]
        raw = export_state(self.settings, player_rows, log, {self.players[0].id: "Target"})
        restored = restore_state(raw)
        self.assertEqual(restored["league_settings"], self.settings)
        self.assertEqual(restored["draft_log"], log)
        self.assertEqual(restored["manual_labels"][self.players[0].id], "Target")
        self.assertEqual(json.loads(raw)["schema_version"], 1)

    def test_fifty_recorded_picks_advance_to_51(self):
        log = []
        for pick in range(1, 51):
            record_pick(log, f"player-{pick}", pick=pick, mine=pick in snake_picks(10, 3, 10))
        self.assertEqual(current_overall_pick(log), 51)
        self.assertEqual(sum(e["mine"] for e in log), 5)


if __name__ == "__main__":
    unittest.main()
