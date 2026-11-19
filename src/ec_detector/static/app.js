// Interface de démonstration. Elle AFFICHE le JSON renvoyé par l'API :
// aucune règle, aucun seuil, aucun statut n'est calculé ici.
"use strict";

const ACTIONS = {
  CONTINUER: "Continuer automatiquement",
  MISE_EN_ATTENTE: "Mise en attente",
  RELECTURE_JURISTE: "Relecture juriste",
};
const ACTION_HINT = {
  CONTINUER: "Aucune CE détectée, données complètes : le dossier avance sans humain.",
  MISE_EN_ATTENTE: "CE probable qui couvre le retard : dossier suspendu, preuves enregistrées.",
  RELECTURE_JURISTE: "Doute, ou CE qui n'explique qu'une partie du retard : un juriste tranche.",
};
const STATUSES = { EC_PROBABLE: "CE probable", AUCUNE: "Aucune CE", INCERTAIN: "Incertain" };
const TYPES = { METEO: "Météo", GREVE_ATC: "Grève ATC" };
const OUTCOMES = { CORRECT: "Correct", RENVOYE: "Renvoyé au juriste", FAUX: "Faux" };
const STRIKE_RULES = {
  "strike.confirmed_airport": "Grève confirmée à cet aéroport",
  "strike.zone_only": "Grève dans la zone, aéroport non confirmé",
  "strike.announced": "Préavis non confirmé",
};

const state = { meta: null, cases: [], filter: "ALL", selected: null, evalLoaded: false };

// ---------- Utilitaires DOM (texte uniquement, jamais innerHTML) ----------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "style") node.setAttribute("style", v);
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}

function safeLink(url) {
  try {
    const u = new URL(url);
    if (u.protocol === "https:") return el("a", { href: u.href, target: "_blank", rel: "noopener noreferrer" }, u.hostname);
  } catch (_) { /* pas une URL */ }
  return el("span", {}, String(url));
}

const pad = (n) => String(n).padStart(2, "0");
const d = (iso) => new Date(iso);
const hhmm = (iso) => { const t = d(iso); return `${pad(t.getUTCHours())}:${pad(t.getUTCMinutes())}Z`; };
const ddmm = (iso) => { const t = d(iso); return `${pad(t.getUTCDate())}/${pad(t.getUTCMonth() + 1)}`; };
const day = (iso) => { const t = d(iso); return `${ddmm(iso)}/${t.getUTCFullYear()}`; };
const stamp = (iso) => `${ddmm(iso)} ${hhmm(iso)}`;
const mins = (m) => (m >= 60 ? `${Math.floor(m / 60)} h ${pad(m % 60)}` : `${m} min`);

async function api(path, options) {
  const resp = await fetch(path, options);
  const body = await resp.json().catch(() => null);
  if (!resp.ok) {
    let msg = `Erreur ${resp.status}`;
    if (body && typeof body.detail === "string") msg = body.detail;
    else if (body && Array.isArray(body.detail)) {
      msg = body.detail.map((e) => `${(e.loc || []).slice(1).join(".")} : ${e.msg}`).join(" · ");
    }
    throw new Error(msg);
  }
  return body;
}

const actionPill = (action, big) =>
  el("span", { class: `pill a-${action}${big ? " action-big" : ""}` }, ACTIONS[action] || action);

// ---------- Rendu d'une décision ----------

