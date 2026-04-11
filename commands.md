# AXIOM Protocol — Demo Commands

> All commands tested and verified. Run in order from the project root.
> **Prerequisite**: `cd /Users/falcon/AXIOM/CleverFyre && source venv/bin/activate`

---

## 0. Start Services (Run Once in Separate Terminals)

These three services power the entire AXIOM ecosystem.

```bash
# Terminal 1 — Backend API + Mock 402 Endpoint
uvicorn backend.main:app --reload --port 8000

# Terminal 2 — SLA Oracle (monitors API response times for auto-refund)
uvicorn oracle.main:app --port 8001

# Terminal 3 — Live Monitoring Dashboard
cd frontend/axiom-frontend && npm run dev
```

Open dashboard at **http://localhost:5173**

---

## 1. Deterministic Agent Identity

**Feature**: AXIOM derives a unique Algorand address from (org_secret + role + SHA-256 of agent code). No wallet files, no key management. Change one byte of code → address changes.

**Why it matters**: Eliminates key management overhead for AI agents. Provides automatic tamper detection — if someone modifies the agent's code, it gets a completely different identity and loses access.

```bash
python -c "
from axiom_agpp.identity import derive_agent_address

pk, addr = derive_agent_address(
    org_secret=b'hackathon-secret-2026',
    org_id='acme',
    agent_role='researcher',
    code_path='manual_trigger.py'
)
print('Agent Address:', addr)

# Prove determinism — same inputs always give same address
pk2, addr2 = derive_agent_address(
    org_secret=b'hackathon-secret-2026',
    org_id='acme',
    agent_role='researcher',
    code_path='manual_trigger.py'
)
print('Deterministic?', addr == addr2, '✅' if addr == addr2 else '❌')

# Different role → completely different address (role isolation)
_, addr3 = derive_agent_address(b'hackathon-secret-2026', 'acme', 'attacker', 'manual_trigger.py')
print('Different role → different address:', addr3[:20] + '...', '✅')
"
```

---

## 2. Full 11-Step Payment Pipeline + On-Chain Reasoning Receipt

**Feature**: Agent encounters HTTP 402 → AXIOM executes all 11 safety checks → pays the API → writes an immutable "Reasoning Receipt" to the Algorand Testnet blockchain.

**Why it matters**: This is the core innovation. Every AI payment is auditable on-chain. You can prove exactly WHY an agent spent money, and verify it on a public blockchain explorer.

```bash
python manual_trigger.py
```

**Watch for these 11 steps in the output:**
- Step 1 — IntentDocument built
- Step 2 — Merkle tree updated
- Step 3 — PolicyVault check passed
- Step 4 — Reputation tier check
- Step 5 — Semantic routing passed
- Step 6 — Anomaly detection passed
- Step 7 — SentinelEscrow deposit
- Step 7b — ✅ REASONING RECEIPT ON-CHAIN (copy this tx_id!)
- Step 8 — IntentRegistry updated
- Step 9 — API response received
- Step 10 — SLA Oracle evaluation
- Step 11 — DNA updated

**Verify on Testnet Explorer**: Copy the `tx_id` from Step 7b and open:
`https://testnet.explorer.perawallet.app/tx/<TX_ID>`

---

## 3. View the Reasoning Receipt (Intent Document)

**Feature**: Every payment generates a structured JSON "Reasoning Receipt" stored locally and Merkle-anchored on-chain.

**Why it matters**: Auditors can prove WHY an agent paid, WHAT it expected, and WHEN it happened — without revealing other payments (selective disclosure via Merkle proofs).

```bash
cat intents/$(ls -t intents/ | head -1) | python -m json.tool
```

---

## 4. PolicyVault — Dead Man's Switch

**Feature**: A smart contract that requires the human operator to periodically renew the agent's spending policy. If they don't renew, the agent is automatically locked out.

