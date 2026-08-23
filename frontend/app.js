/* Steam Group Hub - Frontend ohne Framework.
   Alles was hier passiert: JSON von /api/* holen, in DOM giessen, ein paar SVGs malen. */

const api = async (path) => {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
};

const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html !== undefined) n.innerHTML = html;
  return n;
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

const PALETTE = ["#66c0f4", "#a4d007", "#f0a03c", "#e05c5c", "#b48ef0", "#4fd1c5", "#f472b6", "#facc15"];

const hours = (min) => {
  if (!min) return "0 h";
  if (min < 60) return `${min} min`;
  return `${Math.round(min / 60).toLocaleString("de-DE")} h`;
};
const num = (v) => (v ?? 0).toLocaleString("de-DE");
const euro = (cents) => `${((cents || 0) / 100).toLocaleString("de-DE", { maximumFractionDigits: 0 })} €`;

const relTime = (ts) => {
  if (!ts) return "nie";
  const d = Math.floor(Date.now() / 1000) - ts;
  if (d < 3600) return `vor ${Math.max(1, Math.floor(d / 60))} min`;
  if (d < 86400) return `vor ${Math.floor(d / 3600)} h`;
  if (d < 86400 * 30) {
    const t = Math.floor(d / 86400);
    return `vor ${t} ${t === 1 ? "Tag" : "Tagen"}`;
  }
  return new Date(ts * 1000).toLocaleDateString("de-DE");
};

const iconUrl = (appid, icon) =>
  icon
    ? `https://media.steampowered.com/steamcommunity/public/images/apps/${appid}/${icon}.jpg`
    : `https://cdn.cloudflare.steamstatic.com/steam/apps/${appid}/capsule_sm_120.jpg`;
const headerUrl = (appid, header) =>
  header || `https://cdn.cloudflare.steamstatic.com/steam/apps/${appid}/header.jpg`;

const state = { players: [], me: localStorage.getItem("me") || "", loaded: {} };

/* ------------------------------------------------------------------ tabs */

document.getElementById("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b === btn));
  const id = btn.dataset.tab;
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === id));
  loadTab(id);
});

async function loadTab(id) {
  if (state.loaded[id]) return;
  state.loaded[id] = true;
  try {
    if (id === "library") await loadLibrary();
    if (id === "ideas") await loadIdeas();
    if (id === "achievements") await loadAchievements();
    if (id === "ranks") await loadRanks();
    if (id === "vote") await loadVotes();
  } catch (err) {
    state.loaded[id] = false;
    console.error(err);
  }
}

/* -------------------------------------------------------------- übersicht */

