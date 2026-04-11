# AXIOM: Agentic Payment Protocol 🛡️🤖

![AXIOM Banner](https://via.placeholder.com/1200x300.png?text=AXIOM+Agentic+Payment+Protocol)

AXIOM is a comprehensive on-chain safety and governance layer designed to enhance HTTP 402 client wrappers for autonomous AI agents. While standard x402 implementations provide basic payment routing, they lack critical protections against runaway AI spending, API scams, and inside-threat behavioral drift. 

AXIOM bridges this gap by intercepting x402 responses and executing a rigorous 11-step pipeline built on Algorand Smart Contracts. It enforces strict mathematical spending policies, AI-powered semantic API routing to prevent budget overflow, and multi-dimensional anomaly detection. Every transaction is anchored to the Algorand Testnet with an immutable **Reasoning Receipt**, providing verifiable proof of why an AI spent funds, while SentinelEscrow automatically protects the agent via an SLA Oracle that refunds payments if the destination API fails to deliver. Furthermore, AXIOM features a built-in Red Team CLI simulator, allowing operators to automatically self-test their entire configuration against advanced attack vectors prior to deployment.

---

## 🚀 The 6 Core Smart Contracts

AXIOM utilizes a suite of 6 Algorand Smart Contracts (TEAL) to protect agentic expenditures:

1. **PolicyVault** (App ID: `758648168`): Dead Man's Switch enforcing max daily caps and mandatory human-in-the-loop renewal windows.
2. **IntentRegistry** (App ID: `758648179`): Merkle tree anchor for selective AI intent disclosure.
3. **SentinelEscrow** (App ID: `758648182`): SLA-contingent payment escrow. Funds are automatically refunded if the API is too slow.
4. **PaymentDNARegistry** (App ID: `758648183`): 32-dimensional behavioral fingerprinting for inside-threat drift detection.
5. **ConsensusVault** (App ID: `758648184`): M-of-N Algorand multi-sig requirement for high-value, high-risk AI payments.
6. **ReputationLedger** (App ID: `758648197`): Dynamic, tiered spending limits based on historical agent safety scores.

---

## 🛠️ Setup Instructions

### 1. Requirements
* Python 3.10+
* Node.js 18+
* Algokit
* A `.env` file populated with `DEPLOYER_MNEMONIC` and `GROQ_API_KEY`.

### 2. Backend & Node Services
Open three separate terminals and run the following commands to initialize the entire AXIOM ecosystem:

**Terminal 1 — Backend API**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

**Terminal 2 — SLA Oracle Engine**
```bash
source venv/bin/activate
uvicorn oracle.main:app --port 8001
```

**Terminal 3 — Live AXIOM Dashboard**
```bash
cd frontend/axiom-frontend
npm install
npm run dev
```
Navigate to `http://localhost:5173` to view the Real-Time Event Dashboard.

---

## 🧪 Comprehensive Testing Guide

AXIOM includes 11 completely automated verification commands. Here are the core flows you can run directly from the root directory to see AXIOM in action.

**(1) Full Payment Pipeline + On-Chain Reasoning Receipt**
Simulates an HTTP 402 Payment Required scenario where the AI evaluates the request, passes 11 safety heuristics, deposits into SentinelEscrow, and anchors its reasoning to the Algorand Testnet.
```bash
source venv/bin/activate
python manual_trigger.py
```
> 🔍 Verify on Testnet: Upon success, copy the resulting `tx_id` and view the `x402:axiom:REASONING` JSON note on the [Pera Testnet Explorer](https://testnet.explorer.perawallet.app/).

**(2) Semantic Router Test**
Proves that AXIOM uses an onboard MiniLM embedding model to reject APIs that do not align with the AI's strictly allocated budget map.
```bash
python -c "
from axiom_agpp.semantic import route_api
import yaml

with open('policy.yaml') as f:
    policy = yaml.safe_load(f)

for url in ['https://api.weather.com/forecast', 'https://api.suspicious-hack.com/steal']:
    cat, _ = route_api(url, policy)
    print(f'{url:45s} -> {cat or \"❌ BLOCKED\"}')
"
```

**(3) Behavioral DNA Drift Detection**
Proves AXIOM's `PaymentDNARegistry` can identify sudden shifts in agent behavior mathematically using cosine distance.
```bash
python -c "
from axiom_agpp.dna import BehavioralDNA
dna = BehavioralDNA()
for i in range(5):
    dna.update({'amount':0.1, 'calls_per_hour':5, 'api_domains':['api.test.com'], 'sla_passed':True, 'refunded':False, 'category_counts':{'testing':1}})
baseline = dna.vector.copy()

# Sudden Anomalous Behavior
dna.update({'amount':50.0, 'calls_per_hour':500, 'api_domains':['evil.com'], 'sla_passed':False, 'refunded':True, 'category_counts':{'unknown':1}})
d = dna.drift_score(baseline)
print(f'Drift Score: {d:.4f} -> {\"🚨 QUARANTINE\" if d > 0.3 else \"OK\"}')
"
```

**(4) SLA Auto-Refund Simulator**
Forces a 3-second API response delay. Because the AXIOM SLA threshold is 2 seconds, SentinelEscrow automatically refunds the agent.
```bash
python -c "
import os, logging
from dotenv import load_dotenv
from axiom_agpp.wrapper import AXIOMWrapper

load_dotenv('.env', override=True)
w = AXIOMWrapper(org_id='acme', agent_role='sla-test', task_goal='Test fail', org_secret=b'hackathon')
w.bootstrap()
print('Calling slow API (3s delay)...')
res = w.call('http://localhost:8000/api/v1/mock-sla-fail')
"
```

**(5) Red Team Attack Simulator**
Runs 6 intensive attack vectors (Domain Spoof, Burst Floods, Replay Attacks, etc.) against the AXIOM `policy.yaml` configuration to guarantee system resilience.
```bash
python -c "
from axiom_agpp.red_team import RedTeamEngine
e = RedTeamEngine('policy.yaml')
e.print_report(e.run_all())
"
```

*For an exhaustive list of all 11 test commands, please refer to the included `commands.md` file!*

---

## 📦 Live Deployment & Package

AXIOM is an infrastructure-level Agentic Payment Protocol deployed natively to the **Algorand Testnet**, consumed by developers via the Python SDK: `pip install axiom-agpp`

**Verify the Live Protocol on Testnet:**
You can verify the live, working infrastructure by viewing a recently generated **Reasoning Receipt** directly on the Algorand blockchain explorer:
[https://testnet.explorer.perawallet.app/tx/N72X6SNC46M5Q367GOI6U7NM5JOZHHJNYFZ54ZEUOIBESB2JZWPQ](https://testnet.explorer.perawallet.app/tx/N72X6SNC46M5Q367GOI6U7NM5JOZHHJNYFZ54ZEUOIBESB2JZWPQ)

---
**Built with ❤️ for HACK.ALGO 2026**
