"""
AXIOM Backend — FastAPI Application

Real-time event streaming and temporal state reconstruction API.

Endpoints:
    WebSocket /ws/events   — Live stream of AXIOM payment events from Algorand
    GET       /api/state   — Temporal autopsy: reconstruct system state at any round
    GET       /health      — Health check

Run:
    uvicorn backend.main:app --reload --port 8000

The WebSocket endpoint polls Algorand Indexer every 2 seconds for new
AXIOM transactions (note prefix "x402:axiom:") and pushes normalized
events to all connected frontend clients.

The /api/state endpoint enables the Temporal Scrubber — drag to any
historical round and see the full system state reconstructed from
public chain data alone. No AXIOM server required for audit.
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.event_normalizer import (
    poll_new_events, get_last_round,
    _get_indexer, _normalize, AXIOM_NOTE_PREFIX_RAW,
)
from backend.agent_manager import manager as agent_manager

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
#  APPLICATION SETUP
# ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AXIOM Backend",
    description=(
        "Real-time event streaming and temporal state reconstruction "
        "for the Agentic Payment Protocol (AgPP) reference implementation."
    ),
    version="0.1.0",
)

# CORS — allow all origins for hackathon / development.
# In production, restrict to specific frontend domains.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────
#  WEBSOCKET CONNECTION MANAGER
# ─────────────────────────────────────────────────────────────────

# Track all active WebSocket connections for broadcasting
_active_connections: list[WebSocket] = []


async def _broadcast(event: dict) -> None:
    """
    Broadcast an event to ALL connected WebSocket clients.
    Removes disconnected clients silently.
    """
    dead: list[WebSocket] = []
    payload = json.dumps(event)

    for ws in _active_connections:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)

    # Clean up dead connections
    for ws in dead:
        if ws in _active_connections:
            _active_connections.remove(ws)


# ─────────────────────────────────────────────────────────────────
#  WEBSOCKET ENDPOINT — /ws/events
# ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/events")
async def events_ws(ws: WebSocket):
    """
    Live WebSocket stream of AXIOM payment events from Algorand.

    Connection flow:
        1. Client connects to ws://localhost:8000/ws/events
        2. Server accepts and adds client to the active connections list
        3. Every 2 seconds, server polls Algorand Indexer for new AXIOM txns
        4. Each normalized event is sent as a JSON text frame
        5. On disconnect, client is removed from the active list

    Event format (JSON):
        {
            "type":   "PAYMENT" | "BLOCKED" | "WARNING" | "QUARANTINE" | "DRIFT" | "EXPIRED",
            "tx_id":  "ALGO_TX_ID...",
            "sender": "ALGO_ADDRESS...",
            "round":  28041337,
            "note":   "x402:axiom:...",
            "amount": 1000000,
            "ts":     1719504000
        }

    Frontend components consuming this:
        - NetworkGraph.tsx  → nodes & edges update
        - AxiomTerminal.tsx → scrolling event log
        - SystemVitals.tsx  → agent counts & alert indicators
    """
    await ws.accept()
    _active_connections.append(ws)

    client_id = id(ws)
    logger.info(
        "WebSocket client connected — id=%d (total: %d)",
        client_id,
        len(_active_connections),
    )

    try:
        # ── REPLAY HISTORY ──────────────────────────────────────
        # When a new client connects (or page refreshes), send ALL
        # historical AXIOM events from the blockchain so the dashboard
        # starts fully populated. This is the "chain is the source of
        # truth" principle — no data is ever lost.
        try:
            history_indexer = _get_indexer()
            history_result = history_indexer.search_transactions(
                note_prefix=AXIOM_NOTE_PREFIX_RAW,
            )
            history_txns = history_result.get("transactions", [])
            for tx in history_txns:
                event = _normalize(tx)
                await ws.send_text(json.dumps(event))
            logger.info(
                "Replayed %d historical events to client id=%d",
                len(history_txns), client_id,
            )
        except Exception as e:
            logger.warning("History replay failed: %s", e)

        # ── LIVE POLLING LOOP ───────────────────────────────────
        while True:
            # Poll Algorand Indexer for new AXIOM transactions
            events = await poll_new_events()

            # Send each event individually as a JSON text frame
            for event in events:
                try:
                    await ws.send_text(json.dumps(event))
                except Exception:
                    # Client disconnected mid-send
                    break

            # Wait 2 seconds before next poll cycle
            # Using asyncio.sleep to keep the event loop responsive
            await asyncio.sleep(2)

    except WebSocketDisconnect:
        logger.info(
            "WebSocket client disconnected — id=%d", client_id
        )
    except Exception as e:
        logger.warning(
            "WebSocket error for client id=%d: %s", client_id, e
        )
    finally:
        # Always clean up the connection
        if ws in _active_connections:
            _active_connections.remove(ws)
        logger.info(
            "WebSocket client removed — id=%d (remaining: %d)",
            client_id,
            len(_active_connections),
        )


# ─────────────────────────────────────────────────────────────────
#  REST ENDPOINT — /api/state
# ─────────────────────────────────────────────────────────────────

@app.get("/api/state")
async def get_state(
    round: Optional[int] = Query(
        default=None,
        description=(
            "Algorand round number to reconstruct state at. "
            "If omitted, returns current live state."
        ),
    )
):
    """
    Temporal autopsy: reconstruct full AXIOM system state at any
    historical Algorand round.

    This is the API behind the Temporal Scrubber component in the frontend.
    Drag the slider to any round → this endpoint returns the exact system
    state at that moment, reconstructed entirely from public Algorand data.

    No AXIOM server is required for this audit. The chain is the source
    of truth.

    Query params:
        round (int, optional): The Algorand round to reconstruct.
                               Defaults to the latest known round.

    Returns:
        JSON with:
            round  — the reconstructed round number
            agents — dict of agent address → AgentSnapshot
            events — last 50 events up to that round (for performance)

    Example:
        GET /api/state?round=28041337

        {
            "round": 28041337,
            "agents": {
                "ALGO_ADDR_1...": {
                    "address": "ALGO_ADDR_1...",
                    "reputation_score": 750,
                    "tier": 3,
                    "dna_drift": 0.12,
                    "policy_status": "active",
                    "payments_made": 42,
                    "payments_blocked": 3
                }
            },
            "events": [ ... last 50 events ... ]
        }
    """
    # Import here to avoid circular imports and allow graceful fallback
    # if temporal.py dependencies aren't installed yet
    try:
        from axiom_agpp.temporal import TemporalQuery
    except ImportError as e:
        logger.warning("TemporalQuery not available: %s", e)
        return {
            "round": round or 0,
            "agents": {},
            "events": [],
            "error": "Temporal module not available. Install axiom_agpp dependencies.",
        }

    # Default to latest known round if none specified
    target_round = round
    if target_round is None:
        target_round = get_last_round()
        if target_round == 0:
            # No events seen yet — return empty state
            return {
                "round": 0,
                "agents": {},
                "events": [],
            }

    # Reconstruct system state from public Algorand data
    try:
        tq = TemporalQuery()
        snapshot = tq.reconstruct_at(target_round)

        # Serialize AgentSnapshot objects to dicts
        agents_serialized = {}
        for addr, agent_snap in snapshot.agents.items():
            agents_serialized[addr] = {
                "address": agent_snap.address,
                "reputation_score": agent_snap.reputation_score,
                "tier": agent_snap.tier,
                "dna_drift": agent_snap.dna_drift,
                "policy_status": agent_snap.policy_status,
                "payments_made": agent_snap.payments_made,
                "payments_blocked": agent_snap.payments_blocked,
            }

        # Return last 50 events for performance (frontend can paginate)
        recent_events = snapshot.events[-50:]

        return {
            "round": snapshot.round,
            "agents": agents_serialized,
            "events": recent_events,
        }

    except Exception as e:
        logger.error("Temporal reconstruction failed at round %d: %s", target_round, e)
        return {
            "round": target_round,
            "agents": {},
            "events": [],
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────
#  REST ENDPOINT — /api/stats
# ─────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    """
    Quick stats for the SystemVitals panel.

    Returns current connection count, last known round, and
    basic counters. Lightweight — no Indexer query needed.
    """
    return {
        "ws_connections": len(_active_connections),
        "last_round": get_last_round(),
        "status": "streaming" if _active_connections else "idle",
    }


# -----------------------------------------------------------------
#  REST ENDPOINT — /api/v1/inject-event (for stress test + demo)
# -----------------------------------------------------------------

from pydantic import BaseModel
from typing import Optional as Opt

class InjectedEvent(BaseModel):
    type: str = "PAYMENT"
    tx_id: str = ""
    sender: str = ""
    round: int = 0
    note: str = ""
    amount: int = 0
    ts: int = 0


@app.post("/api/v1/inject-event")
async def inject_event(event: InjectedEvent):
    """
    Inject an event into the WebSocket stream.

    Used by the stress test orchestrator and demo runner to push
    events to the frontend dashboard without requiring on-chain
    transactions. Each injected event is broadcast to ALL connected
    WebSocket clients immediately.

    Body (JSON):
        {
            "type": "PAYMENT" | "BLOCKED" | "WARNING" | "QUARANTINE" | "DRIFT" | "EXPIRED",
            "tx_id": "test-tx-001",
            "sender": "ALGO_ADDRESS...",
            "round": 1234,
            "note": "x402:axiom:RELEASE",
            "amount": 100000,
            "ts": 1719504000
        }
    """
    import time as _time
    evt = event.dict()
    if evt["ts"] == 0:
        evt["ts"] = int(_time.time())
    if evt["tx_id"] == "":
        evt["tx_id"] = f"injected-{int(_time.time() * 1000)}"

    await _broadcast(evt)

    logger.info(
        "Injected event type=%s sender=%s amount=%d -> %d clients",
        evt["type"], evt["sender"][:12] if evt["sender"] else "?",
        evt["amount"], len(_active_connections),
    )
    return {"status": "ok", "broadcast_to": len(_active_connections), "event": evt}


# -----------------------------------------------------------------
#  REST ENDPOINT — /api/v1/mock-402 (simulate payment flow)
# -----------------------------------------------------------------

@app.get("/api/v1/mock-402")
async def mock_402(
    x_payment: Opt[str] = Header(None),
    delay_ms: int = 0,
):
    """
    Simulate an HTTP 402 Payment Required response.

    If 'x-payment' header is present, we simulate a successful
    authenticated/paid request and return 200 OK.
    Otherwise, we return 402 Payment Required to trigger the AXIOM flow.

    Args:
        delay_ms: Optional artificial delay in milliseconds to simulate
                  a slow API server (for SLA failure testing).
    """
    import asyncio

    # Apply artificial delay if requested (for SLA failure demos)
    if delay_ms > 0:
        logger.info("Injecting artificial delay of %dms to simulate slow API", delay_ms)
        await asyncio.sleep(delay_ms / 1000.0)

    if x_payment:
        logger.info("Payment header detected: %s. Releasing resource.", x_payment[:16])
        return {
            "status": "success",
            "message": "Payment verified. Here is your weather data.",
            "data": {"temp_c": 28.5, "city": "Mumbai", "escrow_id": x_payment}
        }

    # Use the deployer address from environment as a valid provider address
    import os
    from algosdk.mnemonic import to_private_key
    from algosdk.account import address_from_private_key
    deployer_mnemonic = os.getenv("DEPLOYER_MNEMONIC")
    provider_addr = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ"
    if deployer_mnemonic:
        try:
            sk = to_private_key(deployer_mnemonic)
            provider_addr = address_from_private_key(sk)
        except Exception:
            pass

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=402,
        content={
            "error": "Payment Required",
            "payment": {
                "amount_algo": 0.1,
                "provider_address": provider_addr,
                "resource": "/api/v1/weather/current",
                "sla": {
                    "max_latency_ms": 2000,
                    "min_status": 200,
                },
            },
            "accept": "x-payment",
        },
        headers={
            'WWW-Authenticate': f'AXIOM realm="axiom-localnet" amount="100000" provider="{provider_addr}"',
        },
    )


# -----------------------------------------------------------------
#  REST ENDPOINT — /api/v1/mock-sla-fail (guaranteed SLA failure)
# -----------------------------------------------------------------

@app.get("/api/v1/mock-sla-fail")
async def mock_sla_fail(x_payment: Opt[str] = Header(None)):
    """
    A deliberately slow API endpoint that ALWAYS exceeds the SLA threshold.

    This endpoint waits 3 seconds before responding, guaranteeing that
    the SLA Oracle will flag it as FAILED and trigger an automatic
    on-chain REFUND via SentinelEscrow.

    Used for demonstrating Feature 4 (Sentinel Escrow) to judges.
    """
    import asyncio

    if x_payment:
        # Simulate a slow API — 3 second delay (SLA threshold is 2 seconds)
        logger.warning("⏳ SLA-FAIL endpoint: Deliberately stalling for 3 seconds...")
        await asyncio.sleep(3.0)

        logger.warning("⏳ SLA-FAIL endpoint: Responding after intentional delay")
        return {
            "status": "success",
            "message": "Data delivered (but too slowly — SLA breached).",
            "data": {"temp_c": 28.5, "city": "Mumbai", "sla_warning": "RESPONSE_DELAYED"},
        }

    # Use the deployer address from environment as a valid provider address
    import os
    from algosdk.mnemonic import to_private_key
    from algosdk.account import address_from_private_key
    deployer_mnemonic = os.getenv("DEPLOYER_MNEMONIC")
    provider_addr = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ"
    if deployer_mnemonic:
        try:
            sk = to_private_key(deployer_mnemonic)
            provider_addr = address_from_private_key(sk)
        except Exception:
            pass

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=402,
        content={
            "error": "Payment Required",
            "payment": {
                "amount_algo": 0.1,
                "provider_address": provider_addr,
                "resource": "/api/v1/slow-data",
                "sla": {
                    "max_latency_ms": 2000,
                    "min_status": 200,
                },
            },
            "accept": "x-payment",
        },
        headers={
            'WWW-Authenticate': f'AXIOM realm="axiom-localnet" amount="100000" provider="{provider_addr}"',
        },
    )


# -----------------------------------------------------------------
#  REST ENDPOINT — /api/v1/trigger-agent (Triggers real transaction)
# -----------------------------------------------------------------

@app.post("/api/v1/trigger-agent")
async def trigger_agent():
    """
    Trigger a real agent transaction on the LocalNet using AXIOMWrapper.
    """
    import os
    import sys
    
    # Try importing AXIOMWrapper safely
    try:
        from axiom_agpp.wrapper import AXIOMWrapper
        from dotenv import load_dotenv
        
        # We must load exactly what manual_trigger does
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        load_dotenv(os.path.join(project_root, ".env"))

        wrapper = AXIOMWrapper(
            org_id="acme",
            agent_role="researcher",
            task_goal="Frontend triggered API request",
            org_secret=b"hackathon-secret-2026",
            policy_path=os.path.join(project_root, "policy.yaml")
        )
        
        url = "http://localhost:8000/api/v1/mock-402"
        response = wrapper.call(url)
        return {"status": "success", "result": response.status_code}
    except Exception as e:
        logger.error("Failed to trigger agent: %s", e)
        return {"status": "error", "message": str(e)}

# -----------------------------------------------------------------
#  AGENT ORCHESTRATION — /api/v1/agents
# -----------------------------------------------------------------

class SpawnAgentRequest(BaseModel):
    name: str
    role: str = "researcher"
    task: str = "Perform market analysis"
    groq_api_key: Optional[str] = None

class DispatchRequest(BaseModel):
    agent_name: str
    scenario: str  # 'market_data' | 'weather_data' | 'spam_attack'

@app.get("/api/v1/agents")
async def list_agents():
    """List all active spawned agents."""
    return {"status": "ok", "agents": agent_manager.list_agents()}

@app.post("/api/v1/agents/spawn")
async def spawn_agent(req: SpawnAgentRequest):
    """Spawn a new autonomous Groq-powered agent."""
    agent = agent_manager.spawn_agent(
        name=req.name,
        role=req.role,
        task=req.task,
        api_key=req.groq_api_key
    )
    return {"status": "ok", "agent": agent.to_dict()}

@app.post("/api/v1/agents/dispatch")
async def dispatch_agent(req: DispatchRequest):
    """Trigger a scenario for a specific agent."""
    agent = agent_manager.get_agent(req.agent_name)
    if not agent:
        return JSONResponse(status_code=404, content={"error": "Agent not found"})
    
    # Run scenario in background task to avoid blocking the API
    # The AXIOM protocol transactions will happen autonomously.
    asyncio.create_task(asyncio.to_thread(agent.run_scenario, req.scenario))
    
    return {
        "status": "dispatched",
        "agent": req.agent_name,
        "scenario": req.scenario
    }

# -----------------------------------------------------------------
#  HEALTH CHECK
# -----------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check -- used by uptime monitors and Docker healthcheck."""
    return {
        "status": "ok",
        "service": "AXIOM Backend",
        "version": "0.1.0",
        "ws_clients": len(_active_connections),
        "last_round": get_last_round(),
    }


# ─────────────────────────────────────────────────────────────────
#  STARTUP / SHUTDOWN EVENTS
# ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    """Log startup and validate environment."""
    import os

    indexer_server = os.getenv("INDEXER_SERVER", "http://localhost")
    indexer_port = os.getenv("INDEXER_PORT", "8980")

    logger.info("═══════════════════════════════════════════════")
    logger.info("  AXIOM Backend starting")
    logger.info("  Indexer: %s:%s", indexer_server, indexer_port)
    logger.info("  WebSocket: ws://0.0.0.0:8000/ws/events")
    logger.info("  State API: http://0.0.0.0:8000/api/state")
    logger.info("═══════════════════════════════════════════════")


@app.on_event("shutdown")
async def on_shutdown():
    """Close all WebSocket connections on shutdown."""
    logger.info("AXIOM Backend shutting down — closing %d WebSocket connections",
                len(_active_connections))
    for ws in _active_connections[:]:
        try:
            await ws.close()
        except Exception:
            pass
    _active_connections.clear()
