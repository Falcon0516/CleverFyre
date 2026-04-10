"""
AXIOM AgPP — Contracts Client

SDK client for interacting with the 6 core AXIOM smart contracts on Algorand.
Abstracts away ABI encoding and application call details.

Contracts (matching Person A's implementations):
    1. PolicyVault         — Graduated Dead Man Switch enforcement
    2. IntentRegistry      — Commits Merkle roots + IPFS CIDs
    3. SentinelEscrow      — Holds funds for SLA-contingent release
    4. PaymentDNARegistry  — Stores 32-dim behavioral fingerprint vectors
    5. ConsensusVault      — Coordinates M-of-N peer agent consensus
    6. ReputationLedger    — Maintains agent scores (0-1000) and tiers

Usage:
    from axiom_agpp.contracts.client import AXIOMContracts
    contracts = AXIOMContracts()
    tier = contracts.policy_vault.check_and_enforce(agent_addr, amount)
"""

import logging
import os
from typing import Optional

from algokit_utils import AlgorandClient

logger = logging.getLogger(__name__)


# ================================================================
# 1. PolicyVault Client
# ================================================================

class PolicyVaultClient:
    """Client for PolicyVault contract — graduated Dead Man Switch."""

    def __init__(self, algo_client: AlgorandClient, app_id: int):
        self.algo_client = algo_client
        self.app_id = app_id

    def check_and_enforce(self, agent_addr: str, amount: int) -> int:
        """
        Check agent's policy tier and enforce spend caps.
        Returns: 0=allowed, 1=warn(1 ALGO cap), 2=capped(0.1 ALGO), 3=frozen
        """
        if self.app_id == 0:
            logger.debug("PolicyVault not deployed — stub: returning 0 (allowed)")
            return 0
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call(
                "check_and_enforce",
                agent=agent_addr,
                amount=amount,
            )
            tier = result.return_value if hasattr(result, "return_value") else 0
            logger.info("PolicyVault check: agent=%s… tier=%d", agent_addr[:8], tier)
            return int(tier)
        except Exception as e:
            logger.error("PolicyVault check_and_enforce failed: %s", e)
            return 0

    def get_policy_status(self, agent_addr: str) -> int:
        """Returns current tier for agent."""
        if self.app_id == 0:
            return 0
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call("get_policy_status", agent=agent_addr)
            return int(result.return_value) if hasattr(result, "return_value") else 0
        except Exception as e:
            logger.error("PolicyVault get_policy_status failed: %s", e)
            return 0


# ================================================================
# 2. IntentRegistry Client
# ================================================================

class IntentRegistryClient:
    """Client for IntentRegistry contract — Merkle roots + IPFS CIDs."""

    def __init__(self, algo_client: AlgorandClient, app_id: int):
        self.algo_client = algo_client
        self.app_id = app_id

    def register_session_root(self, session_id: bytes, merkle_root: bytes,
                               sender_addr: str = "") -> str:
        """Register a session's Merkle root on-chain."""
        if self.app_id == 0:
            logger.debug("IntentRegistry not deployed — stub commit")
            return "stub_tx_id"
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call(
                "register_session_root",
                session_id=session_id,
                merkle_root=merkle_root,
            )
            tx_id = result.tx_id if hasattr(result, "tx_id") else "unknown"
            logger.info("Registered session root %s… tx=%s", merkle_root.hex()[:10], tx_id)
            return tx_id
        except Exception as e:
            logger.error("IntentRegistry register_session_root failed: %s", e)
            return ""

    def register_intent(self, tx_id_hash: bytes, ipfs_cid: bytes,
                         merkle_leaf: bytes, sender_addr: str = "") -> str:
        """Register an intent's IPFS CID and Merkle leaf."""
        if self.app_id == 0:
            logger.debug("IntentRegistry not deployed — stub register_intent")
            return "stub_tx_id"
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call(
                "register_intent",
                tx_id=tx_id_hash,
                ipfs_cid=ipfs_cid,
                merkle_leaf=merkle_leaf,
            )
            tx_id = result.tx_id if hasattr(result, "tx_id") else "unknown"
            logger.info("Registered intent tx=%s", tx_id)
            return tx_id
        except Exception as e:
            logger.error("IntentRegistry register_intent failed: %s", e)
            return ""

    def get_ipfs_cid(self, tx_id_hash: bytes) -> bytes:
        """Retrieve IPFS CID for a given transaction hash."""
        if self.app_id == 0:
            return b""
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call("get_ipfs_cid", tx_id_hash=tx_id_hash)
            return result.return_value if hasattr(result, "return_value") else b""
        except Exception as e:
            logger.error("IntentRegistry get_ipfs_cid failed: %s", e)
            return b""