async function loadDashboard() {
  const [ov, players, awards, tl, act] = await Promise.all([
    api("/api/overview"),
    api("/api/players"),
    api("/api/awards"),
    api("/api/timeline?days=30"),
    api("/api/activity?days=21&limit=40"),
  ]);
  state.players = players;
  renderWhoami();

  const run = ov.last_run;
  document.getElementById("lastRun").textContent = run
    ? `Letzte Aktualisierung ${relTime(run.finished_at)}${run.ok ? "" : " – letzter Lauf mit Fehler"}`
    : "Noch keine Daten – bitte einmal den Sammler laufen lassen.";

  const cards = [
    [num(ov.players), "Spieler"],
    [num(ov.games_distinct), "verschiedene Spiele"],
    [hours(ov.minutes_total), "Spielzeit gesamt"],
    [num(ov.shared_all_multiplayer), "Multiplayer-Titel, die alle haben"],
    [hours(ov.minutes_last_14d), "gespielt in 14 Tagen"],
    [num(ov.achievements_unlocked), "Errungenschaften"],
    [num(ov.unplayed_entries), "nie gestartete Spiele"],
    [euro(ov.library_value_cents), "Bibliothekswert (Listenpreis)"],
  ];
  const stats = document.getElementById("stats");
  stats.innerHTML = "";
  cards.forEach(([v, k]) => {
    stats.append(el("div", "stat", `<div class="v">${esc(v)}</div><div class="k">${esc(k)}</div>`));
  });

  drawLineChart(document.getElementById("timelineChart"), document.getElementById("timelineLegend"), tl);

  const medals = ["🏆", "🥇", "🎖️", "⭐", "🔥", "💰", "💎", "🦉", "🎯"];
  const aw = document.getElementById("awards");
  aw.innerHTML = "";
  if (!awards.length) aw.append(el("div", "empty", "Noch keine Auszeichnungen – es fehlen Daten."));
  awards.forEach((a, i) => {
    aw.append(el("div", "award", `
      <span class="medal">${medals[i % medals.length]}</span>
      <div><b>${esc(a.title)}</b> – <span class="who">${esc(a.player)}</span>
        <div class="hint">${esc(a.desc)}</div></div>
      <span class="val">${esc(a.value)}</span>`));
  });

  const feed = document.getElementById("activity");
  feed.innerHTML = "";
  if (!act.length) {
    feed.append(el("div", "empty", "Noch keine Sessions erfasst. Der Feed füllt sich, sobald der Sammler ein paar Mal gelaufen ist."));
  }
  act.forEach((a) => {
    const item = el("div", "feed-item", `
      <img class="ico" src="${iconUrl(a.appid, a.icon)}" alt="" loading="lazy">
      <div class="txt"><b>${esc(a.player)}</b> spielte <span class="game" data-app="${a.appid}">${esc(a.game)}</span></div>
      <span class="mins">${hours(a.minutes)}</span>
      <span class="when">${relTime(a.end)}</span>`);
    feed.append(item);
  });

  const pl = document.getElementById("players");
  pl.innerHTML = "";
  players.forEach((p) => {
    const top = p.top_games?.[0];
    pl.append(el("div", "player", `
      <img src="${esc(p.avatar || "")}" alt="" loading="lazy">
      <div class="meta">
        <div class="name">${esc(p.name)}</div>
        <div class="tiny">${p.games} Spiele · ${p.unplayed} nie gestartet${top ? ` · meist: ${esc(top.name)}` : ""}</div>
      </div>
      <div class="num"><b>${hours(p.minutes)}</b><span class="tiny">${hours(p.minutes_last_14d)} / 14 T.</span></div>`));
  });
}

/* ------------------------------------------------------------ bibliothek */

function libParams() {
  const p = new URLSearchParams({
    search: document.getElementById("libSearch").value.trim(),
    multiplayer_only: document.getElementById("libMp").checked,
    unplayed_only: document.getElementById("libUnplayed").checked,
    min_owners: document.getElementById("libOwners").value || 1,
    sort: document.getElementById("libSort").value,
    limit: 400,
  });
  return `/api/library?${p}`;
}

async function loadLibrary() {
  const sel = document.getElementById("libOwners");
  if (!sel.options.length) {
    const n = Math.max(state.players.length, 1);
    for (let i = 1; i <= n; i++) {
      const o = new Option(i === n ? `${i} (alle)` : String(i), i);
      sel.add(o);
    }
    sel.value = Math.min(2, n);
    ["libSearch", "libMp", "libUnplayed", "libOwners", "libSort"].forEach((id) => {
      const node = document.getElementById(id);
      node.addEventListener(node.tagName === "INPUT" && node.type === "search" ? "input" : "change", debounce(renderLibrary, 250));
    });
  }
  await renderLibrary();
}

async function renderLibrary() {
  const rows = await api(libParams());
  document.getElementById("libCount").textContent = `${rows.length} Treffer`;
  const wrap = document.getElementById("libTable");
  wrap.innerHTML = "";
  if (!rows.length) {
    wrap.append(el("div", "empty", "Keine Spiele gefunden. Filter lockern?"));
    return;
  }
  const t = el("table");
  t.innerHTML = `<thead><tr>
      <th>Spiel</th><th class="num">Besitzer</th><th>Wer</th>
      <th class="num">Spielzeit</th><th class="num">zuletzt</th><th>Modus</th>
    </tr></thead>`;
  const tb = el("tbody");
  rows.forEach((g) => {
    const tr = el("tr");
    const missing = g.missing_names.length && g.missing_names.length <= 3
      ? `<span class="chip miss">fehlt: ${g.missing_names.map(esc).join(", ")}</span>` : "";
    tr.innerHTML = `
      <td><div class="gamecell" data-app="${g.appid}">
        <img src="${iconUrl(g.appid, g.icon)}" alt="" loading="lazy"><span class="nm">${esc(g.name)}</span>
      </div></td>
      <td class="num">${g.owners}</td>
      <td>${g.owner_names.slice(0, 4).map((n) => `<span class="chip">${esc(n)}</span>`).join("")}${missing}</td>
      <td class="num">${hours(g.total_minutes)}</td>
      <td class="num">${g.last_played ? relTime(g.last_played) : "–"}</td>
      <td>${g.is_coop ? '<span class="chip co">Koop</span>' : ""}${g.is_pvp ? '<span class="chip">PvP</span>' : ""}${!g.meta_ok ? '<span class="hint">?</span>' : ""}</td>`;
    tb.append(tr);
  });
  t.append(tb);
  wrap.append(t);
}