function renderDecision(container, dec, extra = {}) {
  container.replaceChildren();
  const f = dec.flight;

  // En-tête : l'action d'abord, puis le statut.
  const types = (dec.ec_types || []).map((t) => el("span", { class: "tag" }, TYPES[t] || t));
  container.append(el("div", { class: "panel hero", "data-ref": "D1" },
    el("div", { class: "hero-top" },
      el("div", {},
        el("div", { class: "title" }, dec.case_id),
        el("div", { class: "flightline", "data-ref": "V1" },`${f.number} · ${f.departure} → ${f.arrival} · ${day(f.scheduled_departure)}`)),
      actionPill(dec.action, true)),
    el("p", { class: "note" }, ACTION_HINT[dec.action] || ""),
    el("div", { class: "facts" },
      fact("Statut", STATUSES[dec.status] || dec.status, types.length ? types : null),
      fact("Confiance", dec.confidence.toFixed(2), "niveau fixé par règle, pas une probabilité"),
      fact("Retard à l'arrivée", mins(dec.delay_total_minutes)),
      fact("Imputable à la CE", mins(dec.delay_explained_minutes), "estimation"),
      fact("Retard restant", mins(dec.remaining_delay_minutes)))));

  container.append(delayPanel(dec));
  container.append(timelinePanel(dec));

  container.append(el("div", { class: "panel" },
    el("h3", {}, "Pourquoi"),
    el("ul", { class: "reasons" }, dec.reasons.map((r, i) =>
      el("li", { "data-ref": `R${i + 1}` }, el("span", { class: "refid" }, `R${i + 1}`), " ", r)))));

  container.append(notePanel(container, dec));
  container.append(evidencePanel(dec));

  if (extra.description) {
    container.append(el("div", { class: "panel" },
      el("h3", {}, "Contexte du dossier de démonstration"),
      el("p", { style: "margin:0 0 8px" }, extra.description),
      extra.sources && extra.sources.length
        ? el("div", { class: "foot" }, "Sources :", extra.sources.map(safeLink))
        : el("div", { class: "foot" }, "Pas d'événement à sourcer : la preuve est l'absence de signal.")));
  }

  container.append(el("div", { class: "panel" },
    el("details", { class: "raw" },
      el("summary", {}, "JSON renvoyé par l'API (stocké sur le dossier)"),
      el("pre", {}, JSON.stringify(dec, null, 2))),
    el("div", { class: "foot", style: "margin-top:10px" },
      el("span", {}, `Régime : ${dec.legal_regime}`),
      el("span", {}, `Règles ${dec.rules_version}`),
      el("span", {}, `Calendrier des grèves ${dec.strike_calendar_version || "indisponible"}`),
      el("span", {}, `Calculé le ${stamp(dec.computed_at)}`))));
}

function fact(k, v, h) {
  return el("div", { class: "fact" }, el("div", { class: "k" }, k), el("div", { class: "v" }, v),
    h ? el("div", { class: "h" }, h) : null);
}

function delayPanel(dec) {
  const total = Math.max(dec.delay_total_minutes, 1);
  const ex = (dec.delay_explained_minutes / total) * 100;
  const threshold = state.meta ? state.meta.compensation_threshold_minutes : null;
  let verdict;
  if (dec.status === "EC_PROBABLE" && dec.fully_explained) {
    verdict = `Retard restant ${mins(dec.remaining_delay_minutes)} : sous le seuil d'indemnisation`
      + (threshold ? ` (${mins(threshold)})` : "") + ". La CE suffit à écarter l'indemnité.";
  } else if (dec.status === "EC_PROBABLE") {
    verdict = `La CE n'explique qu'une partie du retard : il reste ${mins(dec.remaining_delay_minutes)}`
      + (threshold ? `, au-dessus du seuil de ${mins(threshold)}` : "") + ". Le lien est à établir par un juriste.";
  } else {
    verdict = "Aucune minute de retard imputée à une circonstance extraordinaire.";
  }
  const strike = (dec.ec_types || []).includes("GREVE_ATC");
  return el("div", { class: "panel" },
    el("h3", {}, "Retard et minutes imputables"),
    el("div", { class: "delaybar", role: "img",
      "aria-label": `${dec.delay_explained_minutes} minutes imputables sur ${dec.delay_total_minutes}` },
      el("div", { class: "ex", style: `width:${ex}%` }),
      el("div", { class: "rem", style: `width:${100 - ex}%` })),
    el("div", { class: "legend" },
      el("span", {}, el("i", { style: "background:var(--moderate)" }), `Imputable : ${mins(dec.delay_explained_minutes)}`),
      el("span", {}, el("i", { style: "background:var(--severe)" }), `Restant : ${mins(dec.remaining_delay_minutes)}`)),
    el("p", { class: "verdict" }, verdict),
    strike ? el("p", { class: "note" }, "Grève : imputation à la journée, les horaires précis du préavis ne sont pas sourcés.") : null);
}

// ---------- Frise par aéroport ----------

