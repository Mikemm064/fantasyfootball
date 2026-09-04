import unittest
from dataclasses import dataclass

from draft_parser import incremental_import, match_players, parse_yahoo_clipboard


@dataclass
class Candidate:
    player: str
    position: str
    team: str


class DraftParserTest(unittest.TestCase):
    def test_manager_pick_format_is_sorted_and_marks_your_team(self):
        text = """Randall\n2\nB. Robinson\nRB\nAtl\nBye 11
Your Team\n4\nJ. Chase\nWR\nCin\nBye 6
Ray\n1\nJ. Gibbs\nRB\nDet\nBye 6"""
        picks = parse_yahoo_clipboard(text)
        self.assertEqual([pick.overall_pick for pick in picks], [1, 2, 4])
        self.assertEqual((picks[-1].fantasy_team, picks[-1].bye_week), ("Your Team", 6))
        self.assertTrue(picks[-1].mine)
        self.assertEqual(picks[-1].confidence, "very_high")

    def test_draft_board_format(self):
        picks = parse_yahoo_clipboard("Jahmyr\nGibbs\nRB\nDet\n1.1")
        self.assertEqual(len(picks), 1)
        self.assertEqual((picks[0].player_name, picks[0].overall_pick), ("Jahmyr Gibbs", 1))

    def test_markdown_images_and_svg_are_ignored(self):
        text = """| **Your Team** | 4 | **J. Chase** | WR | Cin | Bye 6 |
|---|---:|---|---|---|---|
![headshot](https://example.test/chase.png)
<svg><path>presentation only</path></svg>"""
        pick = parse_yahoo_clipboard(text)[0]
        self.assertEqual((pick.player_name, pick.nfl_team, pick.bye_week), ("J. Chase", "CIN", 6))

    def test_abbreviation_requires_name_position_and_team_and_preserves_suffix(self):
        candidates = [
            Candidate("Jahmyr Gibbs", "RB", "DET"),
            Candidate("Jahmyr Gibbs", "WR", "DET"),
            Candidate("James Cook II", "RB", "BUF"),
            Candidate("James Cook III", "RB", "BUF"),
            Candidate("Amon-Ra St. Brown", "WR", "DET"),
        ]
        text = """A\n1\nJ. Gibbs\nRB\nDet\nBye 6
B\n2\nJ. Cook III\nRB\nBuf\nBye 7
C\n3\nA. St. Brown\nWR\nDet\nBye 6"""
        picks = match_players(parse_yahoo_clipboard(text), candidates)
        self.assertEqual([pick.matched_player.player for pick in picks],
                         ["Jahmyr Gibbs", "James Cook III", "Amon-Ra St. Brown"])

    def test_ambiguous_matches_and_incremental_conflicts_are_not_guessed(self):
        candidates = [Candidate("Brian Robinson", "RB", "ATL"), Candidate("Bijan Robinson", "RB", "ATL")]
        picks = parse_yahoo_clipboard("Ray\n2\nB. Robinson\nRB\nAtl\nBye 11")
        match_players(picks, candidates)
        self.assertTrue(picks[0].needs_review)
        self.assertIsNone(picks[0].matched_player)

        duplicate = incremental_import(picks, [{"pick": 2, "player": "B. Robinson"}])
        self.assertEqual(duplicate.new_picks, [])
        conflict = incremental_import(picks, [{"pick": 2, "player": "Someone Else"}])
        self.assertEqual(conflict.conflicts, picks)


if __name__ == "__main__":
    unittest.main()

class IncomingDuplicateReconciliationTest(unittest.TestCase):
    def _pick(self, number, name, position="WR", team="PHI"):
        from draft_parser import DraftPick
        return DraftPick(number, name, position, team)

    def test_exact_duplicate_incoming_is_accepted_once(self):
        result = incremental_import([self._pick(18, "A.J. Brown"), self._pick(18, "a.j. brown")], [])
        self.assertEqual(len(result.new_picks), 1)
        self.assertEqual(len(result.unchanged), 1)
        self.assertEqual(result.conflicts, [])

    def test_conflicting_duplicate_incoming_rejects_pick_number(self):
        result = incremental_import([self._pick(18, "A.J. Brown"),
                                     self._pick(18, "Garrett Wilson", team="NYJ")], [])
        self.assertEqual(result.new_picks, [])
        self.assertEqual({pick.player_name for pick in result.conflicts}, {"A.J. Brown", "Garrett Wilson"})

    def test_existing_identity_is_unchanged_or_conflict(self):
        identical = incremental_import([self._pick(18, "A.J. Brown")],
                                       [{"pick": 18, "player": "a.j. brown", "position": "WR", "team": "PHI"}])
        self.assertEqual((identical.new_picks, len(identical.unchanged)), ([], 1))
        conflict = incremental_import([self._pick(18, "Garrett Wilson", team="NYJ")],
                                      [{"pick": 18, "player": "A.J. Brown", "position": "WR", "team": "PHI"}])
        self.assertEqual((conflict.new_picks, len(conflict.conflicts)), ([], 1))