/* ------------------------------------------------------------ spielideen */

function gameCard(g, extra = "") {
  const c = el("div", "game-card");
  c.dataset.app = g.appid;
  c.innerHTML = `
    <img class="head" src="${headerUrl(g.appid, g.header_image)}" alt="" loading="lazy">
    <div class="body">
      <div class="title">${esc(g.name)}</div>
      <div class="why">${esc(g.reason || g.tag || "")}</div>
      <div class="row">${extra}</div>
    </div>`;
  return c;
}

function fill(id, items, extraFn) {
  const box = document.getElementById(id);
  box.innerHTML = "";
  if (!items || !items.length) {
    box.append(el("div", "empty", "Nichts gefunden – vermutlich fehlen noch Store-Daten oder Sammelläufe."));
    return;
  }
  items.forEach((g) => box.append(gameCard(g, extraFn ? extraFn(g) : "")));
}

async function loadIdeas() {
  const [rec, disc] = await Promise.all([api("/api/recommendations?limit=12"), api("/api/discover?limit=18")]);
  fill("recReady", rec.ready_to_play, (g) =>
    `${g.is_coop ? '<span class="chip co">Koop</span>' : ""}<span class="chip">${g.days_since ? `zuletzt vor ${g.days_since} Tagen` : "nie gespielt"}</span>`);
  fill("recAlmost", rec.almost_there, (g) =>
    `<span class="chip">${hours(g.total_minutes)} in der Gruppe</span>${g.price_cents ? `<span class="chip">${euro(g.price_cents)}</span>` : ""}`);
  fill("recGems", rec.backlog_gems, (g) =>
    `<span class="chip">${g.owners} Besitzer</span>${g.metacritic ? `<span class="chip co">Metascore ${g.metacritic}</span>` : ""}`);
  fill("recTrending", rec.trending, (g) => `<span class="chip co">${hours(g.minutes)} in 14 Tagen</span>`);
  fill("discover", disc, (g) =>
    `<span class="chip">${g.players[0]}–${g.players[1]} Spieler</span>${g.owners ? `<span class="chip co">${g.owners} haben es</span>` : ""}`);
}

/* ------------------------------------------------------ errungenschaften */

const pctClass = (p) => (p <= 2 ? "legendary" : p <= 10 ? "rare" : "normal");

function achRow(a) {
  return el("div", "ach", `
    <img src="${esc(a.icon || "")}" alt="" loading="lazy">
    <div class="t">
      <b>${esc(a.display || "?")}</b>
      <span>${esc(a.player)} · ${esc(a.game)} · ${a.unlocktime ? relTime(a.unlocktime) : ""}</span>
    </div>
    <span class="pct ${pctClass(a.global_pct ?? 100)}">${a.global_pct != null ? a.global_pct.toFixed(1) + " %" : ""}</span>`);
}

async function loadAchievements() {
  const [rare, recent, comp] = await Promise.all([
    api("/api/achievements/rare?limit=40"),
    api("/api/achievements/recent?limit=40"),
    api("/api/achievements/completion?limit=40"),
  ]);
  const r1 = document.getElementById("rareAch");
  const r2 = document.getElementById("recentAch");
  r1.innerHTML = ""; r2.innerHTML = "";
  if (!rare.length) r1.append(el("div", "empty", "Noch keine Achievement-Daten – der erste Sammellauf braucht dafür etwas."));
  rare.forEach((a) => r1.append(achRow(a)));
  if (!recent.length) r2.append(el("div", "empty", "Noch nichts freigeschaltet erfasst."));
  recent.forEach((a) => r2.append(achRow(a)));

  const wrap = document.getElementById("completion");
  wrap.innerHTML = "";
  if (!comp.length) { wrap.append(el("div", "empty", "Keine Daten.")); return; }
  const t = el("table");
  t.innerHTML = `<thead><tr><th>Spieler</th><th>Spiel</th><th class="num">Fortschritt</th><th>&nbsp;</th><th class="num">Spielzeit</th></tr></thead>`;
  const tb = el("tbody");
  comp.forEach((c) => {
    const tr = el("tr");
    tr.innerHTML = `
      <td>${esc(c.player)}</td>
      <td><div class="gamecell" data-app="${c.appid}"><img src="${iconUrl(c.appid, c.icon)}" alt=""><span class="nm">${esc(c.game)}</span></div></td>
      <td class="num">${c.unlocked}/${c.total}</td>
      <td><div class="bar"><i style="width:${c.pct}%"></i></div></td>
      <td class="num">${hours(c.minutes)}</td>`;
    tb.append(tr);
  });
  t.append(tb);
  wrap.append(t);
}

