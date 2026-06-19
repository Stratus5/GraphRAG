"""Hand-authored demo scenario, rich enough that Explore is worth clicking
around: 4 founders, 10 companies, 2 VCs with overlapping stakes, and CEOs/CTOs
some of whom run more than one company. Offline and deterministic (no gateway,
no extraction) - written into Neo4j through the real tenant graph path.

Every entity carries a role type (Founder / Company / CEO / CTO / Investor) so
each gets its own colour on the map.
"""

import re

FOUNDERS = {
    "Ada Whitfield": ["Helix Robotics", "Cobalt Health", "Northstar Mobility"],
    "Bruno Castro": ["Vantage Payments", "Lumen Energy", "Drift Logistics"],
    "Mei Lin": ["Pylon Security", "Quartz Analytics"],
    "Omar Haddad": ["Reef Biolabs", "Tessera Cloud"],
}

CEO = {
    "Helix Robotics": "Grace Okoye", "Northstar Mobility": "Grace Okoye",
    "Cobalt Health": "Daniel Reyes",
    "Vantage Payments": "Hannah Berg", "Drift Logistics": "Hannah Berg",
    "Lumen Energy": "Ivan Petrov",
    "Pylon Security": "Lena Voss", "Quartz Analytics": "Lena Voss",
    "Reef Biolabs": "Sam Okafor", "Tessera Cloud": "Sam Okafor",
}

CTO = {
    "Helix Robotics": "Maya Chen", "Cobalt Health": "Maya Chen",
    "Northstar Mobility": "Tomas Vidal",
    "Vantage Payments": "Priya Nair", "Lumen Energy": "Priya Nair",
    "Drift Logistics": "Raphael Kim", "Pylon Security": "Raphael Kim",
    "Quartz Analytics": "Nadia Farouk",
    "Reef Biolabs": "Leo Marsh", "Tessera Cloud": "Leo Marsh",
}

VC = {
    "Northwind Capital": {"Helix Robotics": 25, "Cobalt Health": 18, "Vantage Payments": 30,
                          "Lumen Energy": 15, "Pylon Security": 22, "Reef Biolabs": 62,
                          "Tessera Cloud": 55},
    "Summit Ventures": {"Cobalt Health": 10, "Northstar Mobility": 28, "Vantage Payments": 15,
                        "Drift Logistics": 55, "Pylon Security": 14, "Quartz Analytics": 65,
                        "Tessera Cloud": 18},
}

COMPANIES = [c for cs in FOUNDERS.values() for c in cs]
FOUNDER_OF = {c: f for f, cs in FOUNDERS.items() for c in cs}
INVESTORS = {}
for _vc, _port in VC.items():
    for _c, _p in _port.items():
        INVESTORS.setdefault(_c, []).append((_vc, _p))

# (vc, company, pct) holdings over 50% -> the "majority stake" query.
MAJORITY = [(vc, c, p) for vc, port in VC.items() for c, p in port.items() if p > 50]

# Role type per entity (founders / CEOs / CTOs are disjoint people here).
TYPE_OF = {}
for _f in FOUNDERS:
    TYPE_OF[_f] = "Founder"
for _c in COMPANIES:
    TYPE_OF[_c] = "Company"
for _p in CEO.values():
    TYPE_OF[_p] = "CEO"
for _p in CTO.values():
    TYPE_OF[_p] = "CTO"