function timelinePanel(dec) {
  const panel = el("div", { class: "panel" }, el("h3", {}, "Chronologie aux aéroports (UTC)"));
  const f = dec.flight;
  for (const a of dec.airports) {
    const dep = a.role === "départ";
    panel.append(timeline(a, dep ? f.scheduled_departure : f.scheduled_arrival,
      dep ? f.actual_departure : f.actual_arrival, dec.evidence.filter((e) => e.airport === a.airport)));
  }
  panel.append(el("div", { class: "legend" },
    el("span", {}, el("i", { style: "background:var(--delay);border:1px solid var(--severe)" }), "Période de retard"),
    el("span", {}, el("i", { style: "background:var(--episode)" }), "Épisode météo"),
    el("span", {}, el("i", { style: "background:var(--strike);opacity:.35" }), "Grève ATC"),
    el("span", {}, el("span", { class: "dot severe" }), " relevé sévère"),
    el("span", {}, el("span", { class: "dot moderate" }), " relevé modéré")));
  return panel;
}

function timeline(a, scheduled, actual, evidence) {
  const W = 720, H = 96, L = 8, R = 8, TRACK_Y = 40, TRACK_H = 24;
  const t0 = d(a.window[0]).getTime();
  const t1 = Math.max(d(a.window[1]).getTime(), d(actual).getTime(), t0 + 3600e3);
  const x = (iso) => {
    const t = Math.min(Math.max(d(iso).getTime(), t0), t1);
    return L + ((t - t0) / (t1 - t0)) * (W - L - R);
  };
  const g = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": `Chronologie ${a.airport}` });

  g.append(svg("rect", { x: L, y: TRACK_Y, width: W - L - R, height: TRACK_H, rx: 4, style: "fill:var(--surface-2);stroke:var(--border)" }));
  // Période de retard
  g.append(svg("rect", { x: x(scheduled), y: TRACK_Y - 6, width: Math.max(1, x(actual) - x(scheduled)), height: TRACK_H + 12,
    style: "fill:var(--delay);stroke:var(--severe);stroke-opacity:.35" }));
  // Grèves
  for (const e of evidence.filter((e) => e.source === "CALENDRIER_GREVES")) {
    const [s, en] = e.strike.period;
    const confirmed = e.rule_id === "strike.confirmed_airport";
    g.append(svg("rect", { x: x(s), y: TRACK_Y, width: Math.max(1, x(en) - x(s)), height: TRACK_H,
      style: `fill:${confirmed ? "var(--strike)" : "var(--strike-doubt)"};opacity:.35` }));
  }
  // Épisode météo
  if (a.is_ec && a.episode) {  // épisode retenu comme CE seulement
    g.append(svg("rect", { x: x(a.episode[0]), y: TRACK_Y, width: Math.max(2, x(a.episode[1]) - x(a.episode[0])), height: TRACK_H,
      style: "fill:var(--episode)" }));
  }
  // Relevés avec signal
  for (const e of evidence.filter((e) => e.source === "METAR")) {
    const severe = (e.signals || []).some((s) => s.severity === "severe");
    g.append(svg("circle", { cx: x(e.observed_at), cy: TRACK_Y + TRACK_H / 2, r: 3.4,
      style: `fill:${severe ? "var(--severe)" : "var(--moderate)"}` },
      svg("title", {}, `${hhmm(e.observed_at)} ${e.raw}`)));
  }
  // Axe horaire
  const spanH = (t1 - t0) / 3600e3;
  const step = Math.max(1, Math.ceil(spanH / 8));
  const first = new Date(t0); first.setUTCMinutes(0, 0, 0);
  for (let t = first.getTime() + 3600e3; t <= t1; t += step * 3600e3) {
    const xi = x(new Date(t).toISOString());
    g.append(svg("line", { x1: xi, x2: xi, y1: TRACK_Y + TRACK_H, y2: TRACK_Y + TRACK_H + 5, style: "stroke:var(--border)" }));
    g.append(svg("text", { x: xi, y: H - 8, "text-anchor": "middle" }, `${pad(new Date(t).getUTCHours())}h`));
  }
  // Repères prévu / réel
  const xs = x(scheduled), xa = x(actual);
  g.append(svg("line", { x1: xs, x2: xs, y1: 18, y2: TRACK_Y + TRACK_H + 4, style: "stroke:var(--muted);stroke-dasharray:3 3" }));
  g.append(svg("line", { x1: xa, x2: xa, y1: 18, y2: TRACK_Y + TRACK_H + 4, style: "stroke:var(--text);stroke-width:1.5" }));
  const close = xa - xs < 110;
  const sameDay = ddmm(scheduled) === ddmm(actual);
  const when = (iso) => (sameDay ? hhmm(iso) : stamp(iso));
  g.append(svg("text", { x: xs, y: 13, "text-anchor": close ? "end" : "middle", class: "lbl" }, `prévu ${when(scheduled)}`));
  g.append(svg("text", { x: Math.min(xa, W - 4), y: 13, "text-anchor": close || xa > W - 60 ? (xa > W - 60 ? "end" : "start") : "middle", class: "lbl" }, `réel ${when(actual)}`));

  const status = a.error ? `source indisponible : ${a.error}`
    : `${a.n_obs} relevés · trou max ${a.max_gap_minutes} min · ${a.data_complete ? "données complètes" : "données incomplètes"}`;
  return el("div", { class: "timeline" },
    el("div", { class: "tl-head" },
      el("strong", {}, `${a.airport} · ${a.role}`),
      el("span", { class: "muted" }, a.is_ec ? `CE météo · ${a.severe_minutes} min sévères, ${a.signal_minutes} min avec signal` : status)),
    g);
}

