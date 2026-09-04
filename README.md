# Fantasy Draft Assistant

A native Streamlit draft board for a 10-team standard-scoring league drafting from slot 3.

## Run locally

1. Install Python 3 and the dependencies: `python -m pip install -r requirements.txt`.
2. Start the app: `streamlit run streamlit_app.py`.

For Streamlit Community Cloud, select **`streamlit_app.py`** as the app entrypoint. Active draft progress is held in `st.session_state` for the browser session.

## Import rankings

Select **Import rankings CSV**. Supported columns are `Player`, `Position`, `Team`, `Overall Rank`, `ADP`, `Expert Consensus Rank`, `Target`, `Sleeper`, `Fade`, and `Drafted`. `Player` and `Position` are required; position must be RB, WR, QB, or TE. Boolean fields accept Yes, Y, True, 1, or X. See `sample-rankings.csv`.

Importing replaces the player board and resets prior draft progress. Use **Drafted** for another team's pick or **+ Mine** for your selection. **Undo** reverses the most recent draft action.

## Scope

Milestone 1 intentionally contains no Yahoo authentication, live synchronization, AI, or recommendation scoring. Those are planned for Milestone 2 after the local workflow is proven reliable.
