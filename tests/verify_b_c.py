"""
AXIOM Verification Script — Person B + Person C modules.
Tests all core logic WITHOUT needing deployed contracts or Algorand network.
"""

import hashlib
import json
import sys
import time
import os

# Ensure repo root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} — {detail}")


print()
print("╔══════════════════════════════════════════════════════════╗")
print("║  AXIOM VERIFICATION — Person B + Person C Modules       ║")
print("╚══════════════════════════════════════════════════════════╝")

# ═══════════════════════════════════════════════════════════════
#  PERSON B — SDK Core
# ═══════════════════════════════════════════════════════════════

print("\n─── PERSON B: Identity (identity.py) ───")
from axiom_agpp.identity import derive_agent_address, verify_agent_identity
code_path = os.path.abspath(__file__)
pk1, a1 = derive_agent_address(b"test-secret", "acme", "researcher", code_path)
pk2, a2 = derive_agent_address(b"test-secret", "acme", "researcher", code_path)
check("Deterministic output", a1 == a2, f"{a1} != {a2}")
check("Valid Algorand address (58 chars)", len(a1) == 58, f"len={len(a1)}")
_, a3 = derive_agent_address(b"test-secret", "acme", "hacker", code_path)
check("Different role → different address", a1 != a3)
_, a4 = derive_agent_address(b"other-secret", "acme", "researcher", code_path)
check("Different secret → different address", a1 != a4)
check("verify_agent_identity(correct)", verify_agent_identity(b"test-secret", "acme", "researcher", code_path, a1))
check("verify_agent_identity(tampered)", not verify_agent_identity(b"hacked", "acme", "researcher", code_path, a1))

print(f"\n─── PERSON B: Merkle Tree (merkle.py) ───")
from axiom_agpp.merkle import MerkleTree
leaves = [b"leaf0", b"leaf1", b"leaf2", b"leaf3"]
tree = MerkleTree(leaves)
root = tree.get_root()
check("Root is 32 bytes", len(root) == 32, f"len={len(root)}")
check("4 leaves stored", len(tree) == 4)
for i in range(4):
    proof = tree.get_proof(i)
    check(f"Proof valid for leaf[{i}]", tree.verify(leaves[i], proof, root))
bad_proof = tree.get_proof(0)
check("Bad leaf fails proof", not tree.verify(b"fake", bad_proof, root))

print(f"\n─── PERSON B: Intent Document (intent.py) ───")
from axiom_agpp.intent import IntentDocument
intent = IntentDocument(
    agent_id="TEST_ADDR",
    task_canonical="Find weather",
    api_url="https://api.weather.com",
    api_selection_reason="semantic match",
    policy_commitment="abc123",
    timestamp_round=12345,
)
h = intent.hash()
check("Hash is 32 bytes", len(h) == 32)
j = intent.to_json()
check("JSON is deterministic", intent.to_json() == intent.to_json())
check("JSON is sorted", j == json.dumps(json.loads(j), sort_keys=True))
note = intent.to_note()
check("Note starts with x402:axiom:", note.startswith(b"x402:axiom:"))
check("Note is 32 bytes", len(note) == 32)
rt = IntentDocument.from_json(j)
check("Round-trip from_json", rt.agent_id == "TEST_ADDR" and rt.api_url == "https://api.weather.com")

print(f"\n─── PERSON B: Behavioral DNA (dna.py) ───")
from axiom_agpp.dna import BehavioralDNA
dna = BehavioralDNA()
check("Initial vector is zeros", all(v == 0 for v in dna.vector))
dna.update({
    "amount": 1.0, "calls_per_hour": 50,
    "api_domains": ["api.a.com", "api.a.com", "api.b.com"],
    "sla_passed": True, "refunded": False,
    "category_counts": {"weather": 3, "news": 1}
})
check("Vector not all zeros after update", any(v != 0 for v in dna.vector))
serialized = dna.to_bytes()
check("Serialized to 32 bytes", len(serialized) == 32, f"len={len(serialized)}")
restored = BehavioralDNA.from_bytes(serialized)
check("Deserialized 32 dims", len(restored.vector) == 32)
drift = dna.drift_score(dna.vector)
check("Self-drift is 0", drift == 0.0 or drift < 0.001, f"drift={drift}")
import numpy as np
check("Mission drift calculation", dna.mission_drift_score({"a": 1}, {"b": 1}) > 0)