// ---------- Preuves ----------

function evidencePanel(dec) {
  const strikes = dec.evidence.filter((e) => e.source === "CALENDRIER_GREVES");
  const metars = dec.evidence.filter((e) => e.source === "METAR");
  const panel = el("div", { class: "panel" }, el("h3", {}, `Preuves (${dec.evidence.length})`));
  if (!dec.evidence.length) {
    panel.append(el("p", { class: "note" }, "Aucune preuve de CE : aucun relevé avec signal, aucune grève correspondante."));
    return panel;
  }
  const box = el("div", { class: "evidence" });
  const ref = (e) => `E${dec.evidence.indexOf(e) + 1}`;  // même numérotation que la note
  for (const e of strikes) {
    const s = e.strike;
    box.append(el("div", { class: "ev", "data-ref": ref(e) },
      el("div", { class: "ev-head" },
        el("span", { class: "refid" }, ref(e)),
        el("span", { class: "tag" }, "Calendrier des grèves"),
        el("strong", {}, s.id), el("span", {}, `${e.airport} (${e.role})`),
        el("span", { class: "note" }, STRIKE_RULES[e.rule_id] || e.rule_id)),
      el("div", { class: "foot" },
        el("span", {}, `Du ${stamp(s.period[0])} au ${stamp(s.period[1])}`),
        s.unions.length ? el("span", {}, s.unions.join(", ")) : null,
        el("span", {}, "Source :", s.sources.map(safeLink)))));
  }
  const shown = 6;
  metars.forEach((e, i) => {
    const node = el("div", { class: "ev", "data-ref": ref(e) },
      el("div", { class: "ev-head" },
        el("span", { class: "refid" }, ref(e)),
        el("span", { class: "tag" }, "METAR"),
        el("strong", {}, `${e.airport} · ${stamp(e.observed_at)}`)),
      el("div", { class: "ev-raw" }, e.raw),
      el("div", {}, (e.signals || []).map((s) =>
        el("span", { class: "sig" }, el("span", { class: `dot ${s.severity}` }),
          el("code", {}, s.rule_id), ` ${s.value} (${s.threshold})`))));
    if (i >= shown) node.hidden = true;
    box.append(node);
  });
  panel.append(box);
  if (metars.length > shown) {
    const btn = el("button", { class: "more", type: "button", onclick: () => {
      box.querySelectorAll(".ev[hidden]").forEach((n) => { n.hidden = false; });
      btn.remove();
    } }, `Voir les ${metars.length - shown} autres relevés`);
    panel.append(btn);
  }
  return panel;
}

// ---------- Note pour le juriste (LLM vérifié, D14) ----------
// La note est un TEXTE à côté de la décision : elle ne change ni le statut ni l'action.

