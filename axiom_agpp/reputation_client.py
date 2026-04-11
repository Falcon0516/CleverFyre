"""
AXIOM AgPP — Reputation Client

SDK client for reading and updating agent reputation scores from the
ReputationLedger smart contract on Algorand.

Tier system:
    4 — EXCELLENT  (800+)   auto-release, unlimited within policy
    3 — GOOD       (600-799) up to 5 ALGO/call
    2 — CAUTION    (400-599) up to 0.5 ALGO/call, intent logging mandatory
    1 — RESTRICTED (200-399) quarantine, human required
    0 — BLACKLISTED (0-199)  SentinelEscrow rejects all attempts

Usage:
    from axiom_agpp.reputation_client import ReputationClient
    rc = ReputationClient()
    score = rc.get_score(agent_addr)
    tier = rc.get_tier(agent_addr)
"""

import logging
import os
from typing import Optional

from algokit_utils import AlgorandClient

logger = logging.getLogger(__name__)

# Tier boundaries
TIER_THRESHOLDS = {
    4: 800,   # EXCELLENT
    3: 600,   # GOOD
    2: 400,   # CAUTION
    1: 200,   # RESTRICTED
    0: 0,     # BLACKLISTED
}

TIER_NAMES = {
    0: "BLACKLISTED",
    1: "RESTRICTED",
    2: "CAUTION",
    3: "GOOD",
    4: "EXCELLENT",
}


class ReputationClient:
    """
    Client for interacting with the ReputationLedger smart contract.

    Reads agent reputation scores from box storage and provides
    tier classification for the AXIOM payment pipeline.
    """

    def __init__(self, app_id: Optional[int] = None):
        """
        Initialize the ReputationClient.

        Args:
            app_id: Application ID of the deployed ReputationLedger contract.
                    Falls back to REPUTATION_LEDGER_ID env var.
        """
        self.app_id = app_id or int(os.getenv("REPUTATION_LEDGER_ID", "0"))
        self.client = AlgorandClient.from_environment()

        logger.info("ReputationClient initialized — app_id=%d", self.app_id)

    def get_score(self, agent_addr: str) -> int:
        """
        Get the reputation score for an agent.

        Reads from ReputationLedger box storage on-chain.
        Falls back to default score (500) if contract is not deployed
        or agent is not registered.

        Args:
            agent_addr: Algorand address of the agent.

        Returns:
            Reputation score (0-1000).
        """
        if self.app_id == 0:
            logger.debug("ReputationLedger not deployed — returning default 500")
            return 500

        try:
            # Read box storage: key = agent address decoded bytes
            import algosdk.encoding
            import base64

            addr_bytes = algosdk.encoding.decode_address(agent_addr)
            algod_client = self.client.client.algod

            box_response = algod_client.application_box_by_name(
                self.app_id, addr_bytes
            )
            box_value = box_response.get("value", "")

            if box_value:
                raw = base64.b64decode(box_value)
                # ReputationRecord layout (ARC4):
                #   score:        8 bytes (uint64)
                #   drift_events: 8 bytes (uint64)
                if len(raw) >= 8:
                    score = int.from_bytes(raw[:8], "big")
                    return min(max(score, 0), 1000)

        except Exception as e:
            logger.debug("Box read failed for %s: %s", agent_addr[:8], e)

        # Default: neutral reputation
        return 500

    def get_tier(self, agent_addr: str) -> int:
        """
        Get the reputation tier for an agent.

        Args:
            agent_addr: Algorand address of the agent.

        Returns:
            Tier number (0-4):
                4 = EXCELLENT, 3 = GOOD, 2 = CAUTION,
                1 = RESTRICTED, 0 = BLACKLISTED
        """
        score = self.get_score(agent_addr)

        if score >= 800:
            return 4
        if score >= 600:
            return 3
        if score >= 400:
            return 2
        if score >= 200:
            return 1
        return 0

    def get_tier_name(self, agent_addr: str) -> str:
        """Get the human-readable tier name for an agent."""
        return TIER_NAMES.get(self.get_tier(agent_addr), "UNKNOWN")

    def update_score(
        self,
        agent_addr: str,
        delta: int,
        negative: bool,
        sender_key: str,
    ) -> str:
        """
        Update an agent's reputation score on-chain.

        Only callable by SentinelEscrow or PolicyVault contracts.

        Args:
            agent_addr: Algorand address of the agent.
            delta:      Score change amount (always positive).
            negative:   If True, subtract delta. If False, add delta.
            sender_key: Private key of the authorized caller.

        Returns:
            Transaction ID of the update call (empty string if stub).
        """
        if self.app_id == 0:
            logger.debug("ReputationLedger not deployed — score update skipped")
            return ""

        try:
            from axiom_agpp.contracts.client import AXIOMContracts
            spec = AXIOMContracts.load_spec("ReputationLedger")
            app_client = self.client.client.get_app_client_by_id(
                app_id=self.app_id,
                app_spec=spec
            )

            result = app_client.call(
                "update_score",
                agent=agent_addr,
                delta=delta,
                is_negative=1 if negative else 0,
            )

            tx_id = result.tx_id if hasattr(result, "tx_id") else ""
            action = "-" if negative else "+"
            logger.info(
                "Reputation updated: %s %s%d → tx=%s",
                agent_addr[:8],
                action,
                delta,
                tx_id,
            )
            return tx_id

        except Exception as e:
            logger.error("Failed to update reputation: %s", e)
            return ""

    def get_max_payment(self, agent_addr: str) -> float:
        """
        Get the maximum payment amount allowed for an agent based on tier.

        Returns:
            Max payment in ALGO:
                EXCELLENT: unlimited (999999)
                GOOD: 5.0
                CAUTION: 0.5
                RESTRICTED: 0.0 (quarantine required)
                BLACKLISTED: 0.0 (rejected)
        """
        tier = self.get_tier(agent_addr)
        limits = {
            4: 999999.0,  # EXCELLENT — unlimited within policy
            3: 5.0,       # GOOD
            2: 0.5,       # CAUTION
            1: 0.0,       # RESTRICTED — quarantine
            0: 0.0,       # BLACKLISTED — reject
        }
        return limits.get(tier, 0.0)
