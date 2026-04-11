"""
AXIOM AgPP — Contracts Client

SDK client for interacting with the 6 core AXIOM smart contracts on Algorand.
Abstracts away ABI encoding and application call details.
Repaired for algokit-utils 4.x compatibility.
"""

import logging
import os
import json
from pathlib import Path
from typing import Optional

from algokit_utils import AlgorandClient
from algokit_utils.applications.app_client import AppClientMethodCallParams

logger = logging.getLogger(__name__)


# ================================================================
# Helper: make a proper v4 call
# ================================================================

def _app_call(app_client, method: str, args: dict = None, sender: str = None, signer = None, note: bytes = None):
    """
    Call an ABI method on an AppClient using the v4.x API.
    Returns the SendAppTransactionResult.
    """
    params = AppClientMethodCallParams(
        method=method, 
        args=args or {},
        sender=sender,
        signer=signer,
        note=note
    )
    return app_client.send.call(params)


# ================================================================
# 1. PolicyVault Client
# ================================================================

class PolicyVaultClient:
    def __init__(self, algo_client: AlgorandClient, app_id: int):
        self.algo_client = algo_client
        self.app_id = app_id

    def check_and_enforce(self, agent_addr: str, amount: int) -> int:
        if self.app_id <= 0: return 0
        try:
            spec = AXIOMContracts.load_spec("PolicyVault")
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id, app_spec=spec)
            result = _app_call(app_client, "check_and_enforce", {"agent": agent_addr, "amount": amount})
            return int(result.abi_return) if result.abi_return is not None else 0
        except Exception as e:
            logger.error("PolicyVault check_and_enforce failed: %s", e)
            return 0

    def get_policy_status(self, agent_addr: str) -> int:
        if self.app_id <= 0: return 0
        try:
            spec = AXIOMContracts.load_spec("PolicyVault")
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id, app_spec=spec)
            result = _app_call(app_client, "get_policy_status", {"agent": agent_addr})
            return int(result.abi_return) if result.abi_return is not None else 0
        except Exception as e:
            logger.error("PolicyVault get_policy_status failed: %s", e)
            return 0

# ================================================================
# 2. IntentRegistry Client
# ================================================================

class IntentRegistryClient:
    def __init__(self, algo_client: AlgorandClient, app_id: int):
        self.algo_client = algo_client
        self.app_id = app_id

    def register_session_root(self, session_id: bytes, merkle_root: bytes, sender: str = None, signer = None) -> str:
        if self.app_id <= 0: return "stub_tx"
        try:
            spec = AXIOMContracts.load_spec("IntentRegistry")
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id, app_spec=spec)
            # Add public note for explorer visibility
            note = b"x402:axiom:SESSION_ROOT:" + merkle_root.hex().encode()
            result = _app_call(app_client, "register_session_root", {"session_id": session_id, "root": merkle_root}, sender=sender, signer=signer, note=note)
            return result.tx_id
        except Exception as e:
            logger.error("IntentRegistry register_session_root failed: %s", e)
            return ""

    def register_intent(self, tx_id_hash: bytes, ipfs_cid: bytes, merkle_leaf: bytes, sender: str = None, signer = None) -> str:
        if self.app_id <= 0: return "stub_tx"
        try:
            spec = AXIOMContracts.load_spec("IntentRegistry")
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id, app_spec=spec)
            # 🔥 Money Shot: This is the Reasoning Receipt that appears on the explorer!
            note = b"x402:axiom:REASONING:" + tx_id_hash.hex().encode()[:16] + b":" + ipfs_cid
            result = _app_call(app_client, "register_intent", {"intent_hash": tx_id_hash, "api_url": merkle_leaf}, sender=sender, signer=signer, note=note)
            return result.tx_id
        except Exception as e:
            logger.error("IntentRegistry register_intent failed: %s", e)
            return ""

# ================================================================
# 3. SentinelEscrow Client
# ================================================================

