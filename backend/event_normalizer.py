"""
AXIOM Backend — Event Normalizer

Polls Algorand Indexer for new AXIOM transactions (note prefix "x402:axiom:")
and normalizes them into a standard event format for the WebSocket feed
and frontend consumption.

Maintains a global _last_round counter so each poll only fetches new
transactions since the last known round. This prevents duplicate events
and keeps the feed efficient.

Event types are inferred from note content keywords:
  BLOCK      → "BLOCKED"    (payment rejected by policy/reputation)
  WARN       → "WARNING"    (approaching policy limits)
  QUARANTINE → "QUARANTINE" (held in SentinelEscrow for review)
  DRIFT      → "DRIFT"      (behavioral DNA drift detected)
  EXPIRE     → "EXPIRED"    (Dead Man's Switch policy expired)
  default    → "PAYMENT"    (normal successful payment)

Usage:
    from backend.event_normalizer import poll_new_events
    events = await poll_new_events()  # returns list[dict]
"""

import os
import base64
import logging
from typing import Optional

from algosdk.v2client import indexer as idx_client

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
#  GLOBAL STATE
# ─────────────────────────────────────────────────────────────────

# Track the last processed round to avoid re-fetching old transactions.
# Starts at 0 — on first poll, we fetch everything with the AXIOM prefix.
_last_round: int = 0

# Base64-encoded note prefix for filtering AXIOM transactions via Indexer.
# Raw bytes: b"x402:axiom:" → base64: "eDQwMjpheGlvbTo="
AXIOM_NOTE_PREFIX_B64: str = base64.b64encode(b"x402:axiom:").decode()

# Raw prefix for local matching against decoded notes
AXIOM_NOTE_PREFIX_RAW: bytes = b"x402:axiom:"


# ─────────────────────────────────────────────────────────────────
#  INDEXER CLIENT
# ─────────────────────────────────────────────────────────────────

def _get_indexer() -> idx_client.IndexerClient:
    """
    Create an Algorand Indexer client from environment variables.

    Env vars:
        INDEXER_SERVER  — Indexer base URL (default: http://localhost)
        INDEXER_PORT    — Indexer port (default: 8980)
        INDEXER_TOKEN   — Indexer API token (default: empty for public nodes)
    """
    server = os.getenv("INDEXER_SERVER", "http://localhost")
    port = int(os.getenv("INDEXER_PORT", "8980"))
    token = os.getenv("INDEXER_TOKEN", "")

    # Build the full URL — Indexer client expects "http://host:port"
    url = f"{server}:{port}" if port not in (80, 443) else server

    return idx_client.IndexerClient(
        indexer_token=token,
        indexer_address=url,
    )


# ─────────────────────────────────────────────────────────────────
#  POLL FOR NEW EVENTS
# ─────────────────────────────────────────────────────────────────

async def poll_new_events() -> list[dict]:
    """
    Query Algorand Indexer for new AXIOM transactions since the last
    known round.

    Returns a list of normalized event dicts, each with:
        type   — event type string (PAYMENT, BLOCKED, WARNING, etc.)
        tx_id  — Algorand transaction ID
        sender — sender's Algorand address
        round  — confirmed round number
        note   — decoded note string (UTF-8)
        amount — payment amount in microALGO (0 for app calls)
        ts     — Unix timestamp (round-time from Indexer)

    This function is async for compatibility with the FastAPI WebSocket
    loop, but the Indexer call itself is synchronous (algosdk limitation).
    """
    global _last_round

    indexer = _get_indexer()

    try:
        # Build query kwargs — only fetch transactions after _last_round
        kwargs: dict = {
            "note_prefix": AXIOM_NOTE_PREFIX_RAW,
            "limit": 50
        }

        if _last_round > 0:
            kwargs["min_round"] = _last_round + 1
        else:
            try:
                import algokit_utils
                alg_client = algokit_utils.AlgorandClient.from_environment()
                status = alg_client.client.algod.status()
                kwargs["min_round"] = max(1, status.get("last-round", 1000) - 1000)
            except Exception:
                pass

        # Execute the Indexer search
        result = indexer.search_transactions(**kwargs)
        txns = result.get("transactions", [])

        if not txns:
            return []

        # Update the global round counter to the highest seen round
        max_round = max(
            tx.get("confirmed-round", 0) for tx in txns
        )
        if max_round > _last_round:
            _last_round = max_round
            logger.debug("Event normalizer advanced to round %d", _last_round)

        # Normalize each transaction into our standard event format
        events = [_normalize(tx) for tx in txns]

        if events:
            logger.info(
                "Polled %d new AXIOM events (rounds %d–%d)",
                len(events),
                min(e["round"] for e in events),
                max(e["round"] for e in events),
            )

        return events

    except Exception as e:
        logger.warning("Indexer poll failed (will retry next cycle): %s", e)
        return []


