# AgPP v1 — Agentic Payment Protocol Specification

**Status:** Draft v1.0  
**Authors:** AXIOM Team — HACK.ALGO × GDG × REVA University 2026  
**Reference Implementation:** AXIOM — live on Algorand Testnet  
**Date:** 2026-04-10

---

## Abstract

AgPP defines a 4-layer standard for **trustworthy AI-to-API payments**.

It specifies identity derivation, intent documentation, on-chain enforcement,
and public audit for autonomous AI agents making payments on behalf of humans.
Any team can implement AgPP independently; AXIOM is the canonical reference.

The core problem: AI agents on protocols like x402 can autonomously spend real
money. Today, nobody can cryptographically prove **why** a payment was made —
only that it happened. AgPP makes that proof possible, tamper-proof, and auditable
by anyone with access to a public blockchain, forever.

---

## Layer 1 — Identity

```
agent_addr = HKDF-SHA256(salt="agpp-v1", ikm = org_id + ":" + role + ":" + sha256(code))
```

- **Deterministic.** Same organisation, role, and code → same address. No wallet file required.  
- **Tamper-detectable.** Change one byte of the agent's source code → address changes automatically. Any party can verify integrity.  
- **Revocable by design.** Updating the agent binary rotates the address; the old address stops receiving policy approvals instantly.

Implementation: `HMAC-SHA256(key=org_secret, data=ikm)` produces a 32-byte seed. An Algorand keypair is derived deterministically from that seed using `algosdk`.

---

## Layer 2 — Intent

Every payment is preceded by an **AgPP Intent Document** (JSON, stored on IPFS):

| Field | Description |
|---|---|
| `schema` | `"agpp/v1"` – version discriminator |
| `agent_id` | Algorand address of the paying agent |
| `task_canonical` | Normalised description of the task this payment serves |
| `api_url` | Exact URL being called |
| `api_selection_reason` | How this API was chosen (semantic routing justification) |
| `expected_output_schema` | JSON Schema the response must satisfy |
| `policy_commitment` | Hash of the active policy config at time of payment |
| `timestamp_round` | Algorand round at which intent was created |
| `chain_id` | Parent intent hash (if this is a delegated sub-payment) |

The **Intent hash** (`sha256(intent_json)`) becomes a Merkle leaf.  
A session's Merkle root is committed on Algorand via `IntentRegistry.register_session_root()`.

**Selective disclosure:** to prove a single payment to a regulator, reveal one
Merkle proof path. No other payment in the session is revealed.

---

## Layer 3 — Enforcement

Six ARC-4 smart contracts implement AgPP on Algorand:

| Contract | Role |
|---|---|
| `PolicyVault` | Dead Man's Switch — graduated freeze on missed operator renewals |
| `IntentRegistry` | Merkle root + IPFS CID registry for all intent documents |
| `SentinelEscrow` | Payment hub — escrow, release, refund, quarantine |
| `PaymentDNARegistry` | 32-dim behavioral fingerprint per agent |
| `ConsensusVault` | M-of-N atomic peer consent for high-value payments |
| `ReputationLedger` | 0–1000 trust score with tier-gated spend limits |

**All payment enforcement is cryptographic and on-chain.  
No side channels. No admin overrides.**

### Dead Man's Switch (PolicyVault)

The operator must renew the agent's policy each `renewal_window_rounds` (~30 min).
Missed renewals trigger a **graduated freeze**:

| Missed Renewals | Tier | Effect |
|---|---|---|
| 0 | 0 | Full access |
| 1 | 1 | Capped at 1 ALGO per call |
| 2 | 2 | Capped at 0.1 ALGO per call |
| 3+ | 3 | Fully frozen; all payments rejected |

Renewal requires an ed25519 signature over `sha256(last_3_payment_hashes)`.

### Reputation Tiers (ReputationLedger)

| Score | Tier | Limit |
|---|---|---|
| 800–1000 | EXCELLENT | Unlimited (within policy) |
| 600–799 | GOOD | ≤ 5 ALGO/call |
| 400–599 | CAUTION | ≤ 0.5 ALGO/call; intent logging mandatory |
| 200–399 | RESTRICTED | All payments quarantined; human required |
| 0–199 | BLACKLISTED | Rejected by SentinelEscrow |

Score deltas: +5 per clean payment, +10 per passed anomaly challenge,
−50 per confirmed anomaly, −100 per Dead Man Switch breach, −200 per prompt injection.

---

## Layer 4 — Audit

Full agent payment history is reconstructable from **public Algorand data alone**:

1. Query Algorand Indexer with `note_prefix = base64("x402:axiom:")`.
2. Sort transactions by `confirmed-round`.
3. Replay: each note tag (`RELEASE`, `REFUND`, `BLOCK`, `QUARANTINE`, `DRIFT`) mutates the reconstructed system state.

No AXIOM server required. The **chain is the source of truth**.

**Temporal autopsy:** drag the AXIOM frontend's Temporal Scrubber to any historical
Algorand round to reconstruct the exact system state at that moment — reputation
scores, DNA vectors, quarantine queues, policy status.

---

## Behavioral DNA (Layer 3 extension)

Each agent accumulates a **32-dimensional behavioral fingerprint** stored in
`PaymentDNARegistry`:

- Dimensions encode: payment amounts, call frequency, API domain entropy,
  SLA pass ratio, refund ratio, and 26 budget-category distribution buckets.
- **Cosine distance > 0.30** against historical baseline → anomaly trigger → quarantine.
- **Wasserstein distance > 0.40** on category distribution → mission drift alert.
- Fingerprint is stored as `int8[32]` (1 byte/dim) in on-chain box storage.

---

## Reference Implementation

**AXIOM** — https://github.com/[org]/cleverfyre  
Live on Algorand Testnet. Contract IDs in README.

```python
# 5-line integration — zero agent code modification required
from axiom_agpp import AXIOMWrapper

wrapper = AXIOMWrapper(
    org_id="acme-corp",
    agent_role="market-researcher",
    task_goal="Gather Q3 2026 semiconductor supply chain data",
)
response = wrapper.call("https://premium-data.io/endpoint")
```

Any LangChain, CrewAI, or AutoGen agent can adopt AgPP by wrapping its HTTP
client — transparent at the agent level, cryptographically enforced at the
protocol level.

---

## Security Properties

| Property | Mechanism |
|---|---|
| Identity integrity | HMAC-derived address; code hash in IKM |
| Payment causality | Intent hash Merkle-committed before payment |
| Policy enforcement | On-chain; no admin override path |
| Selective disclosure | Merkle proof; reveal one, hide all others |
| Behavioral drift detection | Cosine/Wasserstein distance on 32-dim DNA |
| Replay protection | `timestamp_round` + `replay_protection: true` in policy |
| Burst protection | `burst_max_calls` + `burst_window_sec` enforced by anomaly detector |
| Consensus gating | M-of-N atomic transaction group; all sign or none pay |
| Temporal audit | Full history from on-chain notes; no server dependency |

---

*AgPP is an open specification. This document is the intellectual property of
the AXIOM team and is released for public review and implementation.*
