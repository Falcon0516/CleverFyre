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
        reason = f"SLA failed — {', '.join(failures)}"
        score_delta = 0

    logger.info(
        "SLA %s for tx=%s escrow=%s — %s",
        "PASSED" if passed else "FAILED",
        req.tx_id[:12],
        req.escrow_id[:12],
        reason,
    )

    # TODO: Wire to SentinelEscrow on-chain calls after contract deployment
    # sentinel_app_id = int(os.getenv("SENTINEL_ESCROW_ID", "0"))
    # if sentinel_app_id > 0:
    #     from algokit_utils import AlgorandClient
    #     client = AlgorandClient.from_environment()
    #     app_client = client.client.get_app_client_by_id(app_id=sentinel_app_id)
    #     if passed:
    #         app_client.call("release", escrow_id=bytes.fromhex(req.escrow_id))
    #     else:
    #         app_client.call("refund", escrow_id=bytes.fromhex(req.escrow_id))

    return SLAResult(
        passed=passed,
        action=action,
        reason=reason,
        score_delta=score_delta,
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