function notePanel(container, dec) {
  const model = state.meta && state.meta.note_llm;
  const body = el("div", { class: "note-body" });
  const status = el("span", { class: "form-status", role: "status" });
  const btn = el("button", { class: "btn small primary", type: "button", onclick: async () => {
    btn.disabled = true;
    status.textContent = model ? "Rédaction par le LLM, puis vérification…" : "Génération…";
    try {
      const r = await api("/api/note", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_id: dec.case_id, flight: pickFlight(dec.flight) }) });
      renderNote(container, body, r.note);
      if (r.note.retryable) {  // quota ou réseau : on peut retenter, rien n'a été gardé en cache
        btn.disabled = false;
        btn.textContent = "Réessayer (IA)";
      } else {
        btn.remove();
      }
      status.textContent = "";
    } catch (e) {
      body.replaceChildren(el("div", { class: "error", role: "alert" }, e.message));
      btn.disabled = false;
      status.textContent = "";
    }
  } }, model ? "Rédiger la note (IA)" : "Générer la note (modèle fixe)");

  return el("div", { class: "panel" },
    el("h3", {}, "Note pour le juriste"),
    el("p", { class: "note" }, model
      ? `Rédigée par un LLM (${model}) à partir des seules raisons R et preuves E ci-dessus et ci-dessous. `
        + "Le code vérifie chaque référence et chaque nombre ; sinon, modèle fixe. La note ne modifie pas la décision."
      : "Aucun LLM configuré (MISTRAL_API_KEY) : la note est produite par le modèle fixe."),
    el("div", { class: "form-actions", style: "margin-top:10px" }, btn, status),
    body);
}

function pickFlight(f) {
  const out = {};
  for (const k of ["number", "departure", "arrival", ...FIELDS]) out[k] = f[k];
  return out;
}

function renderNote(container, box, n) {
  const llm = n.source === "LLM";
  const badge = el("div", { class: `note-badge ${llm ? "ok" : "fixed"}` },
    llm ? `Rédigée par IA · ${n.model} · contrôles réussis`
        : `Modèle fixe · ${n.fallback_reason}`);

  const chip = (id) => el("button", { class: "ref", type: "button", title: n.references[id] || id,
    onclick: () => focusRef(container, id) }, id);

  const paras = n.paragraphs.map((p) =>
    el("p", { class: "note-p" }, p.text, " ", el("span", { class: "refs" }, p.refs.map(chip))));

  const rejected = n.llm_problems && n.llm_problems.length
    ? el("details", { class: "raw", open: n.retryable || null },
        el("summary", {}, n.retryable ? "Détail de l'erreur" : "Pourquoi la note du LLM a été rejetée"),
        el("ul", { class: "reasons", style: "margin-top:8px" }, n.llm_problems.map((p) => el("li", {}, p))))
    : null;

  box.replaceChildren(badge, ...paras, rejected,
    el("div", { class: "foot" },
      el("span", {}, `${n.evidence_sent} preuve(s) envoyée(s)`
        + (n.evidence_not_sent ? `, ${n.evidence_not_sent} non envoyée(s)` : "")),
      el("span", {}, "aucune donnée passager"),
      el("span", {}, `générée le ${stamp(n.generated_at)}`)));
}

function focusRef(container, id) {
  const target = container.querySelector(`[data-ref="${id}"]`);
  if (!target) return;
  target.hidden = false;  // preuve au-delà des 6 premières : on l'affiche
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.remove("flash");
  void target.offsetWidth;  // relance l'animation
  target.classList.add("flash");
}

// ---------- File de dossiers ----------

function renderFilters() {
  const counts = { ALL: state.cases.length };
  for (const c of state.cases) counts[c.decision.action] = (counts[c.decision.action] || 0) + 1;
  const keys = ["ALL", "CONTINUER", "MISE_EN_ATTENTE", "RELECTURE_JURISTE"];
  document.getElementById("filters").replaceChildren(...keys.map((k) =>
    el("button", { class: `filter${state.filter === k ? " on" : ""}`, type: "button",
      onclick: () => { state.filter = k; renderFilters(); renderList(); } },
      k === "ALL" ? "Tous" : actionPill(k), el("span", { class: "n" }, counts[k] || 0))));
}

function renderList() {
  const list = document.getElementById("case-list");
  const items = state.cases.filter((c) => state.filter === "ALL" || c.decision.action === state.filter);
  list.replaceChildren(...items.map((c) => {
    const dec = c.decision, f = dec.flight;
    return el("button", { class: `item${state.selected === c.case_id ? " selected" : ""}`, type: "button",
      onclick: () => select(c.case_id) },
      el("span", { class: "route" }, `${f.departure} → ${f.arrival}`),
      actionPill(dec.action),
      el("span", { class: "meta" },
        el("span", {}, day(f.scheduled_departure)),
        el("span", {}, `retard ${mins(dec.delay_total_minutes)}`),
        el("span", {}, STATUSES[dec.status]),
        dec.ec_type ? el("span", {}, TYPES[dec.ec_type]) : null,
        el("span", { class: "mono" }, c.case_id)));
  }));
  if (!items.length) list.append(el("p", { class: "empty" }, "Aucun dossier pour ce filtre."));
}

