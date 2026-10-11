let CH = {};
let lastSeq = -1;
const $root = document.getElementById("root");
const ROLE = { TOP: "Top", JUNGLE: "Jungle", MIDDLE: "Mid", BOTTOM: "Bot", UTILITY: "Support" };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const DMG = { AD: "physical (AD)", AP: "magic (AP)", MIX: "mixed AD/AP" };
const img = (id) => (CH[id] ? `<img class="dmg-${CH[id].dmg}" src="${CH[id].img}" alt="${esc(CH[id].name)}" title="${esc(CH[id].name)} — ${DMG[CH[id].dmg] || ""}">` : "");
const nm = (id) => esc(CH[id]?.name || id);
const post = (url) => fetch(url, { method: "POST" }).then(() => (lastSeq = -1));

let fails = 0;
async function poll() {
  try {
    const s = await (await fetch("/api/state")).json();
    fails = 0;
    if (s.seq !== lastSeq) {
      lastSeq = s.seq;
      LAST = s;
      render(s);
    }
  } catch (e) {
    if (++fails === 4) appGone();
  }
  setTimeout(poll, 500);
}

function appGone() {
  lastSeq = -1;
  document.getElementById("conn").textContent = "app closed";
  $root.innerHTML = `<div class="center"><h1 style="font-size:18px">PICKBANS isn't running</h1>
    <div class="muted">Close this window and double-click PICKBANS.exe again.</div></div>`;
}

async function boot() {
  try {
    CH = await (await fetch("/api/champs")).json();
    poll();
  } catch (e) {
    appGone();
    setTimeout(boot, 2000);
  }
}

function header(s) {
  document.getElementById("patch").textContent = s.patch ? `patch ${s.patch}` : "";
  const c = document.getElementById("conn");
  if (s.demo) { c.textContent = "DEMO"; c.className = "pill demo"; }
  else if (s.status === "no_client") { c.textContent = "League not open"; c.className = "pill"; }
  else { c.textContent = "connected"; c.className = "pill ok"; }
}

function render(s) {
  header(s);
  if (s.status === "champ_select" && s.recs) return ($root.innerHTML = champSelect(s) + foot(s));
  if (s.status === "assessment" && s.assessment) return ($root.innerHTML = assessment(s.assessment, s.live) + foot(s));
  $root.innerHTML = idle(s) + foot(s);
}

function foot(s) {
  const demo = s.demo ? `<a onclick="post('/api/demo/stop')">Exit demo</a>` : `<a onclick="post('/api/demo/start')">Try the demo</a>`;
  const meta = s.meta_source === "baseline" ? " · meta: baseline list" : s.meta_source ? ` · stats: ${esc(s.meta_source)}` : "";
  const upd = s.update ? `<div class="update">New version ${esc(s.update.version)} available${s.update.url ? ` — <a href="${esc(s.update.url)}" target="_blank">download</a>` : ""}</div>` : "";
  return `<div class="foot">${upd}<div class="legend"><i class="dmg-AD"></i>AD <i class="dmg-AP"></i>AP <i class="dmg-MIX"></i>mixed</div>${demo} · v${esc(s.version)}${meta}</div>`;
}

let LAST = null;       // last state, so clicks can re-render without waiting for the server
let nbChamp = null;    // champion selected in the matchup notebook
let factIdx = 0;
let quizOpen = false;
const rerender = () => LAST && render(LAST);
function pickNb(id) { nbChamp = id; rerender(); }
function nextFact() { factIdx++; quizOpen = false; rerender(); }
function answerQuiz() { quizOpen = true; rerender(); }
const pct = (x) => Math.round(x * 100);
const ago = (t) => { const h = (Date.now() / 1000 - t) / 3600; return h < 1 ? "now" : h < 24 ? `${Math.round(h)}h` : `${Math.round(h / 24)}d`; };

