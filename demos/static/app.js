const $ = (s) => document.querySelector(s);
const panel = $("#panel");
const hint = $("#hint");

const TYPE_COLOR = {
  Founder: "#3b82f6", Company: "#f59e0b", CEO: "#8b5cf6",
  CTO: "#10b981", Investor: "#ec4899",
};
const ROLES = [["Founder", "Founder"], ["Company", "Company"], ["CEO", "CEO"],
               ["CTO", "CTO"], ["VC", "Investor"]];
const nodeColor = (t) => TYPE_COLOR[t] || "#8a8f9c";
const legend = () =>
  `<div class="legend">${ROLES.map(([l, t]) => {
    const c = nodeColor(t);
    return `<span><i style="background:${c};color:${c}"></i>${l}</span>`;
  }).join("")}</div>`;

const cy = cytoscape({
  container: $("#cy"),
  wheelSensitivity: 0.2, minZoom: 0.2, maxZoom: 1.6,
  style: [
    { selector: "node", style: {
      "background-color": (n) => nodeColor(n.data("type")),
      "label": "data(label)", "color": "#e9e4d6", "font-family": "IBM Plex Mono",
      "font-size": 11, "text-valign": "bottom", "text-margin-y": 6,
      "width": 20, "height": 20, "transition-property": "opacity",
    }},
    { selector: "edge", style: {
      "width": 1.2, "line-color": "#2c303b", "target-arrow-color": "#2c303b",
      "target-arrow-shape": "triangle", "arrow-scale": 0.7, "curve-style": "bezier",
      "label": "data(label)", "font-family": "IBM Plex Mono", "font-size": 8,
      "color": "#a49f92", "text-rotation": "autorotate", "text-margin-y": -4,
      "text-background-color": "#0d0e12", "text-background-opacity": 0.9,
      "text-background-padding": 2, "text-background-shape": "roundrectangle",
    }},
    { selector: ".dim", style: { "opacity": 0.1 } },
    { selector: ".hidden", style: { "display": "none" } },
    { selector: "edge.lit", style: {
      "line-color": "#ffb000", "target-arrow-color": "#ffb000", "width": 2.6,
      "color": "#ffce6b", "font-size": 9, "z-index": 20, "opacity": 1 } },
    { selector: "node.lit", style: { "z-index": 15 } },
    { selector: "node.answer", style: {  // the answer entities, a colour of their own
      "background-color": "#fde047", "border-width": 3, "border-color": "#ffffff",
      "width": 30, "height": 30, "color": "#fff",
      "text-outline-color": "#0a0b0e", "text-outline-width": 2, "z-index": 30 } },
    { selector: "node.focus", style: {  // the node Explore is centred on
      "border-width": 4, "border-color": "#ffffff", "width": 30, "height": 30,
      "text-outline-color": "#0a0b0e", "text-outline-width": 2, "z-index": 30 } },
  ],
  layout: { name: "preset" },
});
window.cy = cy;

let fullGraph = null;
const load = (url, body) =>
  fetch(url, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined)
    .then((r) => r.json());
const getFull = async () => (fullGraph ||= await load("/api/graph"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let currentMode = "curated";
document.querySelectorAll('input[name="mode"]').forEach(el =>
  el.addEventListener("change", e => { currentMode = e.target.value; }));

(async () => {
  const { live_available } = await load("/api/modes");
  if (!live_available) {
    const liveRadio = document.querySelector('input[value="live"]');
    liveRadio.disabled = true;
    document.getElementById("live-note").textContent =
      " (set OPENAI_BASE_URL/OPENAI_API_KEY + start Weaviate to enable)";
  }
})();

function elesFrom(g) {
  return [
    ...g.nodes.map((n) => ({ data: { id: n.id, label: n.id, type: n.type } })),
    ...g.edges.map((e) => ({ data: { id: `${e.source}|${e.predicate}|${e.target}`,
      source: e.source, target: e.target, label: e.label } })),
  ];
}
function ensureNode(id, type) {
  if (cy.getElementById(id).empty()) cy.add({ data: { id, label: id, type: type || "Company" } });
}

// Spread across the viewport (boundingBox = canvas) at zoom 1.
function fillLayout(eles, animate = true) {
  const w = cy.width(), h = cy.height();
  eles.layout({ name: "cose", animate, animationDuration: 600, fit: false, randomize: true,
    boundingBox: { x1: 70, y1: 55, w: w - 160, h: h - 130 },
    nodeRepulsion: 55000, idealEdgeLength: 230, gravity: 0.06, nodeOverlap: 40,
    componentSpacing: 150, numIter: 2500 }).run();
  cy.zoom(1); cy.pan({ x: 0, y: 0 });
}
// Answer view: radial, highest-degree entity centred.
function answerLayout(eles) {
  const w = cy.width(), h = cy.height();
  eles.layout({ name: "concentric", animate: true, animationDuration: 600, fit: false,
    boundingBox: { x1: 70, y1: 55, w: w - 160, h: h - 130 },
    concentric: (n) => n.degree(), levelWidth: () => 1, minNodeSpacing: 35 }).run();
  cy.zoom(1); cy.pan({ x: 0, y: 0 });
}
// Explore: re-root the whole graph on `id` (BFS rings to full depth), rebalanced.
function recenterOn(id, animate = true) {
  const w = cy.width(), h = cy.height();
  cy.layout({ name: "breadthfirst", animate, animationDuration: 600, fit: false, circle: true,
    roots: [id], boundingBox: { x1: 60, y1: 50, w: w - 120, h: h - 110 },
    spacingFactor: 1.0, padding: 20 }).run();
  cy.zoom(1); cy.pan({ x: 0, y: 0 });
}

const tabs = { read: showRead, ask: showAsk, explore: showExplore };
document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    tabs[b.dataset.tab]();
  }));