# ================================================================
# 3. SentinelEscrow Client
# ================================================================

class SentinelEscrowClient:
    """Client for SentinelEscrow contract — payment hub."""

    def __init__(self, algo_client: AlgorandClient, app_id: int):
        self.algo_client = algo_client
        self.app_id = app_id

    def deposit(self, provider_addr: str, intent_hash: bytes,
                deadline_rounds: int = 100, requires_consensus: int = 0,
                amount: int = 0, sender_key: str = "") -> bytes:
        """
        Deposit ALGO into escrow. Returns 32-byte escrow_id.
        """
        if self.app_id == 0:
            import hashlib, time
            fake_id = hashlib.sha256(
                f"stub:{provider_addr}:{time.time()}".encode()
            ).digest()
            logger.debug("SentinelEscrow not deployed — stub deposit id=%s…", fake_id.hex()[:10])
            return fake_id
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call(
                "deposit",
                provider=provider_addr,
                intent_hash=intent_hash,
                deadline_rounds=deadline_rounds,
                requires_consensus=requires_consensus,
            )
            escrow_id = result.return_value if hasattr(result, "return_value") else b""
            logger.info("Deposited escrow id=%s…", escrow_id.hex()[:10] if escrow_id else "?")
            return escrow_id
        except Exception as e:
            logger.error("SentinelEscrow deposit failed: %s", e)
            return b""

    def release(self, escrow_id: bytes) -> str:
        """Release escrowed ALGO to provider (SLA passed)."""
        if self.app_id == 0:
            logger.debug("SentinelEscrow not deployed — stub release")
            return "stub_release_tx"
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call("release", escrow_id=escrow_id)
            return result.tx_id if hasattr(result, "tx_id") else ""
        except Exception as e:
            logger.error("SentinelEscrow release failed: %s", e)
            return ""

    def refund(self, escrow_id: bytes) -> str:
        """Refund escrowed ALGO to payer (SLA failed or timeout)."""
        if self.app_id == 0:
            logger.debug("SentinelEscrow not deployed — stub refund")
            return "stub_refund_tx"
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call("refund", escrow_id=escrow_id)
            return result.tx_id if hasattr(result, "tx_id") else ""
        except Exception as e:
            logger.error("SentinelEscrow refund failed: %s", e)
            return ""

    def quarantine(self, escrow_id: bytes, reason_code: int = 1) -> str:
        """Flag a payment for human review."""
        if self.app_id == 0:
            logger.debug("SentinelEscrow not deployed — stub quarantine (reason=%d)", reason_code)
            return "stub_quarantine_tx"
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call(
                "quarantine", escrow_id=escrow_id, reason_code=reason_code
            )
            return result.tx_id if hasattr(result, "tx_id") else ""
        except Exception as e:
            logger.error("SentinelEscrow quarantine failed: %s", e)
            return ""

    def admin_resolve(self, escrow_id: bytes, approved: bool) -> str:
        """Operator approves or rejects quarantined payment."""
        if self.app_id == 0:
            return "stub_resolve_tx"
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call(
                "admin_resolve", escrow_id=escrow_id,
                approved=1 if approved else 0
            )
            return result.tx_id if hasattr(result, "tx_id") else ""
        except Exception as e:
            logger.error("SentinelEscrow admin_resolve failed: %s", e)
            return ""

    def get_escrow_status(self, escrow_id: bytes) -> int:
        """Returns status: 0=open, 1=released, 2=refunded, 3=quarantined."""
        if self.app_id == 0:
            return 0
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call("get_escrow_status", escrow_id=escrow_id)
            return int(result.return_value) if hasattr(result, "return_value") else 0
        except Exception as e:
            logger.error("SentinelEscrow get_escrow_status failed: %s", e)
            return 0