function idle(s) {
  const p = s.profile, h = s.home;
  const btn = s.status === "no_client" && !s.demo ? `<p><button class="primary" onclick="post('/api/demo/start')">Try the demo</button></p>` : "";
  let html = `<div class="home-head"><div><b>${esc(s.message || "Waiting…")}</b>${p && p.name ? `<div class="muted">Hi ${esc(p.name)}${p.main_role ? ` · mostly ${ROLE[p.main_role] || p.main_role}` : ""}</div>` : ""}</div></div>${btn}`;
  if (!h) return html + `<div class="center muted">${p && p.name ? "Reading your games…" : ""}${s.pack_msg ? `<div style="font-size:12px">${esc(s.pack_msg)}</div>` : ""}</div>`;

  if (h.recent.length) {
    const wins = h.recent.filter((g) => g.win).length;
    html += `<h2>Recent games <small>${wins}W ${h.recent.length - wins}L</small></h2><div class="recent">` + h.recent.map((g) =>
      `<div class="rg ${g.win ? "w" : "l"}" title="${g.k}/${g.d}/${g.a} · ${ago(g.t)} ago">${img(g.champ)}
        <div class="rvs">${g.vs ? img(g.vs) : ""}</div><div class="rk">${g.k}/${g.d}/${g.a}</div></div>`).join("") + `</div>`;
  }
  if (h.facts.length) html += factCard(h.facts[factIdx % h.facts.length]);
  if (h.pool.length) html += notebook(h);
  return html;
}

function factCard(f) {
  let body;
  if (f.kind === "quiz") {
    const [a, b] = f.ids;
    body = quizOpen
      ? `<div class="quiz">${img(f.winner)}<div><b>${nm(f.winner)}</b> wins ${f.wr}% of the time.</div></div>`
      : `<div class="quiz-q">${f.role}: who wins the lane?</div><div class="quiz">
          <button onclick="answerQuiz()">${img(a)} ${nm(a)}</button><span class="muted">vs</span><button onclick="answerQuiz()">${img(b)} ${nm(b)}</button></div>`;
  } else {
    body = `<div class="quiz">${f.ids.map(img).join("")}<div>${esc(f.text)}</div></div>`;
  }
  return `<h2>Did you know? <small><a onclick="nextFact()">next →</a></small></h2><div class="fact">${body}</div>`;
}

function mline(m, mine) {
  const wr = m.wr;
  const cls = wr === null || wr === undefined ? "" : wr >= 0.515 ? "good" : wr <= 0.485 ? "bad" : "even";
  const stat = wr === null || wr === undefined ? `<span class="muted">no stats</span>` : `<span class="${cls}">${pct(wr)}%</span>`;
  const you = mine ? `<span class="rec ${m.w * 2 > m.g ? "good" : m.w * 2 < m.g ? "bad" : ""}">${m.w}W ${m.g - m.w}L</span>` : "";
  return `<div class="nrow">${img(m.vs)}<span class="nname">${nm(m.vs)}</span>${you}${stat}</div>`;
}

function notebook(h) {
  if (!nbChamp || !h.notebook[nbChamp]) nbChamp = h.pool[0].id;
  const nb = h.notebook[nbChamp];
  const me = h.pool.find((x) => x.id === nbChamp);
  const tabs = h.pool.map((x) => `<div class="ntab ${x.id === nbChamp ? "on" : ""}" onclick="pickNb('${x.id}')">${img(x.id)}</div>`).join("");
  const head = `<div class="nhead"><b>${nm(nbChamp)}</b> <span class="muted">${ROLE[nb.role] || ""}</span>
      <span class="grade-inline ${me.tier}">${me.tier}</span>${me.wr ? `<span class="muted">${pct(me.wr)}% wins</span>` : ""}
      ${me.games ? `<span class="muted">· you ${me.wins}W ${me.games - me.wins}L</span>` : ""}</div>`;
  const mine = nb.mine.length ? `<div class="nsub">Your games</div>` + nb.mine.map((m) => mline(m, true)).join("") : `<div class="nsub muted">No games logged on ${nm(nbChamp)} yet.</div>`;
  const stats = nb.best.length
    ? `<div class="ncols"><div><div class="nsub good">Good lanes</div>${nb.best.map((m) => mline(m)).join("")}</div>
        <div><div class="nsub bad">Hard lanes</div>${nb.worst.map((m) => mline(m)).join("")}</div></div>`
    : `<div class="nsub muted">No matchup stats for this lane yet.</div>`;
  return `<h2>Matchup notebook <small>% = win rate, all players</small></h2><div class="ntabs">${tabs}</div><div class="nb">${head}${mine}${stats}</div>`;
}

function card(r, opts = {}) {
  const c = CH[r.id] || {};
  const g = opts.noGrade ? "" : `<div class="grade ${r.grade}">${r.grade}</div>`;
  return `<div class="card ${opts.noGrade ? "" : r.grade}">${g}
    <div class="top">${img(r.id)}<div style="min-width:0"><div class="name">${nm(r.id)}</div><div class="style">${esc((c.styles || []).join(" · "))}</div></div></div>
    <div class="why">${(r.reasons || []).map(esc).join("<br>")}</div></div>`;
}