function select(id) {
  state.selected = id;
  const c = state.cases.find((x) => x.case_id === id);
  renderList();
  renderDecision(document.getElementById("case-detail"), c.decision, c);
  if (window.matchMedia("(max-width: 960px)").matches) {
    document.getElementById("case-detail").scrollIntoView({ behavior: "smooth" });
  }
}

// ---------- Nouveau dossier ----------

const FIELDS = ["scheduled_departure", "scheduled_arrival", "actual_departure", "actual_arrival"];

function fillForm(flight, caseId) {
  const form = document.getElementById("new-form");
  form.number.value = flight.number;
  form.case_id.value = caseId;
  form.departure.value = flight.departure;
  form.arrival.value = flight.arrival;
  for (const k of FIELDS) form[k].value = flight[k].slice(0, 16);  // ISO UTC → datetime-local
}

function renderExamples() {
  const box = document.getElementById("examples");
  const nice = { number: "DEMO01", departure: "LFMN", arrival: "LFBO",
    scheduled_departure: "2025-07-03T10:00", scheduled_arrival: "2025-07-03T11:10",
    actual_departure: "2025-07-03T13:30", actual_arrival: "2025-07-03T14:40" };
  box.replaceChildren("Exemples :",
    el("button", { class: "btn small", type: "button", onclick: () => fillForm(nice, "nice-jour-de-greve") },
      "Nice → Toulouse, jour de grève ATC"),
    el("select", { class: "btn small", "aria-label": "Charger un dossier de la file",
      onchange: (ev) => {
        const c = state.cases.find((x) => x.case_id === ev.target.value);
        if (c) fillForm(c.decision.flight, `${c.case_id}-copie`);
        ev.target.selectedIndex = 0;
      } },
      el("option", { value: "" }, "Copier un dossier de la file…"),
      state.cases.map((c) => el("option", { value: c.case_id }, c.case_id))));
}

async function submitForm(ev) {
  ev.preventDefault();
  const form = ev.target;
  const status = document.getElementById("form-status");
  const btn = document.getElementById("submit-btn");
  const out = document.getElementById("new-detail");
  const flight = {
    number: form.number.value.trim(),
    departure: form.departure.value.trim().toUpperCase(),
    arrival: form.arrival.value.trim().toUpperCase(),
  };
  for (const k of FIELDS) flight[k] = form[k].value ? `${form[k].value}:00Z` : "";  // champs en UTC
  const missing = FIELDS.filter((k) => !flight[k]).length + ["number", "departure", "arrival"].filter((k) => !flight[k]).length;
  if (missing) {
    out.replaceChildren(el("div", { class: "error", role: "alert" },
      "Renseigner le vol, les deux aéroports et les quatre horaires (UTC)."));
    return;
  }
  btn.disabled = true;
  status.textContent = "Analyse en cours… (téléchargement des METAR si besoin)";
  try {
    const dec = await api("/api/decide", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case_id: form.case_id.value.trim() || "dossier", flight }) });
    renderDecision(out, dec);
    status.textContent = "";
  } catch (e) {
    out.replaceChildren(el("div", { class: "error", role: "alert" }, e.message));
    status.textContent = "";
  } finally {
    btn.disabled = false;
  }
}

// ---------- Évaluation ----------