class SentinelEscrowClient:
    def __init__(self, algo_client: AlgorandClient, app_id: int):
        self.algo_client = algo_client
        self.app_id = app_id

    def deposit(self, provider: str, intent_hash: bytes, deadline_rounds: int, requires_consensus: int) -> bytes:
        if self.app_id <= 0: return intent_hash[:32]
        try:
            spec = AXIOMContracts.load_spec("SentinelEscrow")
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id, app_spec=spec)
            result = _app_call(app_client, "deposit", {
                "provider": provider, 
                "intent_hash": intent_hash, 
                "deadline_rounds": deadline_rounds, 
                "requires_consensus": requires_consensus
            })
            return result.abi_return if result.abi_return is not None else b""
        except Exception as e:
            logger.error("SentinelEscrow deposit failed: %s", e)
            return b""

    def release(self, escrow_id: bytes) -> str:
        """Release escrowed funds to the API provider (SLA passed)."""
        if self.app_id <= 0: return ""
        try:
            spec = AXIOMContracts.load_spec("SentinelEscrow")
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id, app_spec=spec)
            result = _app_call(app_client, "release", {"escrow_id": escrow_id})
            return result.tx_id
        except Exception as e:
            logger.error("SentinelEscrow release failed: %s", e)
            return ""

    def refund(self, escrow_id: bytes) -> str:
        """Refund escrowed funds to the agent (SLA failed)."""
        if self.app_id <= 0: return ""
        try:
            spec = AXIOMContracts.load_spec("SentinelEscrow")
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id, app_spec=spec)
            result = _app_call(app_client, "refund", {"escrow_id": escrow_id})
            return result.tx_id
        except Exception as e:
            logger.error("SentinelEscrow refund failed: %s", e)
            return ""

    def quarantine(self, escrow_id: bytes, reason_code: int) -> str:
        """Quarantine escrowed funds for human review."""
        if self.app_id <= 0: return ""
        try:
            spec = AXIOMContracts.load_spec("SentinelEscrow")
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id, app_spec=spec)
            result = _app_call(app_client, "quarantine", {"escrow_id": escrow_id, "reason_code": reason_code})
            return result.tx_id
        except Exception as e:
            logger.error("SentinelEscrow quarantine failed: %s", e)
            return ""

    def get_escrow_status(self, escrow_id: bytes) -> int:
        """Get escrow status: 0=open, 1=released, 2=refunded, 3=quarantined."""
        if self.app_id <= 0: return -1
        try:
            spec = AXIOMContracts.load_spec("SentinelEscrow")
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id, app_spec=spec)
            result = _app_call(app_client, "get_escrow_status", {"escrow_id": escrow_id})
            return int(result.abi_return) if result.abi_return is not None else -1
        except Exception as e:
            logger.error("SentinelEscrow get_escrow_status failed: %s", e)
            return -1

# ================================================================
# 4. PaymentDNARegistry Client
# ================================================================

class PaymentDNARegistryClient:
    def __init__(self, algo_client: AlgorandClient, app_id: int):
        self.algo_client = algo_client
        self.app_id = app_id

    def update_dna(self, agent_addr: str, dna_bytes: bytes, sender: str = None, signer = None) -> str:
        if self.app_id <= 0: return "stub_tx"
        try:
            spec = AXIOMContracts.load_spec("PaymentDNARegistry")
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id, app_spec=spec)
            result = _app_call(app_client, "update_dna", {"agent": agent_addr, "observation": dna_bytes}, sender=sender, signer=signer)
            return result.tx_id
        except Exception as e:
            logger.error("PaymentDNARegistry update_dna failed: %s", e)
            return ""

# ================================================================
# 5. ConsensusVault Client
# ================================================================

class ConsensusVaultClient:
    def __init__(self, algo_client: AlgorandClient, app_id: int):
        self.algo_client = algo_client
        self.app_id = app_id

    def open_consensus(self, payment_id: bytes, escrow_id: bytes, required: int) -> str:
        if self.app_id <= 0: return "stub_tx"
        try:
            spec = AXIOMContracts.load_spec("ConsensusVault")
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id, app_spec=spec)
            result = _app_call(app_client, "open_consensus", {"payment_id": payment_id, "escrow_id": escrow_id, "required": required})
            return result.tx_id
        except Exception as e:
            logger.error("ConsensusVault open_consensus failed: %s", e)
            return ""

