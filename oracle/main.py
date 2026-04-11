"""
AXIOM SLA Oracle — FastAPI Application

Evaluates API response quality against SLA thresholds.
On pass: triggers SentinelEscrow.release() to pay the API provider.
On fail: triggers SentinelEscrow.refund() to return funds to the agent.

SLA criteria:
    - HTTP status must be 200
    - Response time must be ≤ sla_threshold_ms (default 2000ms)
    - Response schema must be valid

Run:
    uvicorn oracle.main:app --reload --port 8001
"""

import logging
import os
import json
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AXIOM SLA Oracle",
    description="Evaluates API response quality and triggers escrow settlement.",
    version="0.1.0",
)


# ─────────────────────────────────────────────────────────────────
#  REQUEST / RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────

class SLARequest(BaseModel):
    """SLA evaluation request from the AXIOM wrapper."""
    tx_id: str                         # Algorand transaction ID
    escrow_id: str                     # SentinelEscrow escrow ID
    response_time_ms: int              # API response time in milliseconds
    http_status: int                   # HTTP status code from API
    schema_valid: bool                 # Whether response matched expected schema
    sla_threshold_ms: int = 2000       # Max allowed response time
    agent_address: Optional[str] = None  # For reputation updates


class SLAResult(BaseModel):
    """SLA evaluation result."""
    passed: bool                       # True if all criteria met
    action: str                        # "released" or "refunded"
    reason: str                        # Human-readable explanation
    score_delta: int = 0               # Reputation score change
    on_chain_tx: str = ""              # Transaction ID of the on-chain settlement


# ─────────────────────────────────────────────────────────────────
#  ON-CHAIN SETTLEMENT
# ─────────────────────────────────────────────────────────────────

def _settle_escrow_on_chain(escrow_id_hex: str, passed: bool) -> str:
    """
    Call SentinelEscrow.release() or SentinelEscrow.refund() on-chain.

    Args:
        escrow_id_hex: Hex string of the 32-byte escrow ID.
        passed: If True, call release(). If False, call refund().

    Returns:
        Transaction ID of the settlement, or empty string on failure.
    """
    sentinel_app_id = int(os.getenv("SENTINEL_ESCROW_ID", "0"))
    if sentinel_app_id <= 0:
        logger.info("SentinelEscrow not deployed (ID=0) — skipping on-chain settlement")
        return ""

    try:
        from pathlib import Path
        from algokit_utils import AlgorandClient
        from algokit_utils.applications.app_client import AppClientMethodCallParams

        # Load the repaired ARC-56 spec
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from axiom_agpp.contracts.client import AXIOMContracts

        spec = AXIOMContracts.load_spec("SentinelEscrow")
        algo_client = AlgorandClient.from_environment()

        # Load deployer mnemonic as the signer for the Oracle
        deployer_mnemonic = os.getenv("DEPLOYER_MNEMONIC")
        sender = None
        if deployer_mnemonic:
            try:
                # Add account and set as default signer
                deployer_account = algo_client.account.from_mnemonic(mnemonic=deployer_mnemonic)
                algo_client.account.set_default_signer(deployer_account)
                sender = deployer_account.address
            except Exception as e:
                logger.warning("Failed to set Oracle signer: %s", e)

        app_client = algo_client.client.get_app_client_by_id(
            app_id=sentinel_app_id,
            app_spec=spec,
        )

        method = "release" if passed else "refund"
        escrow_id_bytes = bytes.fromhex(escrow_id_hex)

        result = app_client.send.call(AppClientMethodCallParams(
            method=method,
            args=[escrow_id_bytes],
            sender=sender
        ))

        tx_id = getattr(result, "tx_id", "")
        logger.info(
            "On-chain escrow %s executed — method=%s, tx_id=%s",
            escrow_id_hex[:16],
            method,
            tx_id,
        )
        return tx_id




    except Exception as e:
        logger.warning(
            "On-chain escrow settlement failed (non-fatal): %s", e
        )
        return ""


# ─────────────────────────────────────────────────────────────────
#  EVALUATION ENDPOINT
# ─────────────────────────────────────────────────────────────────

@app.post("/evaluate", response_model=SLAResult)
async def evaluate(req: SLARequest):
    """
    Evaluate an API response against SLA criteria.

    Pass criteria (ALL must be true):
        - http_status == 200
        - response_time_ms <= sla_threshold_ms
        - schema_valid == True

    On pass:
        - Trigger SentinelEscrow.release() → pay API provider
        - Reputation +5 for the agent

    On fail:
        - Trigger SentinelEscrow.refund() → return funds to agent
        - No reputation penalty (API's fault, not agent's)
    """
    passed = (
        req.http_status == 200
        and req.response_time_ms <= req.sla_threshold_ms
        and req.schema_valid
    )

    if passed:
        action = "released"
        reason = (
            f"SLA passed — status={req.http_status}, "
            f"time={req.response_time_ms}ms (≤{req.sla_threshold_ms}ms), "
            f"schema=valid"
        )
        score_delta = 5
    else:
        action = "refunded"
        failures = []
        if req.http_status != 200:
            failures.append(f"status={req.http_status} (expected 200)")
        if req.response_time_ms > req.sla_threshold_ms:
            failures.append(
                f"time={req.response_time_ms}ms (max {req.sla_threshold_ms}ms)"
            )
        if not req.schema_valid:
            failures.append("schema=invalid")
        reason = f"SLA FAILED — {', '.join(failures)}"
        score_delta = 0

    logger.info(
        "SLA %s for tx=%s escrow=%s — %s",
        "PASSED" if passed else "FAILED",
        req.tx_id[:12],
        req.escrow_id[:12],
        reason,
    )

    # Execute on-chain settlement (release or refund)
    on_chain_tx = _settle_escrow_on_chain(req.escrow_id, passed)

    if on_chain_tx:
        logger.info(
            "✅ On-chain %s confirmed: tx=%s",
            action.upper(),
            on_chain_tx,
        )
    else:
        logger.info(
            "⚠️  On-chain settlement skipped (contract not deployed or escrow not found)"
        )

    return SLAResult(
        passed=passed,
        action=action,
        reason=reason,
        score_delta=score_delta,
        on_chain_tx=on_chain_tx,
    )


# ─────────────────────────────────────────────────────────────────
#  HEALTH CHECK
# ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check for the SLA Oracle."""
    return {
        "status": "ok",
        "service": "AXIOM SLA Oracle",
        "version": "0.1.0",
    }