/* -------------------------------------------------------------- ranglisten */

const BOARDS = [
  ["playtime", "Meiste Spielzeit", (v) => hours(v)],
  ["last_14d", "Aktiv in 14 Tagen", (v) => hours(v)],
  ["games", "Größte Bibliothek", (v) => `${num(v)} Spiele`],
  ["backlog", "Pile of Shame", (v) => `${num(v)} ungestartet`],
  ["achievements", "Errungenschaften", (v) => num(v)],
  ["perfect_games", "100 %-Spiele", (v) => num(v)],
  ["library_value", "Bibliothekswert", (v) => euro(v)],
  ["rarest", "Seltenstes Achievement", (v) => `${(v ?? 0).toFixed(2)} %`],
];

async function loadRanks() {
  const [boards, mx, heat] = await Promise.all([api("/api/leaderboards"), api("/api/matrix"), api("/api/heatmap")]);
  const box = document.getElementById("boards");
  box.innerHTML = "";
  BOARDS.forEach(([key, title, fmt]) => {
    const rows = boards[key] || [];
    const b = el("div", "board", `<h2>${esc(title)}</h2>`);
    const ol = el("ol");
    rows.slice(0, 8).forEach((r) => {
      ol.append(el("li", null, `${esc(r.player)}<span>${esc(fmt(r.value))}</span>`));
    });
    if (!rows.length) b.append(el("div", "empty", "keine Daten"));
    b.append(ol);
    box.append(b);
  });

  // Overlap-Matrix
  const m = document.getElementById("matrix");
  m.innerHTML = "";
  if (!mx.players.length) { m.append(el("div", "empty", "keine Spieler")); }
  else {
    const t = el("table");
    const max = Math.max(...mx.cells.flat(), 1);
    let head = "<thead><tr><th></th>";
    mx.players.forEach((p) => (head += `<th class="num">${esc(p.name)}</th>`));
    t.innerHTML = head + "</tr></thead>";
    const tb = el("tbody");
    mx.players.forEach((p, i) => {
      const tr = el("tr");
      let html = `<th>${esc(p.name)}</th>`;
      mx.cells[i].forEach((v, j) => {
        const alpha = i === j ? 0.06 : Math.min(v / max, 1) * 0.55 + 0.05;
        html += `<td style="background:rgba(102,192,244,${alpha.toFixed(2)})">${num(v)}</td>`;
      });
      tr.innerHTML = html;
      tb.append(tr);
    });
    t.append(tb);
    m.append(t);
  }

  // Stunden-Heatmap
  const h = document.getElementById("heatmap");
  h.innerHTML = "";
  if (!heat.players.length) { h.append(el("div", "empty", "Noch keine Achievement-Zeitstempel erfasst.")); return; }
  const t2 = el("table");
  let head2 = "<thead><tr><th></th>";
  heat.hours.forEach((x) => (head2 += `<th class="num">${x}</th>`));
  t2.innerHTML = head2 + "</tr></thead>";
  const tb2 = el("tbody");
  heat.players.forEach((p) => {
    const mx2 = Math.max(...p.data, 1);
    const tr = el("tr");
    let html = `<th>${esc(p.player)}</th>`;
    p.data.forEach((v) => {
      const alpha = v ? (v / mx2) * 0.7 + 0.1 : 0.03;
      html += `<td style="background:rgba(164,208,7,${alpha.toFixed(2)})" title="${v} Unlocks">${v || ""}</td>`;
    });
    tr.innerHTML = html;
    tb2.append(tr);
  });
  t2.append(tb2);
  h.append(t2);
}