function section(title, list, empty, hint = "", opts = {}) {
  const body = list && list.length ? `<div class="cards">${list.map((r) => card(r, opts)).join("")}</div>` : `<div class="empty">${empty}</div>`;
  return `<h2>${title}<small>${hint}</small></h2>${body}`;
}

function champSelect(s) {
  const d = s.draft, r = s.recs;
  const me = d.allies.find((a) => a.is_me) || {};
  const role = ROLE[r.role] || r.role;
  let banner;
  if (d.phase === "FINALIZATION") banner = `<div class="banner"><b>Draft locked</b><span class="muted">Assessment below ↓</span></div>`;
  else if (d.my_action === "ban") banner = `<div class="banner turn"><b>Your turn to BAN</b><span class="muted">${role}</span></div>`;
  else if (d.my_action === "pick") banner = `<div class="banner turn"><b>Your turn to PICK</b><span class="muted">${role}</span></div>`;
  else banner = `<div class="banner"><b>${d.phase === "PLANNING" ? "Planning" : "Champ select"}</b><span class="muted">You: ${role}${r.role_guessed ? " (guessed)" : ""}</span></div>`;

  const slot = (p, isAlly) => {
    const id = p.champ || p.hover;
    return `<div class="slot ${p.champ ? "" : "hover"} ${p.is_me ? "me" : ""}">${id ? img(id) : ""}<div class="r">${ROLE[p.role] || ""}${p.role_guessed ? "?" : ""}</div></div>`;
  };
  const teams = `<div class="teams">
    <div class="team"><div class="lbl">Your team</div><div class="slots">${d.allies.map((p) => slot(p, true)).join("")}</div></div>
    <div class="team"><div class="lbl">Enemy team</div><div class="slots">${d.enemies.map((p) => slot(p, false)).join("")}</div></div>
  </div>${d.bans.length ? `<div class="bans">${d.bans.map(img).join("")}</div>` : ""}`;

  const missing = r.missing.filter((m) => m.missing);
  const covered = r.missing.filter((m) => !m.missing && m.ratio >= 0.8);
  const chips = `<div class="chips"><span class="k">Missing</span>${missing.length ? missing.map((m) => `<span class="chip miss">${esc(m.label)}</span>`).join("") : `<span class="chip">${d.allies.some((a) => a.champ || a.hover) ? "nothing big" : "—"}</span>`}
    ${covered.map((m) => `<span class="chip ok">${esc(m.label)} ✓</span>`).join("")}</div>
    ${r.enemy_tags.length ? `<div class="chips"><span class="k">They have</span>${r.enemy_tags.map((t) => `<span class="chip enemy">${esc(t)}</span>`).join("")}</div>` : ""}`;

  const picking = !me.champ;
  const banPhase = d.my_action === "ban" || (d.bans.length < 10 && !d.enemies.some((e) => e.champ) && !d.allies.some((a) => a.champ));
  let html = banner + teams + chips;
  if (picking && banPhase) html += `<div class="bans-rec">${section("Ban recs", r.bans, "Nothing scary to ban for you.", "", { noGrade: true })}</div>`;
  if (picking) {
    html += section("Comfy picks", r.comfy, "No comfort champs available for this role.", "what you play");
    html += section("Ideal picks", r.ideal, "No picks available.", "you + both teams + bans");
    html += section("Lane counter", r.counter, r.opponent ? `No strong counter to ${nm(r.opponent)} — go comfy.` : "Waiting for your lane opponent to lock…", r.opponent ? `vs ${nm(r.opponent)}` : "");
    if (r.cheese.length) html += section("Cheese ?", r.cheese, "", "oh btw");
  }
  if (r.my_pick) html += myPick(r.my_pick, r.opponent, !!me.champ);
  if (s.assessment) html += `<h2>Match assessment</h2>` + assessmentBody(s.assessment, null);
  return html;
}

function myPick(p, opp, locked) {
  return `<div class="mypick"><div class="row">${img(p.id)}<div><div class="name" style="font-weight:700">${locked ? "" : "Hovering: "}${nm(p.id)}</div>
    <div class="styles">${p.styles.map((x) => `<span>${esc(x)}</span>`).join("")}</div></div></div>
    <div class="muted" style="font-size:11px;margin-top:6px">Playstyle — pick the matching build in your build tool</div>
    ${p.play ? `<p><b>How to play:</b> ${esc(p.play)}</p>` : ""}
    ${opp && p.vs ? `<p><b>vs ${nm(opp)}:</b> ${esc(p.vs)}</p>` : ""}
    ${p.lane_why ? `<p class="muted">${esc(p.lane_why)}</p>` : ""}</div>`;
}