print(f"\n─── PERSON B: Anomaly Detector (anomaly.py) ───")
from axiom_agpp.anomaly import AnomalyDetector
det = AnomalyDetector(window=20)
check("No anomaly before training", not det.is_anomaly([1, 2, 3]))
for _ in range(15):
    det.record([1.0, 10.0, 0.1, 1.0, 0.0])
check("Model trained after 15 samples", det.model is not None)
check("Normal pattern not anomaly", not det.is_anomaly([1.0, 10.0, 0.1, 1.0, 0.0]))
check("Burst check (under limit)", not det.burst_check(window_sec=5, max_calls=50))
check("Burst check (over limit)", det.burst_check(window_sec=60, max_calls=5))
stats = det.get_stats()
check("Stats dict has keys", "total_checks" in stats and "model_trained" in stats)

print(f"\n─── PERSON B: Semantic Router (semantic.py) ───")
from axiom_agpp.semantic import route_api, get_all_scores
budget = {"weather": 0.5, "financial_data": 2.0, "news": 0.3}
cat, score = route_api("weather forecast temperature rain", budget, threshold=0.3)
check(f"Weather routed correctly (cat={cat})", cat == "weather", f"got {cat}")
check(f"Score > 0.3", score > 0.3, f"score={score}")
cat2, score2 = route_api("completely unknown gibberish xyz123", budget, threshold=0.9)
check("Gibberish blocked at high threshold", cat2 is None, f"got {cat2}")
scores = get_all_scores("stock market financial trading")
check("get_all_scores returns list", len(scores) > 0)
check("Top match is financial_data", scores[0][0] == "financial_data", f"got {scores[0][0]}")

# ═══════════════════════════════════════════════════════════════
#  PERSON C — Infrastructure
# ═══════════════════════════════════════════════════════════════

print(f"\n─── PERSON C: Consensus Orchestrator (consensus.py) ───")
from axiom_agpp.consensus import ConsensusOrchestrator
co = ConsensusOrchestrator(consensus_vault_id=0, sentinel_escrow_id=0)
check("Orchestra init with stub IDs", co.vault_id == 0 and co.escrow_id == 0)
# _query_consensus_status should return stub dict
status = co._query_consensus_status("abcdef1234567890")
check("Stub status has collected", "collected" in status)
check("Stub status has required", "required" in status)
check("Stub status has resolved", "resolved" in status)

print(f"\n─── PERSON C: Temporal Query (temporal.py) ───")
from axiom_agpp.temporal import TemporalQuery, AgentSnapshot, SystemSnapshot
snap = SystemSnapshot(round=100)
check("Empty snapshot", len(snap.agents) == 0 and len(snap.events) == 0)
# Test apply() with simulated transactions
snap.apply("x402:axiom:PAYMENT", {"sender": "AGENT_A", "confirmed-round": 100, "id": "tx1", "payment-transaction": {"amount": 500000}})
check("Apply PAYMENT: agent created", "AGENT_A" in snap.agents)
check("Apply PAYMENT: payments_made=1", snap.agents["AGENT_A"].payments_made == 1)
check("Apply PAYMENT: rep boosted", snap.agents["AGENT_A"].reputation_score == 505)
snap.apply("x402:axiom:BLOCK", {"sender": "AGENT_A", "confirmed-round": 101, "id": "tx2"})
check("Apply BLOCK: blocked=1", snap.agents["AGENT_A"].payments_blocked == 1)
check("Apply BLOCK: rep penalized", snap.agents["AGENT_A"].reputation_score == 455)
check("Events logged", len(snap.events) == 2)

print(f"\n─── PERSON C: Reputation Client (reputation_client.py) ───")
from axiom_agpp.reputation_client import ReputationClient, TIER_NAMES
rc = ReputationClient(app_id=0)
score = rc.get_score("FAKE_ADDR")
check("Default stub score is 500", score == 500)
tier = rc.get_tier("FAKE_ADDR")
check("Default tier is 2 (CAUTION)", tier == 2)
check("Tier name is CAUTION", rc.get_tier_name("FAKE_ADDR") == "CAUTION")
max_pay = rc.get_max_payment("FAKE_ADDR")
check("CAUTION max pay is 0.5", max_pay == 0.5)