/* -------------------------------------------------------------- abstimmung */

async function loadVotes() {
  const search = document.getElementById("voteSearch");
  if (!search.dataset.bound) {
    search.dataset.bound = "1";
    search.addEventListener("input", debounce(async () => {
      const q = search.value.trim();
      const box = document.getElementById("voteSuggest");
      box.innerHTML = "";
      if (q.length < 2) return;
      const rows = await api(`/api/library?search=${encodeURIComponent(q)}&min_owners=1&limit=8`);
      rows.forEach((g) => {
        const s = el("div", "s", `<img src="${iconUrl(g.appid, g.icon)}" width="24" height="24" alt=""> ${esc(g.name)} <span class="hint">${g.owners} Besitzer</span>`);
        s.onclick = () => sendVote(g.appid, 1);
        box.append(s);
      });
    }, 300));
  }
  renderVotes(await api("/api/votes"));
}

async function sendVote(appid, value) {
  if (!state.me) { alert("Bitte oben rechts auswählen, wer du bist."); return; }
  const r = await fetch("/api/votes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ steamid: state.me, appid, value }),
  });
  if (!r.ok) { alert("Konnte nicht abstimmen."); return; }
  document.getElementById("voteSuggest").innerHTML = "";
  document.getElementById("voteSearch").value = "";
  renderVotes(await r.json());
}

function renderVotes(rows) {
  const list = document.getElementById("voteList");
  list.innerHTML = "";
  if (!rows.length) { list.append(el("div", "empty", "Noch keine Vorschläge – oben ein Spiel suchen.")); return; }
  const myName = state.players.find((p) => p.steamid === state.me)?.name;
  rows.forEach((v) => {
    const yes = (v.yes_names || "").split(",").filter(Boolean);
    const no = (v.no_names || "").split(",").filter(Boolean);
    const row = el("div", "vote-row", `
      <img src="${headerUrl(v.appid, v.header_image)}" alt="" loading="lazy">
      <div class="info">
        <div><b>${esc(v.name)}</b></div>
        <div class="hint">${yes.length ? "dafür: " + yes.map(esc).join(", ") : ""}${no.length ? " · dagegen: " + no.map(esc).join(", ") : ""}</div>
      </div>
      <span class="score ${v.score > 0 ? "pos" : v.score < 0 ? "neg" : ""}">${v.score > 0 ? "+" : ""}${v.score}</span>`);
    const up = el("button", "vbtn" + (myName && yes.includes(myName) ? " on" : ""), "👍");
    const down = el("button", "vbtn down" + (myName && no.includes(myName) ? " on" : ""), "👎");
    up.onclick = () => sendVote(v.appid, myName && yes.includes(myName) ? 0 : 1);
    down.onclick = () => sendVote(v.appid, myName && no.includes(myName) ? 0 : -1);
    row.append(up, down);
    list.append(row);
  });
}

/* ------------------------------------------------------------------ modal */

document.addEventListener("click", async (e) => {
  const t = e.target.closest("[data-app]");
  if (!t) return;
  if (e.target.closest(".vbtn")) return;
  openGame(t.dataset.app);
});
document.getElementById("modalClose").onclick = () => (document.getElementById("modal").hidden = true);
document.getElementById("modal").addEventListener("click", (e) => {
  if (e.target.id === "modal") document.getElementById("modal").hidden = true;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") document.getElementById("modal").hidden = true;
});