function assessment(a, live) {
  const clock = live ? `<span class="pill">${esc(live.clock)} · ${esc(live.phase.toLowerCase())}</span>` : `<span class="muted">loading screen</span>`;
  return `<div class="ig-head"><b>${live ? "In game" : "Match assessment"}</b>${clock}</div>` + assessmentBody(a, live);
}

function mrow(m) {
  const cls = m.mine ? "mine" : "";
  const s = m.score;
  let bar = `<div class="bar"></div>`;
  if (s !== null && s !== undefined) {
    const w = Math.max(3, Math.round(Math.abs(s) * 50));
    const color = Math.abs(s) < 0.15 ? "even" : s > 0 ? "good" : "bad";
    const style = s >= 0 ? `right:50%;width:${w}%` : `left:50%;width:${w}%`;
    bar = `<div class="bar"><i class="${color}" style="${style}"></i></div>`;
  }
  const c2 = s === null || s === undefined || Math.abs(s) < 0.15 ? "even" : s > 0 ? "good" : "bad";
  const wr = m.wr === null || m.wr === undefined ? "" : `${m.wr}%`;
  return `<div class="mrow ${cls}"><span class="lab">${ROLE[m.role]}</span>
    <div class="ic">${m.ally ? img(m.ally) : ""}</div>${bar}<div class="ic">${m.enemy ? img(m.enemy) : ""}</div>
    <span class="mw ${c2}" title="your side's win rate in this lane, all players">${wr}</span></div>`;
}

function assessmentBody(a, live) {
  const tags = a.tags.map((t) => `<span class="chip ${t.kind === "bad" ? "miss" : t.kind === "good" ? "ok" : "enemy"}">${esc(t.text)}</span>`).join("");
  let h = `<div class="plan"><b>${esc(a.headline)}.</b> ${esc(a.plan)}</div>${tags ? `<div class="chips">${tags}</div>` : ""}`;

  h += `<h2>Matchups <small>green = your side wins the lane · % = your side</small></h2>` + a.matchups.map(mrow).join("");
  const bot = a.matchups.find((m) => m.duo !== undefined);
  if (bot) {
    const v = bot.duo >= 0.2 ? ["good", "favored"] : bot.duo <= -0.2 ? ["bad", "tough"] : ["even", "even"];
    h += `<div class="duo">Bot 2v2: <span class="${v[0]}">${v[1]}</span></div>`;
  }

  if (a.traps.length)
    h += `<h2>Watch out</h2>` + a.traps.map((t) => `<div class="trap">${img(t.id)}<div><b>${esc(t.head)}</b>${t.tail ? ` <span class="muted">· ${esc(t.tail)}</span>` : ""}</div></div>`).join("");

  h += `<h2>Now</h2><div class="live">${nowBox(a, live)}</div>`;
  return h;
}

function nowBox(a, live) {
  const L = a.lane;
  const laneLine = L ? `<div class="now-lane">${img(L.me)}<span>vs</span>${L.opps.map(img).join("")}
      <span class="verdict ${L.verdict || ""}">${esc({ good: "favored", hard: "tough", even: "even" }[L.verdict] || "")}</span></div>
      ${L.tip ? `<div>${esc(L.tip)}</div>` : ""}${L.vs ? `<div class="muted">vs ${nm(L.opps[L.opps.length - 1])}: ${esc(L.vs)}</div>` : ""}` : "";
  if (!live) return laneLine || `<div class="muted">Waiting for the game to start…</div>`;
  let h = live.alerts.map((x) => `<div class="alert ${x.kind}">${img(x.id)}<span>${esc(x.text)}</span></div>`).join("");
  h += live.objectives.map((o) => `<div class="obj ${o.soon ? "soon" : ""}">${esc(o.text)}</div>`).join("");
  h += `<div style="margin-top:6px">${esc(live.advice)}</div>`;
  if (live.phase === "Laning") h += `<div class="sep"></div>` + laneLine;
  h += `<div class="muted score">Kills ${live.score[0]} – ${live.score[1]}</div>`;
  return h;
}

boot();