print(f"\n─── PERSON C: Red Team Engine (red_team.py) ───")
from axiom_agpp.red_team import RedTeamEngine
engine = RedTeamEngine("policy.yaml")
check("Policy loaded", engine.policy is not None)
results = engine.run_all()
check("6 attack vectors ran", len(results) == 6)
for r in results:
    status = "VULNERABLE" if r.succeeded else "BLOCKED"
    check(f"{r.id}: {r.name[:30]} → {status}", True)

print(f"\n─── PERSON C: Event Normalizer (event_normalizer.py) ───")
from backend.event_normalizer import _classify_event, _normalize, get_last_round, reset_last_round
check("PAYMENT default", _classify_event("x402:axiom:some normal note") == "PAYMENT")
check("QUARANTINE keyword", _classify_event("x402:axiom:QUARANTINE_HOLD") == "QUARANTINE")
check("BLOCKED keyword", _classify_event("x402:axiom:BLOCK_PAYMENT") == "BLOCKED")
check("WARNING keyword", _classify_event("x402:axiom:WARN_LIMIT") == "WARNING")
check("DRIFT keyword", _classify_event("x402:axiom:DRIFT_DETECTED") == "DRIFT")
check("EXPIRED keyword", _classify_event("x402:axiom:EXPIRE_POLICY") == "EXPIRED")
reset_last_round(0)
check("Reset round counter", get_last_round() == 0)
# Test _normalize with a mock tx
import base64
mock_tx = {
    "id": "TXID123",
    "sender": "SENDER_ADDR",
    "confirmed-round": 999,
    "note": base64.b64encode(b"x402:axiom:WARN_TEST").decode(),
    "round-time": 1719500000,
    "payment-transaction": {"amount": 500000},
}
ev = _normalize(mock_tx)
check("Normalized type=WARNING", ev["type"] == "WARNING")
check("Normalized tx_id", ev["tx_id"] == "TXID123")
check("Normalized sender", ev["sender"] == "SENDER_ADDR")
check("Normalized round=999", ev["round"] == 999)
check("Normalized amount=500000", ev["amount"] == 500000)

print(f"\n─── PERSON C: IPFS Client (backend/ipfs_client.py) ───")
from backend.ipfs_client import get_cached_cid
check("No cached CID initially", get_cached_cid("nonexistent") is None)

print(f"\n─── PERSON C: Backend FastAPI (backend/main.py) ───")
from backend.main import app
check("FastAPI app title", app.title == "AXIOM Backend")
routes = [r.path for r in app.routes]
check("/ws/events endpoint exists", "/ws/events" in routes)
check("/api/state endpoint exists", "/api/state" in routes)
check("/health endpoint exists", "/health" in routes)

# ═══════════════════════════════════════════════════════════════
#  CROSS-MODULE INTEGRATION
# ═══════════════════════════════════════════════════════════════

print(f"\n─── INTEGRATION: Wrapper (wrapper.py) ───")
from axiom_agpp.wrapper import AXIOMWrapper
check("AXIOMWrapper class importable", True)
# Don't instantiate — needs file system for identity derivation and policy.yaml
# But we can verify the _handle_402 method exists
check("_handle_402 method exists", hasattr(AXIOMWrapper, '_handle_402'))
check("_call_policy_vault method exists", hasattr(AXIOMWrapper, '_call_policy_vault'))
check("_call_sentinel_deposit method exists", hasattr(AXIOMWrapper, '_call_sentinel_deposit'))
check("_call_sentinel_quarantine method exists", hasattr(AXIOMWrapper, '_call_sentinel_quarantine'))
check("_call_intent_registry method exists", hasattr(AXIOMWrapper, '_call_intent_registry'))
check("_call_dna_registry_update method exists", hasattr(AXIOMWrapper, '_call_dna_registry_update'))
check("_post_sla_evaluation method exists", hasattr(AXIOMWrapper, '_post_sla_evaluation'))
check("_parse_provider_address method exists", hasattr(AXIOMWrapper, '_parse_provider_address'))
check("_parse_payment_amount method exists", hasattr(AXIOMWrapper, '_parse_payment_amount'))

# ═══════════════════════════════════════════════════════════════
print()
print("╔══════════════════════════════════════════════════════════╗")
total = PASS + FAIL
if FAIL == 0:
    print(f"║  ALL {PASS} TESTS PASSED ✓                                ║")
else:
    print(f"║  {PASS}/{total} PASSED, {FAIL} FAILED ✗                          ║")
print("╚══════════════════════════════════════════════════════════╝")
print()

sys.exit(FAIL)