async function openGame(appid) {
  const body = document.getElementById("modalBody");
  body.innerHTML = '<div class="empty">lade …</div>';
  document.getElementById("modal").hidden = false;
  let g;
  try {
    g = await api(`/api/game/${appid}`);
  } catch {
    body.innerHTML = '<div class="empty">Zu diesem Spiel liegen keine Daten vor.</div>';
    return;
  }
  const owners = g.owners.map((o) =>
    `<tr><td>${esc(o.player)}</td><td class="num">${hours(o.minutes)}</td><td class="num">${o.last_played ? relTime(o.last_played) : "–"}</td></tr>`).join("");
  const ach = g.achievements.map((a) =>
    `<tr><td>${esc(a.player)}</td><td class="num">${a.unlocked}/${a.total}</td>
     <td><div class="bar"><i style="width:${a.total ? (100 * a.unlocked / a.total).toFixed(0) : 0}%"></i></div></td></tr>`).join("");

  body.innerHTML = `
    <img src="${headerUrl(g.appid, g.header_image)}" alt="" style="width:100%;border-radius:8px;margin-bottom:.8rem">
    <h2>${esc(g.name)}</h2>
    <p class="hint">${esc(g.short_desc || "")}</p>
    <p>
      ${(g.genres || []).map((x) => `<span class="chip">${esc(x)}</span>`).join("")}
      ${g.is_coop ? '<span class="chip co">Koop</span>' : ""}
      ${g.is_pvp ? '<span class="chip">PvP</span>' : ""}
      ${g.metacritic ? `<span class="chip co">Metascore ${g.metacritic}</span>` : ""}
      ${g.price_cents ? `<span class="chip">${euro(g.price_cents)}</span>` : ""}
      ${g.release_date ? `<span class="chip">${esc(g.release_date)}</span>` : ""}
    </p>
    <h3>Wer spielt es</h3>
    <table><thead><tr><th>Spieler</th><th class="num">Spielzeit</th><th class="num">zuletzt</th></tr></thead><tbody>${owners}</tbody></table>
    ${ach ? `<h3 style="margin-top:1rem">Errungenschaften</h3><table><tbody>${ach}</tbody></table>` : ""}
    <p style="margin-top:1rem"><a href="https://store.steampowered.com/app/${g.appid}" target="_blank" rel="noopener">Im Steam-Store öffnen ↗</a></p>`;
}

/* ------------------------------------------------------------------ chart */

function drawLineChart(host, legendHost, data) {
  host.innerHTML = "";
  legendHost.innerHTML = "";
  if (!data.series.length) {
    host.append(el("div", "empty", "Noch keine Zeitreihe – die entsteht erst durch wiederholte Sammelläufe."));
    return;
  }
  const W = 800, H = 220, padL = 38, padB = 22, padT = 10, padR = 8;
  const n = data.labels.length;
  const max = Math.max(10, ...data.series.flatMap((s) => s.data));
  const x = (i) => padL + (i * (W - padL - padR)) / Math.max(n - 1, 1);
  const y = (v) => H - padB - (v / max) * (H - padB - padT);

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");

  let html = "";
  for (let g = 0; g <= 4; g++) {
    const v = (max / 4) * g;
    html += `<line class="grid-line" x1="${padL}" y1="${y(v)}" x2="${W - padR}" y2="${y(v)}"/>
             <text class="axis" x="4" y="${y(v) + 3}">${Math.round(v / 60)} h</text>`;
  }
  const step = Math.ceil(n / 8);
  data.labels.forEach((lb, i) => {
    if (i % step) return;
    const d = lb.slice(8) + "." + lb.slice(5, 7) + ".";
    html += `<text class="axis" x="${x(i)}" y="${H - 6}" text-anchor="middle">${d}</text>`;
  });

  data.series.forEach((s, si) => {
    const color = PALETTE[si % PALETTE.length];
    const pts = s.data.map((v, i) => `${x(i)},${y(v)}`).join(" ");
    html += `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2"
              stroke-linejoin="round" stroke-linecap="round"/>`;
    s.data.forEach((v, i) => {
      if (v > 0) html += `<circle cx="${x(i)}" cy="${y(v)}" r="2.5" fill="${color}"><title>${esc(s.player)}: ${hours(v)} am ${esc(data.labels[i])}</title></circle>`;
    });
    legendHost.append(el("span", null, `<i style="background:${color}"></i>${esc(s.player)}`));
  });
  svg.innerHTML = html;
  host.append(svg);
}

/* ------------------------------------------------------------------- misc */

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function renderWhoami() {
  const sel = document.getElementById("whoami");
  sel.innerHTML = '<option value="">– niemand –</option>';
  state.players.forEach((p) => sel.add(new Option(p.name, p.steamid)));
  sel.value = state.me;
  sel.onchange = () => {
    state.me = sel.value;
    localStorage.setItem("me", state.me);
    if (state.loaded.vote) loadVotes();
  };
}

loadDashboard().catch((err) => {
  document.getElementById("lastRun").textContent = "Backend nicht erreichbar";
  console.error(err);
});
