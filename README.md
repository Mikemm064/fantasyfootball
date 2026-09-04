# Fantasy Draft Assistant

A reliable, local-only browser draft board for a 10-team standard-scoring Yahoo league drafting from slot 3.

## Start on Windows

1. Install [Python 3](https://www.python.org/downloads/) if it is not already installed (select **Add Python to PATH** during installation).
2. Double-click **`run.bat`**. Your browser opens automatically.
3. Keep the command window open during the draft. Close it or press Ctrl+C when finished.

No packages, account, internet connection, or build step are required. Draft progress is saved in that browser's local storage.

## Import rankings

Select **Import rankings CSV**. Supported columns are `Player`, `Position`, `Team`, `Overall Rank`, `ADP`, `Expert Consensus Rank`, `Target`, `Sleeper`, `Fade`, and `Drafted`. `Player` and `Position` are required; position must be RB, WR, QB, or TE. Boolean fields accept Yes, Y, True, 1, or X. See `sample-rankings.csv`.

Importing replaces the player board and resets prior draft progress. Use **Drafted** for another team's pick or **+ Mine** for your selection. The undo arrow in the draft log corrects a mistake.

## Scope

Milestone 1 intentionally contains no Yahoo authentication, live synchronization, AI, or recommendation scoring. Those are planned for Milestone 2 after the local workflow is proven reliable.
