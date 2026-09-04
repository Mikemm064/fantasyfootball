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

The current milestone adds Yahoo authentication and a read-only Fantasy Football access check. Live synchronization, AI, and recommendation scoring remain out of scope; the draft workflow stays manual.

## Yahoo Fantasy authentication

Yahoo authentication uses the OAuth 2.0 Authorization Code flow and is optional; the manual draft board continues to work without it. Create a Yahoo developer application with the callback URL that exactly matches the deployed Streamlit app URL, then add these values to local or Community Cloud Streamlit Secrets:

```toml
[yahoo]
client_id = "your-yahoo-client-id"
client_secret = "your-yahoo-client-secret"
redirect_uri = "https://your-app.streamlit.app/"
```

For local development, use the exact local callback URL registered with Yahoo (for example, `http://localhost:8501/`). Never commit `.streamlit/secrets.toml`; it is ignored by this repository. Tokens remain in the active Streamlit session. The connection check performs one read-only Fantasy Sports API request and does not change leagues, rosters, transactions, or picks.