**Why it matters**: Prevents runaway AI spending. If the human operator disappears, gets locked out, or the agent goes rogue — the Dead Man's Switch stops all payments automatically.

```bash
python -c "
from axiom_agpp.contracts.client import AXIOMContracts

c = AXIOMContracts()
agent = 'DCD57XNL6DWMFGGRCET3GM65CKRJQFPMT2W73VH7P5LQRIK62VFOV43XOY'
print('PolicyVault App ID:', c.policy_vault_id)
print('Policy Status:', c.policy_vault.get_policy_status(agent))
print()
print('Status codes:')
print('  0 = ACTIVE        (agent can spend)')
print('  1 = WARNING        (renewal needed soon)')
print('  2 = RENEW_NEEDED  (approaching expiry)')
print('  3 = EXPIRED        (agent BLOCKED from spending)')
"
```

---

## 5. Reputation System — Tiered Access Control

**Feature**: Each agent has an on-chain reputation score (0-1000). The score determines their spending tier with hard caps.

**Why it matters**: New/untrusted agents get low spending limits. Proven agents earn higher limits. Malicious agents get blacklisted permanently — enforced on-chain, not by policy files.

```bash
python -c "
from axiom_agpp.reputation_client import ReputationClient, TIER_NAMES

rc = ReputationClient()
agent = 'DCD57XNL6DWMFGGRCET3GM65CKRJQFPMT2W73VH7P5LQRIK62VFOV43XOY'
score = rc.get_score(agent)
tier = rc.get_tier(agent)
max_pay = rc.get_max_payment(agent)

print('Agent:', agent[:16] + '...')
print('Score:', score, '/1000')
print('Tier:', tier, '-', TIER_NAMES.get(tier, '?'))
print('Max Payment:', max_pay, 'ALGO per call')
print()
print('All Tiers:')
print('  0 = BLACKLISTED  (0 ALGO — permanently blocked)')
print('  1 = RESTRICTED   (0 ALGO — probation)')
print('  2 = ACTIVE       (1 ALGO — default for new agents)')
print('  3 = TRUSTED      (10 ALGO — earned through good behavior)')
print('  4 = PREMIUM      (100 ALGO — top-tier agents)')
"
```

---

## 6. Semantic Routing — AI-Powered Budget Enforcement

**Feature**: Uses a MiniLM-L6-v2 language model to classify API URLs into spending categories. Each category has its own budget limit from policy.yaml.

**Why it matters**: Agents can't just pay any arbitrary API. The AI must justify the payment against a predefined budget map. Unknown or unrelated APIs are automatically blocked.

```bash
python -c "
from axiom_agpp.semantic import route_api
import yaml

with open('policy.yaml') as f:
    policy = yaml.safe_load(f)

urls = [
    'https://api.weather.com/forecast/london',
    'https://api.finance.com/stock/AAPL',
    'https://news.api.com/latest/headlines',
    'http://localhost:8000/api/v1/mock-402',
    'https://api.suspicious-site.com/steal-data',
]

print('Semantic Router Results')
print('=' * 70)
for url in urls:
    cat, score = route_api(url, policy)
    budget = policy.get('budget_map', {}).get(cat, 0) if cat else 0
    status = '✅ ALLOWED' if cat else '❌ BLOCKED'
    print(f'  {url[:45]:45s} → {str(cat or \"NONE\"):12s} {status}')
print('=' * 70)
"
```

---

## 7. Anomaly Detection — Burst + IsolationForest

**Feature**: Detects two types of anomalies: (a) rapid-fire "burst" attacks exceeding rate limits, and (b) statistically unusual spending patterns via IsolationForest on 5 real-time features.

**Why it matters**: A compromised agent might try to drain funds with rapid micro-payments. AXIOM's burst detector catches this and quarantines the payment for human review.