# ================================================================
# 4. PaymentDNARegistry Client
# ================================================================

class PaymentDNARegistryClient:
    """Client for PaymentDNARegistry — 32-dim behavioral fingerprints."""

    def __init__(self, algo_client: AlgorandClient, app_id: int):
        self.algo_client = algo_client
        self.app_id = app_id

    def update_dna(self, agent_addr: str, dna_bytes: bytes, sender_addr: str = "") -> str:
        """Store an agent's 32-byte quantized DNA vector on-chain."""
        if self.app_id == 0:
            logger.debug("PaymentDNARegistry not deployed — stub update")
            return "stub_tx_id"
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call(
                "update_dna",
                agent=agent_addr,
                observation=dna_bytes,
            )
            tx_id = result.tx_id if hasattr(result, "tx_id") else "unknown"
            logger.info("Updated DNA for %s… tx=%s", agent_addr[:8], tx_id)
            return tx_id
        except Exception as e:
            logger.error("PaymentDNARegistry update_dna failed: %s", e)
            return ""

    def get_drift_score(self, agent_addr: str, observation: bytes) -> int:
        """Returns cosine distance * 1000 as integer (0-1000)."""
        if self.app_id == 0:
            return 0
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call(
                "get_drift_score", agent=agent_addr, observation=observation
            )
            return int(result.return_value) if hasattr(result, "return_value") else 0
        except Exception as e:
            logger.error("PaymentDNARegistry get_drift_score failed: %s", e)
            return 0


# ================================================================
# 5. ConsensusVault Client
# ================================================================

class ConsensusVaultClient:
    """Client for ConsensusVault — M-of-N peer agent consensus."""

    def __init__(self, algo_client: AlgorandClient, app_id: int):
        self.algo_client = algo_client
        self.app_id = app_id

    def open_consensus(self, payment_id: bytes, escrow_id: bytes,
                        required: int) -> str:
        """Create a new consensus record."""
        if self.app_id == 0:
            logger.debug("ConsensusVault not deployed — stub open_consensus")
            return "stub_tx_id"
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call(
                "open_consensus",
                payment_id=payment_id,
                escrow_id=escrow_id,
                required=required,
            )
            return result.tx_id if hasattr(result, "tx_id") else ""
        except Exception as e:
            logger.error("ConsensusVault open_consensus failed: %s", e)
            return ""

    def execute_if_consensus(self, payment_id: bytes) -> int:
        """Check if consensus reached, execute if so. Returns 1=executed, 0=waiting."""
        if self.app_id == 0:
            return 1  # stub: auto-approve
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call("execute_if_consensus", payment_id=payment_id)
            return int(result.return_value) if hasattr(result, "return_value") else 0
        except Exception as e:
            logger.error("ConsensusVault execute_if_consensus failed: %s", e)
            return 0


# ================================================================
# 6. ReputationLedger Client
# ================================================================