// ---- demo 1: Read ------------------------------------------------------
function showRead() {
  cy.elements().remove();
  hint.textContent = "reading each document, then drawing what it found";
  panel.innerHTML = `
    <div class="eyebrow">Demo 1</div>
    <div class="lede">Watch it read documents into a map.</div>
    <p class="copy">Company filings go in. Each one is read line by line, then the
      founders, companies, VCs and the CEO/CTO of each appear on the map.</p>
    ${legend()}
    <button class="act" id="go">Read the documents</button>
    <div class="reading" id="reading"></div>
    <div class="readout" id="ro"></div>`;
  $("#go").onclick = readRun;
}
const edgeLabel = (p, pct) => (pct == null ? p : `${p} ${pct}%`);

function _pop(ele) { ele.style("opacity", 0); ele.animate({ style: { opacity: 1 } }, { duration: 200 }); }

async function readRun() {
  const btn = $("#go"); btn.disabled = true;
  cy.elements().remove();
  const reading = $("#reading"), ro = $("#ro");
  const { documents } = await load("/api/read-steps");
  const w = cy.width(), h = cy.height();
  for (const d of documents) {
    reading.innerHTML = `<div class="src">${d.source}</div><div class="txt" id="txt"></div>`;
    const txt = $("#txt");
    for (let i = 0; i <= d.text.length; i += 2) {
      txt.textContent = d.text.slice(0, i) + "▏";
      await sleep(10);
    }
    txt.textContent = d.text;
    await sleep(160);
    for (const n of d.nodes) {
      if (cy.getElementById(n.id).empty()) {
        _pop(cy.add({ data: { id: n.id, label: n.id, type: n.type },
          position: { x: w * (0.3 + 0.4 * Math.random()), y: h * (0.3 + 0.4 * Math.random()) } }));
      }
    }
    for (const e of d.edges) {
      ensureNode(e.source); ensureNode(e.target);
      const id = `${e.source}|${e.predicate}|${e.target}`;
      if (cy.getElementById(id).empty()) {
        _pop(cy.add({ data: { id, source: e.source, target: e.target, label: edgeLabel(e.predicate, e.pct) } }));
      }
    }
    ro.innerHTML = `read <b>${cy.nodes().length}</b> entities, <b>${cy.edges().length}</b> links so far`;
    await sleep(220);
  }
  reading.innerHTML = "";
  ro.innerHTML = `done. <b>${cy.nodes().length}</b> entities, <b>${cy.edges().length}</b> relationships. Switch to Explore to walk it.`;
  fillLayout(cy.elements(), true);
  btn.disabled = false;
}

// ---- demo 2: Ask -------------------------------------------------------
async function showAsk() {
  hint.textContent = "the answer entities are highlighted in yellow";
  cy.elements().remove();
  cy.add(elesFrom(await getFull()));
  fillLayout(cy.elements(), false);
  cy.elements().addClass("dim");
  const qs = await load("/api/questions");
  panel.innerHTML = `
    <div class="eyebrow">Demo 2</div>
    <div class="lede">Ask, and watch the answer light up.</div>
    <p class="copy">Pick a question. The facts that answer it light up across the
      graph; the answer entities turn yellow.</p>
    ${legend()}
    <div class="facts" id="qlist"></div>
    <div class="readout" id="ro2"></div>
    <div class="facts" id="facts"></div>
    <div id="answer"></div>`;
  const ql = $("#qlist");
  qs.forEach((q) => {
    const b = document.createElement("button");
    b.className = "qbtn"; b.textContent = q.question;
    b.onclick = () => ask(q.id, b);
    ql.appendChild(b);
  });
}

async function ask(id, btn) {
  document.querySelectorAll(".qbtn").forEach((x) => x.style.opacity = .5);
  if (btn) btn.style.opacity = 1;
  const data = await load("/api/ask", { id, mode: currentMode });
  if (data.mode === "live") renderLive(data); else renderCurated(data);
}

