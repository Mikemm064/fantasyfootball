const STORAGE_KEY = "fantasy-draft-assistant-v1";
const picks = DraftEngine.snakePicks(10, 3, 20);
const defaultCSV = `Player,Position,Team,Overall Rank,ADP,Expert Consensus Rank,Target,Sleeper,Fade,Drafted
Ja'Marr Chase,WR,CIN,1,1.4,1,Yes,,,No
Bijan Robinson,RB,ATL,2,2.1,2,Yes,,,No
Jahmyr Gibbs,RB,DET,3,3.2,3,Yes,,,No
Justin Jefferson,WR,MIN,4,4.8,4,,,,No
CeeDee Lamb,WR,DAL,5,5.3,5,,,,No
Puka Nacua,WR,LAR,6,7.1,6,Yes,,,No
Saquon Barkley,RB,PHI,7,6.8,7,,,,No
Amon-Ra St. Brown,WR,DET,8,8.2,8,,,,No
Josh Allen,QB,BUF,9,18.0,10,,,,No
Brock Bowers,TE,LV,10,13.4,9,Yes,,,No
Lamar Jackson,QB,BAL,11,21.0,12,,,,No
Trey McBride,TE,ARI,12,20.1,11,,Yes,,No
Malik Nabers,WR,NYG,13,12.4,13,,Yes,,No
De'Von Achane,RB,MIA,14,15.7,14,,,Yes,No`;

let state = loadState();
let filter = "ALL";
let query = "";

function loadState() {
  try { const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)); if (saved?.players) return saved; } catch (_) {}
  return { players: DraftEngine.parseCSV(defaultCSV), drafted: [], myRoster: [] };
}
function save() { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
function esc(value) { const el = document.createElement("span"); el.textContent = value ?? ""; return el.innerHTML; }
function currentPick() { return state.drafted.length + 1; }

function render() {
  const current = currentPick(); const next = DraftEngine.nextPick(current, picks);
  document.querySelector("#currentPick").textContent = current;
  document.querySelector("#nextPick").textContent = next ?? "—";
  document.querySelector("#picksUntil").textContent = next === null ? "—" : Math.max(0, next - current);
  document.querySelector("#pickPath").textContent = picks.filter(p => p >= current).slice(0, 5).join(" · ") || "Draft complete";
  document.querySelector("#positionFilters").innerHTML = DraftEngine.POSITIONS.map(p => `<button class="filter ${filter === p ? "active" : ""}" data-position="${p}">${p}</button>`).join("");
  const draftedIds = new Set(state.drafted.map(d => d.id));
  const available = state.players.filter(p => !draftedIds.has(p.id));
  const shown = available.filter(p => (filter === "ALL" || p.position === filter) && (`${p.player} ${p.team}`.toLowerCase().includes(query)));
  document.querySelector("#availableCount").textContent = `${available.length} available`;
  document.querySelector("#playerRows").innerHTML = shown.map(p => `<tr>
    <td class="rank">${p.rank ?? "—"}</td><td><strong>${esc(p.player)}</strong><small>${esc(p.team)}</small></td><td><span class="pos pos-${p.position.toLowerCase()}">${p.position}</span></td>
    <td>${p.adp ?? "—"}</td><td>${p.ecr ?? "—"}</td><td>${badges(p)}</td><td class="actions"><button data-draft="${p.id}">Drafted</button><button class="mine" data-mine="${p.id}" title="Draft to my roster">+ Mine</button></td></tr>`).join("");
  const empty = document.querySelector("#emptyState"); empty.hidden = shown.length > 0; empty.textContent = state.players.length ? "No available players match these filters." : "Import a rankings CSV to begin.";
  document.querySelector("#rosterCount").textContent = state.myRoster.length;
  document.querySelector("#rosterList").innerHTML = state.myRoster.length ? state.myRoster.map(sidePlayer).join("") : '<p class="placeholder">Use “+ Mine” when you make a pick.</p>';
  document.querySelector("#draftedList").innerHTML = state.drafted.length ? [...state.drafted].reverse().map((p, i) => `<div class="side-player"><span class="pick-num">${state.drafted.length - i}</span><div><strong>${esc(p.player)}</strong><small>${p.position} · ${esc(p.team)}${p.mine ? " · YOUR PICK" : ""}</small></div><button data-undo="${p.id}" title="Undo drafted status">↶</button></div>`).join("") : '<p class="placeholder">No picks recorded yet.</p>';
}
function badges(p) { return [[p.target,"Target","target"],[p.sleeper,"Sleeper","sleeper"],[p.fade,"Fade","fade"]].filter(x=>x[0]).map(x=>`<span class="badge ${x[2]}">${x[1]}</span>`).join(" ") || '<span class="badge neutral">Neutral</span>'; }
function sidePlayer(p) { return `<div class="side-player"><span class="pos pos-${p.position.toLowerCase()}">${p.position}</span><div><strong>${esc(p.player)}</strong><small>${esc(p.team)} · Pick ${p.pick}</small></div></div>`; }
function draft(id, mine) { const p = state.players.find(x => x.id === id); if (!p || state.drafted.some(x => x.id === id)) return; const record = {...p, mine, pick: currentPick()}; state.drafted.push(record); if (mine) state.myRoster.push(record); save(); render(); }

document.addEventListener("click", e => {
  const pos = e.target.dataset.position; if (pos) { filter = pos; render(); }
  if (e.target.dataset.draft) draft(e.target.dataset.draft, false);
  if (e.target.dataset.mine) draft(e.target.dataset.mine, true);
  if (e.target.dataset.undo) { const id = e.target.dataset.undo; state.drafted = state.drafted.filter(p => p.id !== id); state.myRoster = state.myRoster.filter(p => p.id !== id); save(); render(); }
});
document.querySelector("#search").addEventListener("input", e => { query = e.target.value.trim().toLowerCase(); render(); });
document.querySelector("#resetDraft").addEventListener("click", () => { if (confirm("Clear every drafted player and reset to pick 1?")) { state.drafted=[]; state.myRoster=[]; save(); render(); } });
document.querySelector("#csvFile").addEventListener("change", async e => {
  const file = e.target.files[0]; if (!file) return;
  const players = DraftEngine.parseCSV(await file.text()); const notice = document.querySelector("#notice");
  if (!players.length) { notice.textContent = "No valid players found. Check that Player and Position columns are present."; notice.className="notice error show"; return; }
  state = { players, drafted: players.filter(p=>p.drafted).map((p,i)=>({...p,pick:i+1,mine:false})), myRoster: [] }; save(); render(); notice.textContent = `Imported ${players.length} players from ${file.name}.`; notice.className="notice success show"; setTimeout(()=>notice.classList.remove("show"), 5000);
});
render();