class ReputationLedgerClient:
    """Client for ReputationLedger — social trust layer."""

    def __init__(self, algo_client: AlgorandClient, app_id: int):
        self.algo_client = algo_client
        self.app_id = app_id

    def get_tier(self, agent_addr: str) -> int:
        """
        Returns tier: 0=BLACKLISTED, 1=RESTRICTED, 2=CAUTION, 3=GOOD, 4=EXCELLENT.
        Stub returns 2 (CAUTION) when contracts not deployed.
        """
        if self.app_id == 0:
            logger.debug("ReputationLedger not deployed — stub: returning tier 2 (CAUTION)")
            return 2
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call("get_tier", agent=agent_addr)
            tier = int(result.return_value) if hasattr(result, "return_value") else 2
            logger.info("ReputationLedger tier for %s… = %d", agent_addr[:8], tier)
            return tier
        except Exception as e:
            logger.error("ReputationLedger get_tier failed: %s", e)
            return 2

    def get_score(self, agent_addr: str) -> int:
        """Returns score 0-1000. Stub returns 500 (neutral)."""
        if self.app_id == 0:
            return 500
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call("get_score", agent=agent_addr)
            return int(result.return_value) if hasattr(result, "return_value") else 500
        except Exception as e:
            logger.error("ReputationLedger get_score failed: %s", e)
            return 500

    def update_score(self, agent_addr: str, delta: int,
                      is_negative: bool, sender_key: str = "") -> str:
        """Adjust agent's reputation score."""
        if self.app_id == 0:
            logger.debug("ReputationLedger not deployed — stub update_score")
            return "stub_tx_id"
        try:
            app_client = self.algo_client.client.get_app_client_by_id(app_id=self.app_id)
            result = app_client.call(
                "update_score",
                agent=agent_addr,
                delta=delta,
                is_negative=1 if is_negative else 0,
            )
            return result.tx_id if hasattr(result, "tx_id") else ""
        except Exception as e:
            logger.error("ReputationLedger update_score failed: %s", e)
            return ""


# ================================================================
# Facade
# ================================================================

class AXIOMContracts:
    """Facade for all 6 AXIOM smart contracts."""

    def __init__(self):
        """Initialize clients for all deployed contracts using .env IDs."""
        from dotenv import load_dotenv
        load_dotenv()

        self.algo_client = AlgorandClient.from_environment()

        self.policy_vault_id = int(os.getenv("POLICY_VAULT_ID", "0"))
        self.intent_registry_id = int(os.getenv("INTENT_REGISTRY_ID", "0"))
        self.sentinel_escrow_id = int(os.getenv("SENTINEL_ESCROW_ID", "0"))
        self.payment_dna_registry_id = int(os.getenv("PAYMENT_DNA_REGISTRY_ID", "0"))
        self.consensus_vault_id = int(os.getenv("CONSENSUS_VAULT_ID", "0"))
        self.reputation_ledger_id = int(os.getenv("REPUTATION_LEDGER_ID", "0"))

        all_ids = [
            self.policy_vault_id, self.intent_registry_id,
            self.sentinel_escrow_id, self.payment_dna_registry_id,
            self.consensus_vault_id, self.reputation_ledger_id,
        ]
        if any(id == 0 for id in all_ids):
            logger.warning(
                "Some AXIOM contracts not deployed (ID=0). "
                "SDK will use stubs. Run deploy.py to populate .env."
            )

        self.policy_vault = PolicyVaultClient(
            self.algo_client, self.policy_vault_id
        )
        self.intent_registry = IntentRegistryClient(
            self.algo_client, self.intent_registry_id
        )
        self.sentinel_escrow = SentinelEscrowClient(
            self.algo_client, self.sentinel_escrow_id
        )
        self.payment_dna_registry = PaymentDNARegistryClient(
            self.algo_client, self.payment_dna_registry_id
        )
        self.consensus_vault = ConsensusVaultClient(
            self.algo_client, self.consensus_vault_id
        )
        self.reputation_ledger = ReputationLedgerClient(
            self.algo_client, self.reputation_ledger_id
        )

        logger.info(
            "AXIOMContracts initialized — "
            "PV=%d IR=%d SE=%d DNA=%d CV=%d RL=%d",
            self.policy_vault_id, self.intent_registry_id,
            self.sentinel_escrow_id, self.payment_dna_registry_id,
            self.consensus_vault_id, self.reputation_ledger_id,
        )