```bash
python -c "
from axiom_agpp.anomaly import AnomalyDetector
import time

detector = AnomalyDetector(window=50)

print('=== Normal Behavior (3 calls, spaced out) ===')
for i in range(3):
    detector.timestamps.append(time.time())
    time.sleep(0.5)
    burst = detector.burst_check(window_sec=30, max_calls=5)
    print(f'  Call {i+1}: burst={burst}')

print()
print('=== Burst Attack (rapid-fire calls) ===')
for i in range(6):
    detector.timestamps.append(time.time())
    burst = detector.burst_check(window_sec=30, max_calls=5)
    if burst:
        print(f'  Call {i+4}: 🚨 BURST DETECTED — payment quarantined!')
        break
    else:
        print(f'  Call {i+4}: burst={burst}')
"
```

---

## 8. SLA Oracle — Automatic Refund on Service Failure

**Feature**: After the agent pays, AXIOM monitors the API's response time and status. If the API is too slow or returns an error, the SLA Oracle triggers an automatic on-chain refund.

**Why it matters**: Agents shouldn't pay for broken services. AXIOM's oracle enforces SLA guarantees — if the API breaches the 2-second threshold, the agent gets its money back automatically.

```bash
python -c "
import os, logging
from dotenv import load_dotenv
from axiom_agpp.wrapper import AXIOMWrapper

logging.basicConfig(level=logging.INFO)
load_dotenv('.env', override=True)

wrapper = AXIOMWrapper(
    org_id='acme',
    agent_role='sla-tester',
    task_goal='Test SLA failure and automatic refund',
    org_secret=b'hackathon-secret-2026'
)
wrapper.bootstrap()

# This endpoint deliberately takes 3 seconds (SLA limit is 2 seconds)
print('Calling slow API (3-second delay)...')
res = wrapper.call('http://localhost:8000/api/v1/mock-sla-fail')
print('Response:', res.status_code)
"
```

**Look for in output:**
```
Step 10 — SLA Oracle: passed=False, action=refunded, reason=SLA FAILED — time=3001ms (max 2000ms)
```

---

## 9. Behavioral DNA — 32-Dimensional Fingerprint

**Feature**: AXIOM builds a 32-dimensional behavioral DNA vector for each agent — capturing amount patterns, call rates, API diversity, SLA pass ratios, and category distributions.

**Why it matters**: Detects insider compromise that individual checks would miss. If an agent suddenly starts paying large amounts to unknown APIs, the drift score spikes and triggers quarantine.

```bash
python -c "
import numpy as np
from axiom_agpp.dna import BehavioralDNA

dna = BehavioralDNA()

# Establish a normal baseline (5 small, legitimate payments)
for i in range(5):
    dna.update({
        'amount': 0.1,
        'calls_per_hour': 5,
        'api_domains': ['api.weather.com'],
        'sla_passed': True,
        'refunded': False,
        'category_counts': {'weather': 1}
    })

baseline = dna.vector.copy()
print('Baseline DNA (first 6 dims):', [round(x, 3) for x in dna.vector[:6]])
print('Baseline norm:', round(float(np.linalg.norm(dna.vector)), 4))

# Sudden anomalous payment — large amount, unknown domain, SLA failed
dna.update({
    'amount': 50.0,
    'calls_per_hour': 500,
    'api_domains': ['evil-drain-funds.com'],
    'sla_passed': False,
    'refunded': True,
    'category_counts': {'unknown': 1}
})

drift = dna.drift_score(baseline)
print()
print('After anomalous payment:')
print('DNA (first 6 dims):', [round(x, 3) for x in dna.vector[:6]])
print('Drift from baseline:', round(drift, 4))
print('Threshold: 0.30')
print('Result:', '🚨 QUARANTINE — drift exceeds threshold!' if drift > 0.3 else '✅ Normal')
"
```

---

## 10. Red Team Attack Simulator

**Feature**: Built-in attack simulator that tests 6 attack vectors against your policy configuration and reports which are blocked.

