"""Frozen gold questions + required-evidence specs.

Imported by record.py (to embed each question) and bench.py (to score). The
verdict is RETRIEVAL-presence, not an answer-LLM call: a case PASSES when every
`required` token appears in the retrieved evidence (top-k chunks for vector-only;
top-k chunks + expanded graph facts for graph). This separates "did the bridging
fact reach the context" (this service's job) from "could an LLM reason over it"
(the platform's job) — the confound the original multi-hop benchmark conflated.
"""

from pathlib import Path

CORPUS_DIR = Path(__file__).parent / "corpus"

# Schema modes recorded per fixture. Generic = auto-derive (empty allow-lists);
# domain = the locked fightclub schema where CTO_OF is a first-class edge.
MODES = {
    "generic": {"allowed_nodes": [], "allowed_relationships": []},
    "domain": {
        "allowed_nodes": ["Person", "Company", "City"],
        "allowed_relationships": ["FOUNDED", "ACQUIRED", "CTO_OF", "HEADQUARTERED_IN"],
    },
}

GOLD = [
    {
        "id": "AGGREGATION",
        "category": "aggregation",
        "question": "List every company that Acme Corp acquired.",
        "required": ["beta labs", "cobalt", "delta freight",
                     "echo robotics", "falcon drones", "gamma logistics"],
    },
    {
        "id": "MULTIHOP",
        "category": "multi-hop",
        "question": "Who is the Chief Technology Officer of the company that Jane Doe founded?",
        "required": ["maria garcia"],
        # The bridging chunk (maria_garcia.txt) must be OUTSIDE vector top-k; the
        # anchor chunk that names Acme (acme.txt) must be INSIDE. bench asserts both.
        "anchor_source": "acme.txt",
        "bridge_source": "maria_garcia.txt",
    },
    {
        "id": "CONTROL",
        "category": "control",
        "question": "Where is Acme Corp headquartered?",
        "required": ["boston"],
    },
]