async function loadEval() {
  const box = document.getElementById("eval");
  box.replaceChildren(el("p", { class: "loading" }, "Calcul…"));
  try {
    const r = await api("/api/evaluation");
    const s = r.score, n = s.n, o = s.outcomes;
    const kpi = (k, v, of, h) => el("div", { class: "card kpi" }, el("div", { class: "k" }, k),
      el("div", { class: "v" }, String(v), el("small", {}, ` / ${of}`)), h ? el("div", { class: "h" }, h) : null);
    const statuses = ["EC_PROBABLE", "AUCUNE", "INCERTAIN"];
    const label = (st, t) => `${STATUSES[st]}${t ? " · " + TYPES[t] : ""}`;

    const matrix = el("table", { class: "cm" },
      el("thead", {}, el("tr", {}, el("th", {}, "attendu \\ obtenu"),
        statuses.map((g) => el("th", { class: "num" }, STATUSES[g])))),
      el("tbody", {}, statuses.map((e) => el("tr", {}, el("th", {}, STATUSES[e]),
        statuses.map((g) => el("td", { class: `num${e === g ? " diag" : ""}` }, s.confusion[e][g]))))));

    const detail = el("table", {},
      el("thead", {}, el("tr", {}, ["Dossier", "Attendu", "Obtenu", "Action", "Classe"].map((h) => el("th", {}, h)))),
      el("tbody", {}, r.rows.map((row) => el("tr", {},
        el("td", { class: "mono" }, row.case_id),
        el("td", {}, label(row.expected_status, row.expected_type)),
        el("td", {}, label(row.status, row.ec_type)),
        el("td", {}, actionPill(row.action)),
        el("td", { class: `o-${row.outcome}` }, OUTCOMES[row.outcome])))));

    const card = (title, table) => el("div", { class: "card", style: "padding:16px" },
      el("h3", { style: "margin-bottom:10px" }, title), el("div", { class: "table-wrap" }, table));

    box.replaceChildren(
      el("div", { class: "callout" },
        el("strong", {}, "Démonstration, pas une mesure. "),
        `${n} dossiers construits à la main sur des journées réelles, dont des pièges (pluie ordinaire, lendemain de tempête, tempête sur un autre aéroport, grève non sourcée à l'aéroport). Étiquettes fixées avant de lancer le moteur, à confirmer par un juriste.`),
      el("div", { class: "eval-grid" },
        kpi("Corrects", o.CORRECT, n),
        kpi("Renvoyés à un juriste", o.RENVOYE, n, "le module dit « incertain »"),
        kpi("Faux", o.FAUX, n),
        kpi("Traités sans humain", s.automated, n, "continuer ou mise en attente"),
        kpi("Erreurs parmi les automatiques", s.automated_errors, s.automated),
        kpi("Erreurs critiques", s.critical_errors.length, s.automated, "continuer alors qu'une CE est plausible")),
      el("div", { class: "two" },
        card("Matrice de confusion", matrix),
        card("Détail par dossier", detail)),
      el("p", { class: "note", style: "margin-top:12px" },
        `Règles ${r.rules_version} · calendrier des grèves ${r.strike_calendar_version}. Même calcul que scripts/evaluate.py.`));
    state.evalLoaded = true;
  } catch (e) {
    box.replaceChildren(el("div", { class: "error", role: "alert" }, e.message));
  }
}

// ---------- Navigation et démarrage ----------

function show(view) {
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.view === view;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on);
  });
  for (const v of ["queue", "new", "eval"]) document.getElementById(`view-${v}`).hidden = v !== view;
  if (view === "eval" && !state.evalLoaded) loadEval();
}

async function init() {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => show(t.dataset.view)));
  document.getElementById("new-form").addEventListener("submit", submitForm);
  try {
    state.meta = await api("/api/meta");
    // Bornes stockées en UTC : on arrondit au jour le plus proche pour l'affichage.
    const shift = (iso, h) => new Date(d(iso).getTime() + h * 3600e3).toISOString();
    const cov = state.meta.strike_coverage.map((c) => `${c.zone} ${day(shift(c.from, 12))}–${day(shift(c.to, -12))}`).join(", ");
    document.getElementById("versions").replaceChildren(
      el("span", { class: "chip" }, `Règles ${state.meta.rules_version}`),
      el("span", { class: "chip" }, `Grèves ${state.meta.strike_calendar_version}`),
      el("span", { class: "chip", title: "Zones et périodes où l'absence de grève est vérifiée" }, `Couverture grèves : ${cov || "aucune"}`));
    state.cases = await api("/api/cases");
  } catch (e) {
    document.getElementById("case-list").replaceChildren(el("div", { class: "error", role: "alert" }, e.message));
    return;
  }
  renderFilters();
  renderList();
  renderExamples();
  if (state.cases.length) select(state.cases.find((c) => c.decision.ec_type === "GREVE_ATC")?.case_id || state.cases[0].case_id);
}

init();