function renderCurated(res) {
  cy.elements().removeClass("hidden dim lit answer focus");
  let lit = cy.collection();
  res.facts.forEach((f) => {
    [`${f.subject}|${f.predicate}|${f.object}`, f.subject, f.object].forEach((i) => {
      const e = cy.getElementById(i); if (!e.empty()) lit = lit.union(e);
    });
  });
  lit.addClass("lit");
  cy.elements().not(lit).addClass("hidden");
  // Answer entities (by name) get their own colour.
  const tokens = res.answer.map((a) => a.toLowerCase());
  lit.nodes().forEach((n) => {
    if (tokens.some((t) => n.id().toLowerCase().includes(t))) n.addClass("answer");
  });
  answerLayout(lit);
  $("#ro2").innerHTML = `connected <b>${res.facts.length}</b> facts`
    + (res.sources.length ? ` from <b>${res.sources.length}</b> documents:` : ":");
  $("#facts").innerHTML = res.facts.map((f, i) => {
    const obj = f.pct == null ? f.object : `${f.object} (${f.pct}%)`;
    return `<div class="fact" style="animation-delay:${i * 45}ms"><span class="s">${f.subject}</span><span class="p">${f.predicate}</span><span class="o">${obj}</span></div>`;
  }).join("");
  const ans = $("#answer"); if (ans) ans.innerHTML = "";
}

function renderLive(data) {
  cy.elements().removeClass("hidden dim lit answer focus");
  // Light the graph exactly like curated: the nodes + edges backing the returned
  // facts light up, everything else is hidden, answer entities turn yellow, and the
  // lit subgraph is re-laid-out radially. (service.retrieve returns predicate =
  // type(r), so `subject|predicate|object` matches the /api/graph edge ids.)
  let lit = cy.collection();
  data.facts.forEach((f) => {
    [`${f.subject}|${f.predicate}|${f.object}`, f.subject, f.object].forEach((i) => {
      const e = cy.getElementById(i); if (!e.empty()) lit = lit.union(e);
    });
  });
  lit.addClass("lit");
  cy.elements().not(lit).addClass("hidden");
  const answerTokens = (data.answer || []).map((a) => a.toLowerCase());
  lit.nodes().forEach((n) => {
    if (answerTokens.some((t) => n.id().toLowerCase().includes(t))) n.addClass("answer");
  });
  answerLayout(lit);

  const hitText = data.vector_hits.map(h => h.text.toLowerCase()).join(" ");
  const facts = data.facts.map(f => {
    // a fact is "graph-only" if neither endpoint's name appears in the retrieved chunks
    const inVectors = hitText.includes((f.subject || "").toLowerCase()) &&
                      hitText.includes((f.object || "").toLowerCase());
    return { ...f, graphOnly: !inVectors };
  });
  const hitsHtml = data.vector_hits.length
    ? data.vector_hits.map(h =>
        `<div class="hit"><span class="src">${h.source}</span><span class="score">${h.score.toFixed(2)}</span></div>`).join("")
    : `<div class="hit"><span class="src">(no chunks)</span></div>`;
  // Same styled fact cards as curated; graph-only facts carry a badge + accent.
  const factsHtml = facts.map((f, i) =>
    `<div class="fact${f.graphOnly ? " graph-only" : ""}" style="animation-delay:${i * 45}ms">` +
    `<span class="s">${f.subject}</span><span class="p">${f.predicate}</span><span class="o">${f.object}</span>` +
    `${f.graphOnly ? '<span class="badge">graph-only</span>' : ""}</div>`).join("");
  $("#ro2").innerHTML = `<b>${data.vector_hits.length}</b> vector hits, <b>${facts.length}</b> graph facts`;
  $("#facts").innerHTML = "";
  document.getElementById("answer").innerHTML =
    `<div class="section-label">Vector search returned (k=${data.vector_hits.length})</div>` +
    `<div class="hits">${hitsHtml}</div>` +
    `<div class="section-label">Facts after graph expansion</div>` +
    `<div class="facts">${factsHtml}</div>`;
}

// ---- demo 3: Explore ---------------------------------------------------
async function showExplore() {
  hint.textContent = "click any entity to centre the graph on it";
  cy.elements().remove();
  cy.add(elesFrom(await getFull()));
  const start = cy.getElementById("Northwind Capital").empty() ? cy.nodes()[0].id() : "Northwind Capital";
  focusNode(start, false);
  panel.innerHTML = `
    <div class="eyebrow">Demo 3</div>
    <div class="lede">Click around. The graph re-centres on what you click.</div>
    <p class="copy">No search box. Click any entity and the whole graph rebalances
      around it, rings out to everything it connects to, however deep that goes.</p>
    ${legend()}
    <div class="readout" id="ro3">Centred on <b>${start}</b></div>`;
}

function focusNode(id, animate = true) {
  cy.elements().removeClass("focus dim lit");
  cy.getElementById(id).addClass("focus");
  recenterOn(id, animate);
  const ro = $("#ro3"); if (ro) ro.innerHTML = `Centred on <b>${id}</b>`;
}

cy.on("tap", "node", (evt) => {
  if (document.querySelector(".tab.active").dataset.tab === "explore") focusNode(evt.target.id());
});

showRead();