for _v in VC:
    TYPE_OF[_v] = "Investor"


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _andlist(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _n(nid):
    return {"id": nid, "type": TYPE_OF[nid], "properties": {}}


def _rel(s, t, rtype, props=None):
    return {"source": {"id": s, "type": TYPE_OF[s]}, "target": {"id": t, "type": TYPE_OF[t]},
            "type": rtype, "properties": props or {}}


CHUNKS = []
GRAPH = []


def _add(chunk_id, source, text, nodes, rels):
    CHUNKS.append({"chunk_id": chunk_id, "source": source, "text": text})
    GRAPH.append({"source_chunk_id": chunk_id, "source": source, "nodes": nodes,
                  "relationships": rels})


for c in COMPANIES:
    f, ceo, cto = FOUNDER_OF[c], CEO[c], CTO[c]
    inv = INVESTORS[c]
    inv_txt = _andlist([f"{vc} holds a {p}% stake" for vc, p in inv])
    text = (f"{c} is a company founded by {f}. Its chief executive officer is {ceo} "
            f"and its chief technology officer is {cto}. {inv_txt} in {c}.")
    nodes = [_n(c), _n(f), _n(ceo), _n(cto)] + [_n(vc) for vc, _ in inv]
    rels = [_rel(f, c, "FOUNDED"), _rel(ceo, c, "CEO_OF"), _rel(cto, c, "CTO_OF")]
    rels += [_rel(vc, c, "INVESTED_IN", {"pct": p}) for vc, p in inv]
    _add(slug(c), slug(c) + ".txt", text, nodes, rels)

for f, cos in FOUNDERS.items():
    text = f"{f} is a founder. {f} founded {_andlist(cos)}."
    _add(slug(f), slug(f) + ".txt", text, [_n(f)] + [_n(c) for c in cos], [])

for vc, port in VC.items():
    holdings = _andlist([f"{c} ({p}%)" for c, p in port.items()])
    text = f"{vc} is a venture capital firm. It holds stakes in {holdings}."
    _add(slug(vc), slug(vc) + ".txt", text, [_n(vc)] + [_n(c) for c in port], [])

# Distractor chunks: high lexical overlap with the questions (so they compete for
# vector top-k) but carry NO new relationships, so graph/curated answers are unchanged.
# They re-mention existing entities only.
_DISTRACTORS = [
    ("distractor_market", "market_report.txt",
     "This industry market report discusses founders, chief executive officers and "
     "chief technology officers across many companies and the venture capital firms "
     "that hold stakes in them. It mentions Ada Whitfield, Northwind Capital and "
     "Vantage Payments in passing without stating any specific role or stake.",
     ["Ada Whitfield", "Northwind Capital", "Vantage Payments"]),
    ("distractor_press", "press_roundup.txt",
     "A press roundup covering company founders, CEOs, CTOs and investors. It name-drops "
     "Maya Chen, Summit Ventures and Helix Robotics in a general overview of the sector, "
     "with no founding, role, or investment relationship asserted.",
     ["Maya Chen", "Summit Ventures", "Helix Robotics"]),
]
for _cid, _src, _text, _ents in _DISTRACTORS:
    _add(_cid, _src, _text, [_n(e) for e in _ents], [])


def read_steps():
    steps = []
    for gd in GRAPH[:len(COMPANIES)]:
        for n in gd["nodes"]:
            steps.append({"kind": "node", "id": n["id"], "type": n["type"], "doc": gd["source"]})
        for r in gd["relationships"]:
            steps.append({"kind": "edge", "source": r["source"]["id"], "target": r["target"]["id"],
                          "predicate": r["type"], "pct": r["properties"].get("pct"), "doc": gd["source"]})
    return steps


QUESTIONS = [
    {"id": "FOUNDER_CO", "question": "Which companies did Ada Whitfield found?",
     "answer": ["helix robotics", "cobalt health", "northstar mobility"]},
    {"id": "VC_PORT", "question": "Which companies does Northwind Capital hold a stake in?",
     "answer": ["helix robotics", "cobalt health", "vantage payments", "lumen energy",
                "pylon security", "reef biolabs", "tessera cloud"]},
    {"id": "BOTH_VC",
     "question": "Which companies have both Northwind Capital and Summit Ventures as investors?",
     "answer": ["cobalt health", "vantage payments", "pylon security", "tessera cloud"]},
    {"id": "SHARED_CTO", "question": "Which companies share Maya Chen as their CTO?",
     "answer": ["helix robotics", "cobalt health"]},
    {"id": "CO_TEAM", "question": "Who founded and runs Vantage Payments?",
     "answer": ["bruno castro", "hannah berg", "priya nair"]},
    {"id": "MAJORITY", "kind": "majority",
     "question": "Name each VC and the companies it owns more than 50% of.",
     "answer": [c.lower() for _, c, _ in MAJORITY]},
]