**Why it matters**: We don't just claim security — we prove it. Run this before deploying to find vulnerabilities in your policy.

```bash
python -c "
from axiom_agpp.red_team import RedTeamEngine
e = RedTeamEngine('policy.yaml')
e.print_report(e.run_all())
"
```

**Expected output:**
```
ATK-001: Gradual Escalation                 ✓ BLOCKED
ATK-002: Domain Spoof                       ✓ BLOCKED
ATK-003: Burst Attack (100 micro-payments)  ✓ BLOCKED
ATK-004: Semantic Confusion                 ✓ BLOCKED
ATK-005: Dead Man Switch Timing Attack      ✓ BLOCKED
ATK-006: Intent Replay Attack               ✓ BLOCKED

6/6 attacks blocked.
```

---

## 11. Live Dashboard — Real-Time WebSocket Events

**Feature**: All protocol events (payments, blocks, quarantines, drift alerts) stream in real-time to a monitoring dashboard via WebSocket.

**Why it matters**: Organizations need a single screen to monitor all their agents' spending activity. Every event is categorized and timestamped for instant visibility.

Open the dashboard at **http://localhost:5173**, then inject events:

```bash
# 11a. Successful payment event
curl -s -X POST http://localhost:8000/api/v1/inject-event \
  -H "Content-Type: application/json" \
  -d '{"type":"PAYMENT","sender":"DCD57XNL6DWMFGGRCET3GM65CKRJQFPMT2W73VH7P5LQRIK62VFOV43XOY","amount":500000,"note":"x402:axiom:RELEASE","round":62302477}'

# 11b. Blocked payment (anomaly detected)
curl -s -X POST http://localhost:8000/api/v1/inject-event \
  -H "Content-Type: application/json" \
  -d '{"type":"BLOCKED","sender":"ATTACKER_ADDRESS","amount":5000000,"note":"x402:axiom:ANOMALY","round":62302480}'

# 11c. Quarantined payment (burst detected)
curl -s -X POST http://localhost:8000/api/v1/inject-event \
  -H "Content-Type: application/json" \
  -d '{"type":"QUARANTINE","sender":"DCD57XNL6DWMFGGRCET3GM65CKRJQFPMT2W73VH7P5LQRIK62VFOV43XOY","amount":1000000,"note":"x402:axiom:QUARANTINE","round":62302485}'

# 11d. DNA drift warning
curl -s -X POST http://localhost:8000/api/v1/inject-event \
  -H "Content-Type: application/json" \
  -d '{"type":"DRIFT","sender":"DCD57XNL6DWMFGGRCET3GM65CKRJQFPMT2W73VH7P5LQRIK62VFOV43XOY","amount":0,"note":"x402:axiom:DNA_DRIFT:0.45","round":62302490}'

# 11e. Policy expired alert
curl -s -X POST http://localhost:8000/api/v1/inject-event \
  -H "Content-Type: application/json" \
  -d '{"type":"EXPIRED","sender":"DCD57XNL6DWMFGGRCET3GM65CKRJQFPMT2W73VH7P5LQRIK62VFOV43XOY","amount":0,"note":"x402:axiom:POLICY_EXPIRED","round":62302495}'
```

---

## Blockchain Verification Links

| What | Link |
|------|------|
| Agent Account | https://testnet.explorer.perawallet.app/address/DCD57XNL6DWMFGGRCET3GM65CKRJQFPMT2W73VH7P5LQRIK62VFOV43XOY |
| Deployer Account | https://testnet.explorer.perawallet.app/address/2MANOJ5CURDMVSSHKAEQZVBJ37VNTUBNEZNM7CAO6IKL6REYXR3N673BYU |
| Sample Reasoning Receipt | https://testnet.explorer.perawallet.app/tx/3TPSBSRVLV4XOBTKGPWQNQOI3U264UJHG2Y2SC3FXRVPGPVC6QLQ |
