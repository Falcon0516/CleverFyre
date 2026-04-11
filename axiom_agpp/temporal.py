"""
AXIOM AgPP — Temporal Query Engine

Reconstructs full AXIOM system state at any historical Algorand round.
Pure chain data — no AXIOM server required.

This is the engine behind the Temporal Scrubber in the frontend and the
"axiom audit" CLI command. Drag to any round → see the exact state.

How it works:
    1. Query Algorand Indexer for ALL transactions with note prefix "x402:axiom:"
       up to the target round
    2. Replay transactions in order, building up AgentSnapshot objects
    3. Return a SystemSnapshot with complete agent states and event log

This proves AXIOM's audit claim: the chain IS the source of truth.
No AXIOM server is required for forensic reconstruction.

Usage:
    tq = TemporalQuery()
    snapshot = tq.reconstruct_at(round_number=28041337)
    for addr, agent in snapshot.agents.items():
        print(f"{addr}: score={agent.reputation_score}, tier={agent.tier}")
"""

import base64
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List

from algosdk.v2client import indexer as idx_client

logger = logging.getLogger(__name__)

# Raw bytes prefix for filtering AXIOM transactions via Indexer
AXIOM_NOTE_PREFIX = b"x402:axiom:"


# ─────────────────────────────────────────────────────────────────
#  DATA MODELS
# ─────────────────────────────────────────────────────────────────

@dataclass
class AgentSnapshot:
    """State of a single AI agent at a specific round."""
    address: str
    reputation_score: int = 500   # starts at neutral
    tier: int = 2                 # CAUTION tier by default
    dna_drift: float = 0.0
    policy_status: str = "active"
    payments_made: int = 0
    payments_blocked: int = 0


@dataclass
class SystemSnapshot:
    """Complete AXIOM system state at a specific round."""
    round: int = 0
    agents: Dict[str, AgentSnapshot] = field(default_factory=dict)
    events: List[dict] = field(default_factory=list)

    def apply(self, note: str, tx: dict) -> None:
        """
        Apply a single transaction to update the system state.

        Infers the event type from note keywords and updates the
        relevant agent's counters and status.

        Args:
            note: Decoded UTF-8 note string from the transaction.
            tx:   Raw transaction dict from Algorand Indexer.
        """
        sender = tx.get("sender", "unknown")

        # Ensure agent exists in snapshot
        if sender not in self.agents:
            self.agents[sender] = AgentSnapshot(address=sender)
        agent = self.agents[sender]

        # Classify and apply the event
        note_upper = note.upper()

        if "BLOCK" in note_upper or "QUARANTINE" in note_upper:
            agent.payments_blocked += 1
            event_type = "BLOCKED" if "BLOCK" in note_upper else "QUARANTINE"

            # Reputation penalty for blocked payments
            agent.reputation_score = max(0, agent.reputation_score - 50)

        elif "DRIFT" in note_upper:
            agent.dna_drift += 0.1
            event_type = "DRIFT"
            agent.reputation_score = max(0, agent.reputation_score - 25)

        elif "EXPIRE" in note_upper:
            agent.policy_status = "expired"
            event_type = "EXPIRED"
            agent.reputation_score = max(0, agent.reputation_score - 100)

        elif "WARN" in note_upper:
            event_type = "WARNING"

        elif "CONSENT" in note_upper:
            event_type = "CONSENT"

        else:
            # Default: successful payment
            agent.payments_made += 1
            event_type = "PAYMENT"
            # Small reputation boost for successful payments
            agent.reputation_score = min(1000, agent.reputation_score + 5)

        # Update tier based on current reputation score
        if agent.reputation_score >= 800:
            agent.tier = 4    # EXCELLENT
        elif agent.reputation_score >= 600:
            agent.tier = 3    # GOOD
        elif agent.reputation_score >= 400:
            agent.tier = 2    # CAUTION
        elif agent.reputation_score >= 200:
            agent.tier = 1    # RESTRICTED
        else:
            agent.tier = 0    # BLACKLISTED

        # Record the event
        self.events.append({
            "type": event_type,
            "sender": sender,
            "round": tx.get("confirmed-round", 0),
            "note": note,
            "tx_id": tx.get("id", ""),
            "amount": tx.get("payment-transaction", {}).get("amount", 0),
            "ts": tx.get("round-time", 0),
        })


# ─────────────────────────────────────────────────────────────────
#  TEMPORAL QUERY ENGINE
# ─────────────────────────────────────────────────────────────────

class TemporalQuery:
    """
    Reconstructs AXIOM system state at any historical Algorand round.

    Uses only public Algorand Indexer data — no AXIOM server required.
    This proves the audit guarantee: chain is the source of truth.
    """

    def __init__(self):
        """Initialize with Indexer client from environment variables."""
        server = os.getenv("INDEXER_SERVER", "http://localhost")
        port = int(os.getenv("INDEXER_PORT", "8980"))
        token = os.getenv("INDEXER_TOKEN", "")

        url = f"{server}:{port}" if port not in (80, 443) else server

        self.indexer = idx_client.IndexerClient(
            indexer_token=token,
            indexer_address=url,
        )

    def reconstruct_at(self, round_number: int) -> SystemSnapshot:
        """
        Reconstruct the full AXIOM system state at a specific round.

        Fetches ALL AXIOM transactions up to round_number from the
        Indexer and replays them in order to build the system state.

        Args:
            round_number: The Algorand round to reconstruct state at.

        Returns:
            SystemSnapshot with all agents' states and event log.
        """
        logger.info("Reconstructing system state at round %d...", round_number)

        # Fetch all AXIOM transactions up to the target round
        all_txns = self._fetch_all_axiom_txns(round_number)

        logger.info(
            "Fetched %d AXIOM transactions for reconstruction", len(all_txns)
        )

        # Sort by confirmed round for correct replay order
        all_txns.sort(key=lambda t: t.get("confirmed-round", 0))

        # Build the snapshot by replaying transactions
        snap = SystemSnapshot(round=round_number)
        for tx in all_txns:
            raw_note = tx.get("note", "")
            try:
                note = base64.b64decode(raw_note).decode(errors="replace")
            except Exception:
                note = ""
            snap.apply(note, tx)

        logger.info(
            "Reconstruction complete — %d agents, %d events at round %d",
            len(snap.agents),
            len(snap.events),
            round_number,
        )

        return snap

    def _fetch_all_axiom_txns(self, max_round: int) -> list:
        """
        Paginate through all AXIOM transactions up to max_round.

        Uses Indexer's next-token pagination to handle large result sets.

        Args:
            max_round: Maximum round number to include.

        Returns:
            List of raw transaction dicts from Indexer.
        """
        all_txns: list = []
        next_token: str | None = None

        while True:
            kwargs: dict = {
                "note_prefix": AXIOM_NOTE_PREFIX,
                "max_round": max_round,
            }
            if next_token:
                kwargs["next_page"] = next_token

            try:
                result = self.indexer.search_transactions(**kwargs)
            except Exception as e:
                logger.warning("Indexer query failed: %s", e)
                break

            txns = result.get("transactions", [])
            all_txns.extend(txns)

            next_token = result.get("next-token")
            if not next_token:
                break

        return all_txns
