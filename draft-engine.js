(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.DraftEngine = api;
})(typeof self !== "undefined" ? self : this, function () {
  const POSITIONS = ["ALL", "RB", "WR", "QB", "TE"];

  function snakePicks(teams, slot, rounds) {
    const picks = [];
    for (let round = 1; round <= rounds; round++) {
      const withinRound = round % 2 ? slot : teams - slot + 1;
      picks.push((round - 1) * teams + withinRound);
    }
    return picks;
  }

  function stableId(player, position, team) {
    const input = `${player}|${position}|${team}`.trim().toLowerCase();
    let hash = 2166136261;
    for (let i = 0; i < input.length; i++) {
      hash ^= input.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return `p_${(hash >>> 0).toString(36)}`;
  }

  function parseCSV(text) {
    const rows = []; let row = []; let value = ""; let quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted && c === '"' && text[i + 1] === '"') { value += '"'; i++; }
      else if (c === '"') quoted = !quoted;
      else if (c === "," && !quoted) { row.push(value.trim()); value = ""; }
      else if ((c === "\n" || c === "\r") && !quoted) {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(value.trim()); value = "";
        if (row.some(Boolean)) rows.push(row); row = [];
      } else value += c;
    }
    row.push(value.trim()); if (row.some(Boolean)) rows.push(row);
    if (rows.length < 2) return [];
    const normalize = s => s.toLowerCase().replace(/[^a-z0-9]/g, "");
    const headers = rows.shift().map(normalize);
    const get = (r, names) => { const i = headers.findIndex(h => names.includes(h)); return i >= 0 ? r[i] || "" : ""; };
    return rows.map((r, i) => {
      const player = get(r, ["player", "playername", "name"]);
      const position = get(r, ["position", "pos"]).toUpperCase();
      const team = get(r, ["team", "nflteam"]).toUpperCase();
      const number = names => { const n = Number(get(r, names)); return Number.isFinite(n) && n > 0 ? n : null; };
      const truthy = names => /^(true|yes|y|1|x)$/i.test(get(r, names));
      return { id: stableId(player, position, team), player, position, team,
        rank: number(["overallrank", "rank", "overall"]), adp: number(["adp"]), ecr: number(["expertconsensusrank", "ecr"]),
        target: truthy(["target"]), sleeper: truthy(["sleeper"]), fade: truthy(["fade"]), drafted: truthy(["drafted"]), sourceOrder: i };
    }).filter(p => p.player && POSITIONS.includes(p.position) && p.position !== "ALL")
      .sort((a, b) => (a.rank || 9999) - (b.rank || 9999) || a.sourceOrder - b.sourceOrder);
  }

  function nextPick(current, picks) { return picks.find(p => p >= current) || null; }
  return { POSITIONS, snakePicks, stableId, parseCSV, nextPick };
});