# ================================================================
# 6. ReputationLedger Client
# ================================================================

class ReputationLedgerClient:
    def __init__(self, algo_client: AlgorandClient, app_id: int):
        self.algo_client = algo_client
        self.app_id = app_id

    def get_tier(self, agent: str) -> int:
        if self.app_id <= 0: return 2
        try:
            spec = AXIOMContracts.load_spec("ReputationLedger")
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id, app_spec=spec)
            result = _app_call(app_client, "get_tier", {"agent": agent})
            return int(result.abi_return) if result.abi_return is not None else 2
        except Exception as e:
            logger.error("ReputationLedger get_tier failed: %s", e)
            return 2

    def get_max_payment(self, agent: str) -> float:
        tier = self.get_tier(agent)
        mapping = {0: 0.0, 1: 0.0, 2: 1.0, 3: 10.0, 4: 100.0}
        return mapping.get(tier, 1.0)

# ================================================================
# Facade
# ================================================================

class AXIOMContracts:
    def __init__(self):
        from dotenv import load_dotenv
        load_dotenv()

        self.algo_client = AlgorandClient.from_environment()

        self.policy_vault_id = int(os.getenv("POLICY_VAULT_ID", "0"))
        self.intent_registry_id = int(os.getenv("INTENT_REGISTRY_ID", "0"))
        self.sentinel_escrow_id = int(os.getenv("SENTINEL_ESCROW_ID", "0"))
        self.payment_dna_registry_id = int(os.getenv("PAYMENT_DNA_REGISTRY_ID", "0"))
        self.consensus_vault_id = int(os.getenv("CONSENSUS_VAULT_ID", "0"))
        self.reputation_ledger_id = int(os.getenv("REPUTATION_LEDGER_ID", "0"))

        self.policy_vault = PolicyVaultClient(self.algo_client, self.policy_vault_id)
        self.intent_registry = IntentRegistryClient(self.algo_client, self.intent_registry_id)
        self.sentinel_escrow = SentinelEscrowClient(self.algo_client, self.sentinel_escrow_id)
        self.payment_dna_registry = PaymentDNARegistryClient(self.algo_client, self.payment_dna_registry_id)
        self.consensus_vault = ConsensusVaultClient(self.algo_client, self.consensus_vault_id)
        self.reputation_ledger = ReputationLedgerClient(self.algo_client, self.reputation_ledger_id)

    @staticmethod
    def load_spec(name: str) -> str:
        import re
        root = Path(__file__).resolve().parent.parent.parent
        
        # Convert PascalCase/camelCase to snake_case for directory names
        slug_snake = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
        slug_snake = slug_snake.replace("_d_n_a_", "_dna_")
        slug_simple = name.lower().replace(" ", "_")
        slugs = [slug_snake, slug_snake.replace("_d_n_a", "_dna"), slug_simple, name]
        
        for slug in slugs:
            paths = [
                root / "projects" / "cleverfyre" / "smart_contracts" / "artifacts" / slug / f"{name}.arc56.json",
                Path.cwd() / "projects" / "cleverfyre" / "smart_contracts" / "artifacts" / slug / f"{name}.arc56.json",
                Path.cwd() / "smart_contracts" / "artifacts" / slug / f"{name}.arc56.json",
            ]
            for p in paths:
                if p.exists():
                    try:
                        data = json.loads(p.read_text())
                        # 🔥 FIX: Repair 'bareActions' vs 'bare_actions'
                        if "bareActions" in data and "bare_actions" not in data:
                            data["bare_actions"] = data.pop("bareActions")
                        if "structs" not in data:
                            data["structs"] = {}
                        if "methods" not in data:
                            data["methods"] = []
                        
                        logger.debug("Loaded and repaired spec for %s from %s", name, p)
                        return json.dumps(data)
                    except Exception as e:
                        logger.error("Failed to parse/repair spec for %s: %s", name, e)
                    
        logger.warning("Could not find spec for %s in any of: %s", name, slugs)
        return json.dumps({"name": name, "methods": [], "bare_actions": {"create": [], "call": []}, "structs": {}})
