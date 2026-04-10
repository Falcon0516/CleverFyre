"""
Tests for AXIOM AgPP SDK modules.

These tests ensure the core logic (Identity, Merkle, DNA, Semantic, Anomaly)
works correctly.

Run:
    pytest -v tests/test_sdk.py
"""

import hashlib
import json
import logging
import numpy as np

from axiom_agpp.anomaly import AnomalyDetector
from axiom_agpp.dna import BehavioralDNA
from axiom_agpp.identity import derive_agent_address, verify_agent_identity
from axiom_agpp.intent import IntentDocument
from axiom_agpp.merkle import MerkleTree


# ─────────────────────────────────────────────────────────────────
#  IDENTITY TESTS
# ─────────────────────────────────────────────────────────────────

def test_deterministic_identity():
    """Test that derive_agent_address is deterministic."""
    secret = b"test-secret"
    org = "test-org"
    role = "agent"
    
    # We use __file__ as the code hash source
    pk1, addr1 = derive_agent_address(secret, org, role, __file__)
    pk2, addr2 = derive_agent_address(secret, org, role, __file__)
    
    # Determinism: same inputs -> same outputs
    assert pk1 == pk2
    assert addr1 == addr2
    assert len(addr1) == 58  # standard Algorand address length
    
    # Verification helper
    assert verify_agent_identity(secret, org, role, __file__, addr1)
    
    # Tamper detection: different role
    _, addr3 = derive_agent_address(secret, org, "hacked-role", __file__)
    assert addr1 != addr3
    
    # Tamper detection: different secret
    _, addr4 = derive_agent_address(b"hacked-secret", org, role, __file__)
    assert addr1 != addr4


# ─────────────────────────────────────────────────────────────────
#  MERKLE TREE TESTS
# ─────────────────────────────────────────────────────────────────

def test_merkle_tree():
    """Test Merkle tree root and proofs."""
    leaves = [b"intent1", b"intent2", b"intent3", b"intent4", b"intent5"]
    hashed_leaves = [hashlib.sha256(l).digest() for l in leaves]
    
    tree = MerkleTree(hashed_leaves)
    root = tree.get_root()
    
    assert len(root) == 32
    assert len(tree.leaves) == 5
    
    # Test proofs for all leaves
    for i in range(5):
        proof = tree.get_proof(i)
        assert tree.verify(hashed_leaves[i], proof, root)
        
    # Invalid proof should fail
    bad_proof = tree.get_proof(0)
    bad_proof[0] = b"wronghash"
    assert not tree.verify(hashed_leaves[0], bad_proof, root)


# ─────────────────────────────────────────────────────────────────
#  DNA & ANOMALY TESTS
# ─────────────────────────────────────────────────────────────────

def test_behavioral_dna():
    """Test DNA vector tracking, drift calculation, and mission drift."""
    dna1 = BehavioralDNA()
    obs1 = {
        "amount": 10.0,
        "calls_per_hour": 100,
        "api_domains": ["api.weather.com", "api.weather.com"],
        "sla_passed": True,
        "refunded": False,
        "category_counts": {"weather": 2}
    }
    dna1.update(obs1)
    
    dna2 = BehavioralDNA()
    obs2 = {
        "amount": 10.5,
        "calls_per_hour": 105,
        "api_domains": ["api.weather.com"],
        "sla_passed": True,
        "refunded": False,
        "category_counts": {"weather": 1}
    }
    dna2.update(obs2)
    
    # Drift should be small for similar behavior
    drift = dna1.drift_score(dna2.vector)
    assert drift < 0.1
    
    # Serialized size should be exactly 32 bytes
    b = dna1.to_bytes()
    assert len(b) == 32
    
    # Mission drift calculation
    expected = {"weather": 1.0, "news": 0.0}
    actual = {"weather": 0.1, "news": 0.9}  # Agent doing news instead of weather
    mission_drift = dna1.mission_drift_score(expected, actual)
    assert mission_drift > 0.5  # High mission drift


def test_anomaly_detector_burst():
    """Test basic burst rate limiter."""
    detector = AnomalyDetector(window=10)
    for _ in range(15):
        detector.record([1.0, 10.0])
        
    # Burst limit=10, we sent 15
    assert detector.burst_check(window_sec=5.0, max_calls=10) == True
    assert detector.burst_check(window_sec=5.0, max_calls=20) == False


# ─────────────────────────────────────────────────────────────────
#  INTENT DOCUMENT TESTS
# ─────────────────────────────────────────────────────────────────

def test_intent_document():
    """Test IntentDocument serialization and hashing."""
    intent = IntentDocument(
        agent_id="TEST_AGENT_ADDRESS",
        task_canonical="Test mission",
        api_url="http://test.api",
        api_selection_reason="Test reason"
    )
    
    j = intent.to_json()
    assert j == json.dumps(json.loads(j), sort_keys=True)
    
    h = intent.hash()
    assert len(h) == 32
    
    note = intent.to_note()
    assert note.startswith(b"x402:axiom:")
    assert len(note) == 32