# ─────────────────────────────────────────────────────────────────
#  TRANSACTION NORMALIZER
# ─────────────────────────────────────────────────────────────────

def _normalize(tx: dict) -> dict:
    """
    Normalize a raw Algorand Indexer transaction dict into a standard
    AXIOM event format.

    The event type is inferred from keywords found in the decoded
    transaction note:
        "BLOCK"      → BLOCKED
        "WARN"       → WARNING
        "QUARANTINE" → QUARANTINE
        "DRIFT"      → DRIFT
        "EXPIRE"     → EXPIRED
        (default)    → PAYMENT

    Args:
        tx: Raw transaction dict from Algorand Indexer API.

    Returns:
        Normalized event dict with keys: type, tx_id, sender, round,
        note, amount, ts.
    """
    # Decode the base64-encoded note field
    raw_note = tx.get("note", "")
    note = ""
    if raw_note:
        try:
            note = base64.b64decode(raw_note).decode(errors="replace")
        except Exception:
            note = ""

    # Infer event type from note content keywords
    event_type = _classify_event(note)

    # Extract payment amount (microALGO) — may be in payment-transaction
    # or asset-transfer-transaction depending on tx type
    amount = 0
    if "payment-transaction" in tx:
        amount = tx["payment-transaction"].get("amount", 0)
    elif "asset-transfer-transaction" in tx:
        amount = tx["asset-transfer-transaction"].get("amount", 0)

    return {
        "type": event_type,
        "tx_id": tx.get("id", ""),
        "sender": tx.get("sender", ""),
        "round": tx.get("confirmed-round", 0),
        "note": note,
        "amount": amount,
        "ts": tx.get("round-time", 0),
    }


def _classify_event(note: str) -> str:
    """
    Classify the event type from the decoded note string.

    Checks for keywords in priority order (most specific first)
    to avoid misclassification — e.g., "QUARANTINE_BLOCK" should
    match QUARANTINE, not BLOCK.

    Args:
        note: Decoded UTF-8 note string from the transaction.

    Returns:
        Event type string: BLOCKED, WARNING, QUARANTINE, DRIFT,
        EXPIRED, or PAYMENT.
    """
    note_upper = note.upper()

    # Priority order: most specific keywords first
    if "QUARANTINE" in note_upper:
        return "QUARANTINE"
    if "BLOCK" in note_upper:
        return "BLOCKED"
    if "WARN" in note_upper:
        return "WARNING"
    if "DRIFT" in note_upper:
        return "DRIFT"
    if "EXPIRE" in note_upper:
        return "EXPIRED"

    # Default: normal successful payment
    return "PAYMENT"


def get_last_round() -> int:
    """Return the current value of the global _last_round counter."""
    return _last_round


def reset_last_round(round_num: int = 0) -> None:
    """
    Reset the global _last_round counter.
    Useful for testing or re-scanning from a specific point.
    """
    global _last_round
    _last_round = round_num
    logger.info("Event normalizer reset to round %d", round_num)
