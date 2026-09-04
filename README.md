# Fantasy Draft Assistant

A native Streamlit draft board for a 10-team standard-scoring league drafting from slot 3.

## Run locally

1. Install Python 3 and the dependencies: `python -m pip install -r requirements.txt`.
2. Start the app: `streamlit run streamlit_app.py`.

For Streamlit Community Cloud, select **`streamlit_app.py`** as the app entrypoint. Active draft progress is held in `st.session_state`; use the single-file **Export Draft State** JSON download regularly so a browser/session reset is recoverable.

## 2026 recommendation engine

The board now scores every undrafted player from 0–100 using five configurable
weights in `recommendation_engine.py`: expert history (35%), broad consensus
(25%), ADP value (15%), role/opportunity (15%), and roster construction (10%).
Expert opinions retain their names, overall accuracy weights, and optional
position-specific weights. Target and Fade labels require two corroborating
expert signals; mixed or sparse evidence stays Neutral. Sleeper additionally
requires a meaningful discount outside the obvious early rounds.

The **Top 5 Recommendations** refreshes after every Drafted, + Mine, Undo, import,
or reset action. It shows model and manual labels separately, component scores,
ADP/ECR value, and an explainable snake-draft TAKE NOW / WAIT / FAIR VALUE /
FADE AT THIS PRICE decision. QB recommendations are replacement-value adjusted
for this 10-team, one-QB league. This feature is deterministic and uses no AI,
scraping, Yahoo draft polling, or automated selections.

## Import rankings

Select **Import rankings CSV**. In addition to the original columns, imports may
include `Draft Key`, `Projection`, `Role Score`, `Opportunity Score`, `Risk Score`, `Expert
Count`, `Expert Weighted Rank`, `Recommendation Score`, `Recommendation Label`,
and `Notes`. `Player` and `Position` are required; position must be RB, WR, QB,
or TE. Boolean fields accept Yes, Y, True, 1, or X. Missing optional fields use
neutral model defaults, so old files remain valid. `Target`, `Sleeper`, and
`Fade` are manual overrides shown alongside—never substituted into—the model
score. See `sample-rankings.csv`.

Importing replaces the player board and resets prior draft progress. Use **Drafted** for another team's pick or **+ Mine** for your selection. **Undo** reverses the most recent draft action.

## Quick Draft Entry

At the top of the live controls, **Quick Draft Search** searches only available
players by partial name, last name, NFL team, or Draft Key. Draft Keys are
optional in CSV imports; a readable unique key is generated when omitted.
Select a result with Enter, then use **D** to mark it drafted or **M** to mark it
as yours. **/** or **Ctrl+K** focuses search, **U** undoes the last pick, and
Escape clears the native search or selection. Shortcuts are disabled while
typing in other fields, and the regular buttons remain available if keyboard
enhancement is unavailable.

**Paste Draft Picks / Catch Up** accepts numbered Yahoo-style lines or plain player
names assigned from **Starting Pick Number**. It normalizes punctuation and suffixes,
then uses exact matching before conservative fuzzy matching. Its preview shows pick,
player, position, NFL/fantasy team, ownership, confidence, and status. Snake pick,
fantasy team name, and Yahoo team ID independently identify your picks; conflicting
signals stay in REVIEW and are not imported. Duplicate, drafted, ambiguous, and
unmatched players are also withheld. A confirmed import can be reversed as one batch.

## Draft-night backup

**Export Draft State** downloads league/team settings, the complete player pool,
stable IDs, all picks and ownership, manual labels, and recommendation inputs as one
JSON file. Upload it under **Restore Draft State** and confirm to reproduce the board
without Yahoo access. The defaults are Party on Pearl Street (league `557989`) and
Sippin' On Jeanty Juice (team `6`), but all league fields remain editable.

## Scope

Yahoo authentication remains an optional read-only access check while approval
is pending. Draft synchronization and selections remain manual.

## Yahoo Fantasy authentication

Yahoo authentication uses the OAuth 2.0 Authorization Code flow and is optional; the manual draft board continues to work without it. Create a Yahoo developer application with the callback URL that exactly matches the deployed Streamlit app URL, then add these values to local or Community Cloud Streamlit Secrets:

```toml
[yahoo]
client_id = "your-yahoo-client-id"
client_secret = "your-yahoo-client-secret"
redirect_uri = "https://your-app.streamlit.app/"
```

For local development, use the exact local callback URL registered with Yahoo (for example, `http://localhost:8501/`). Never commit `.streamlit/secrets.toml`; it is ignored by this repository. Tokens remain in the active Streamlit session. The connection check performs one read-only Fantasy Sports API request and does not change leagues, rosters, transactions, or picks.
