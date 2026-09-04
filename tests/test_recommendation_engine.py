import unittest
from dataclasses import replace

from draft_utils import draft_timing
from recommendation_engine import (Expert, evaluate_player, rank_recommendations,
                                   roster_fit_score, standard_scoring_adjustment)
from streamlit_app import Player, stable_player_id


def player(name="Player", position="WR", rank=30, adp=40, ecr=30, **kwargs):
    return Player(stable_player_id(name, position, "TST"), name, position, "TST",
                  rank, adp, ecr, False, False, False, **kwargs)


EXPERTS = {name: Expert(name, weight) for name, weight in
           (("Accurate A", 1.3), ("Accurate B", 1.1), ("Contrarian", .8))}


class RecommendationEngineTest(unittest.TestCase):
    def test_one_expert_cannot_create_target(self):
        p = player(expert_rankings={"Accurate A": 20})
        self.assertEqual(evaluate_player(p, experts=EXPERTS).model_label, "Neutral")

    def test_two_corroborating_experts_create_target(self):
        p = player(adp=36, ecr=32, expert_rankings={"Accurate A": 24, "Accurate B": 26})
        self.assertEqual(evaluate_player(p, experts=EXPERTS).model_label, "Target")

    def test_conflicting_experts_are_neutral(self):
        p = player(adp=40, expert_rankings={"Accurate A": 25, "Contrarian": 60})
        self.assertEqual(evaluate_player(p, experts=EXPERTS).model_label, "Neutral")

    def test_adp_discount_improves_score_and_premium_lowers_it(self):
        cheap = player(adp=60, ecr=30, expert_count=2, expert_weighted_rank=28)
        expensive = player(adp=20, ecr=30, expert_count=2, expert_weighted_rank=34)
        self.assertGreater(evaluate_player(cheap).final_score, evaluate_player(expensive).final_score)
        self.assertGreater(evaluate_player(cheap).adp_value_score, 50)
        self.assertLess(evaluate_player(expensive).adp_value_score, 50)

    def test_standard_scoring_traits(self):
        power_back = standard_scoring_adjustment("RB", rushing_volume=1, goal_line=1)
        receiving_back = standard_scoring_adjustment("RB", reception_dependency=1)
        deep_receiver = standard_scoring_adjustment("WR", deep_upside=1, touchdown_equity=1)
        self.assertGreater(power_back, receiving_back)
        self.assertGreater(deep_receiver, 0)

    def test_qb_replacement_penalty(self):
        self.assertLess(roster_fit_score("QB", [], 18), roster_fit_score("WR", [], 18))
        qb = player(position="QB", adp=18, rank=10, ecr=10,
                    expert_rankings={"Accurate A": 8, "Accurate B": 9})
        wr = replace(qb, id="wr", position="WR")
        self.assertLess(evaluate_player(qb, current_pick=18, experts=EXPERTS).final_score,
                        evaluate_player(wr, current_pick=18, experts=EXPERTS).final_score)

    def test_roster_changes_fit(self):
        roster = [player(str(i), "RB") for i in range(3)]
        self.assertGreater(roster_fit_score("WR", roster, 40), roster_fit_score("RB", roster, 40))

    def test_snake_return_estimate(self):
        action, survives, _ = draft_timing(current_pick=38, next_pick=43, adp=62,
                                           rank=49, position="WR", model_label="Target")
        self.assertTrue(survives)
        self.assertEqual(action, "WAIT")
        action, survives, _ = draft_timing(current_pick=38, next_pick=43, adp=41,
                                           rank=29, position="WR", model_label="Target")
        self.assertFalse(survives)
        self.assertEqual(action, "TAKE NOW")

    def test_drafted_players_never_recommended(self):
        first, second = player("First"), player("Second")
        ranked = rank_recommendations([first, second], {first.id})
        self.assertEqual([p.player for p, _ in ranked], ["Second"])


if __name__ == "__main__":
    unittest.main()
