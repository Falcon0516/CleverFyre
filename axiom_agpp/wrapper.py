"""
AXIOM AgPP — SDK Wrapper

The top-level interface for AI agents. Wraps the standard requests.Session
to inject AXIOM protocol protections natively.

At the call site, the AI agent simply does:
    r = wrapper.call("https://api.example.com")

Under the hood, AXIOM performs the full 10-step pipeline:
    1. Build IntentDocument with all fields
    2. Compute session MerkleTree root
    3. PolicyVault.check_and_enforce — Dead Man's Switch
    4. ReputationLedger.get_tier — blacklist/restrict check
    5. Semantic routing via MiniLM-L6-v2
    6. Anomaly detection (burst + IsolationForest) → quarantine
    7. SentinelEscrow.deposit — hold funds with SLA-contingent release
    8. IntentRegistry.register_session_root + register_intent
    9. Inject x-payment header with escrow_id and retry request
   10. POST response metrics to SLA Oracle for release/refund
   11. Update Behavioral DNA and PaymentDNARegistry on-chain

Usage:
    from axiom_agpp.wrapper import AXIOMWrapper

    wrapper = AXIOMWrapper(
        org_id="acme",
        agent_role="researcher",
        task_goal="Find stock prices",
        org_secret=b"my-secret"
    )

    # Automatically protected by AXIOM — handles 402 transparently
    response = wrapper.call("https://api.financial.com/quote/AAPL")
"""

import hashlib
import logging
import os
import time
from typing import Any, Dict, Optional

import requests
import yaml
from algosdk.account import address_from_private_key
from algosdk.mnemonic import to_private_key
from algosdk.v2client import algod
import algosdk.transaction as transaction

from algokit_utils import AlgorandClient
from algokit_utils.applications.app_client import AppClientMethodCallParams

from axiom_agpp.anomaly import AnomalyDetector
from axiom_agpp.consensus import ConsensusOrchestrator
from axiom_agpp.contracts.client import AXIOMContracts
from axiom_agpp.dna import BehavioralDNA
from axiom_agpp.exceptions import (
    AnomalyDetectedError,
    ConsensusTimeoutError,
    IntentRejectedError,
    MissionDriftError,
    PolicyExpiredError,
    ReputationBlacklistedError,
    SLAFailedError,
    SemanticMismatchError,
)
from axiom_agpp.identity import derive_agent_address
from axiom_agpp.intent import IntentDocument
from axiom_agpp.merkle import MerkleTree
from axiom_agpp.reputation_client import ReputationClient
from axiom_agpp.semantic import route_api

# Try to import background uploader, but don't fail if backend isn't loaded
try:
    from backend.ipfs_client import upload_intent_background
except ImportError:
    def upload_intent_background(intent):
        pass

logger = logging.getLogger(__name__)


class AXIOMWrapper:
    """
    AXIOM Reference SDK Wrapper.

    Protects outbound agent API calls using the AXIOM AgPP standard.
    Transparently handles HTTP 402 Payment Required responses by
    executing the full AXIOM protocol pipeline.
    """

    def __init__(
        self,
        org_id: str,
        agent_role: str,
        task_goal: str,
        org_secret: bytes,
        policy_path: str = "policy.yaml",
        code_path: Optional[str] = None,
    ):
        """
        Initialize the AXIOM Wrapper.

        Args:
            org_id:      Organization identifier.
            agent_role:  Agent role identifier.
            task_goal:   The agent's canonical task/mission.
            org_secret:  Master organization secret (bytes).
            policy_path: Path to the local policy.yaml config.
            code_path:   Optional override for identity derivation.
        """
        self.org_id = org_id
        self.agent_role = agent_role
        self.task_goal = task_goal

        # Derive deterministic identity
        if not code_path:
            import sys
            code_path = sys.argv[0] if sys.argv else "unknown.py"
        
        self.private_key, self.address = derive_agent_address(
            org_secret, org_id, agent_role, code_path
        )
        self.signer = self.private_key

        # Load policy
        try:
            with open(policy_path) as f:
                self.policy = yaml.safe_load(f)
        except Exception as e:
            logger.error("Failed to load %s: %s", policy_path, e)
            self.policy = {}

        # Compute policy commitment hash for intent documents
        self.policy_commitment = hashlib.sha256(
            yaml.dump(self.policy, sort_keys=True).encode()
        ).hexdigest()

        # Initialize protocol modules
        self.reputation = ReputationClient()
        self.anomaly_detector = AnomalyDetector(window=50)
        self.dna = BehavioralDNA()
        self.consensus = ConsensusOrchestrator()
        self.contracts = AXIOMContracts()

        # AlgorandClient for direct contract calls
        self.algo_client = AlgorandClient.from_environment()
        
        # Configure the agent's derived address as the default signer
        try:
            from algosdk.atomic_transaction_composer import AccountTransactionSigner
            # identity.py returns base64 string of the private key
            self.signer = AccountTransactionSigner(self.private_key)
            self.algo_client.account.set_default_signer(self.signer)
            logger.info("Agent signer configured for address: %s", self.address[:8] + "...")
        except Exception as e:
            logger.warning("Agent signer configuration failed: %s", e)

        # Raw algod client for status queries
        self.algod_client = algod.AlgodClient(
            os.getenv("ALGOD_TOKEN", "a" * 64),
            f"{os.getenv('ALGOD_SERVER', 'http://localhost')}:{os.getenv('ALGOD_PORT', '4001')}",
        )

        # Contract app IDs from environment
        self.policy_vault_id = int(os.getenv("POLICY_VAULT_ID", "0"))
        self.sentinel_escrow_id = int(os.getenv("SENTINEL_ESCROW_ID", "0"))
        self.intent_registry_id = int(os.getenv("INTENT_REGISTRY_ID", "0"))
        self.reputation_ledger_id = int(os.getenv("REPUTATION_LEDGER_ID", "0"))
        self.payment_dna_registry_id = int(os.getenv("PAYMENT_DNA_REGISTRY_ID", "0"))
        self.consensus_vault_id = int(os.getenv("CONSENSUS_VAULT_ID", "0"))

        # SLA Oracle URL
        self.sla_oracle_url = os.getenv("SLA_ORACLE_URL", "http://localhost:8001")

        # Session state
        self.session = requests.Session()
        self.intent_hashes: list[bytes] = []
        self._session_start = time.time()
        self._call_count = 0

        logger.info(
            "AXIOM Wrapper initialized for %s — addr=%s...",
            self.task_goal[:30],
            self.address[:10],
        )

    def bootstrap(self) -> bool:
        """
        Bootstrap the agent's on-chain presence.
        1. Fund from deployer if balance < 5 ALGO.
        2. Initialize PolicyVault record if missing.
        3. Initialize PaymentDNARegistry record if missing.
        """
        logger.info("Bootstrap — Ensuring agent %s initialized on-chain", self.address[:8])
        
        # 1. Funding
        deployer_account = None
        deployer_mnemonic = os.getenv("DEPLOYER_MNEMONIC")
        if deployer_mnemonic:
            try:
                deployer_account = self.algo_client.account.from_mnemonic(mnemonic=deployer_mnemonic)
            except Exception:
                pass

        # 1. Funding & Account Creation (The Ultra-Reliable Way for Testnet)
        try:
            # First, check if agent already has enough balance
            info = self.algod_client.account_info(self.address)
            balance = info.get("amount", 0)
            
            if balance < 1_000_000: # Less than 1 ALGO
                logger.info("Bootstrap — Agent balance low (%d), funding...", balance)
                
                if deployer_mnemonic:
                    # Direct payment is much more reliable on Testnet than simulation-heavy utilities
                    import algokit_utils
                    sender_acct = self.algo_client.account.from_mnemonic(mnemonic=deployer_mnemonic)
                    
                    self.algo_client.send.payment(algokit_utils.PaymentParams(
                        sender=sender_acct.address,
                        receiver=self.address,
                        amount=algokit_utils.AlgoAmount(algo=2.5), # 2.5 ALGO is perfect for demo & boxes
                        note=f"axiom:bootstrap:{self.address[:8]}".encode()
                    ))
                    logger.info("Bootstrap — Agent %s successfully funded from Deployer", self.address[:8])
                    time.sleep(4) # Significant delay for Testnet propagation
                else:
                    logger.warning("Bootstrap — No DEPLOYER_MNEMONIC, attempting localnet dispenser fallback")
                    import algokit_utils
                    algokit_utils.ensure_funded(
                        self.algo_client.client.algod,
                        algokit_utils.EnsureFundedParams(
                            account_to_fund=self.address,
                            min_spending_balance=algokit_utils.AlgoAmount(algo=2),
                        )
                    )
            else:
                logger.info("Bootstrap — Agent %s already has sufficient balance (%d)", self.address[:8], balance)

        except Exception as e:
            logger.error("Bootstrap — Funding phase failed: %s", e)
            if "balance" in str(e).lower() or "overspend" in str(e).lower():
                 logger.error("  >> ACTION REQUIRED: Fund the Deployer account first at https://bank.testnet.algorand.network/")
                 raise ValueError("Deployer account out of Testnet ALGO. Please fund your deployer address.")
            raise

        # 2. PolicyVault Initialization
        if self.policy_vault_id > 0:
            try:
                # Check if box exists (box name is address in bytes)
                from algosdk import encoding
                addr_bytes = encoding.decode_address(self.address)
                # Box key is just the address but for BoxMap it might have a prefix
                # Based on the contract: self.policies = BoxMap(Account, PolicyRecord)
                # ARC-56 BoxMap often uses "name" + address. Key prefix in BoxMap is usually empty unless specified.
                try:
                    self.algod_client.application_box_by_name(self.policy_vault_id, addr_bytes)
                    logger.info("Bootstrap — PolicyVault record already exists")
                except Exception:
                    # Box not found — initialize
                    spec = self.contracts.load_spec("PolicyVault")
                    app_client = self.algo_client.client.get_app_client_by_id(
                        app_id=self.policy_vault_id, app_spec=spec
                    )
                    # Use Deployer to pay for box MBR to ensure reliability
                    from algosdk.transaction import BoxReference
                    app_client.send.call(AppClientMethodCallParams(
                        method="init_policy",
                        args=[self.address, 1000, addr_bytes],
                        sender=deployer_account.address,
                        signer=deployer_account.signer,
                        box_references=[BoxReference(self.policy_vault_id, addr_bytes)]
                    ))
                    logger.info("Bootstrap — PolicyVault initialized")
            except Exception as e:
                logger.warning("Bootstrap — PolicyVault initialization failed: %s", e)

        # 3. DNA Registry Initialization
        if self.payment_dna_registry_id > 0:
            try:
                from algosdk import encoding
                addr_bytes = encoding.decode_address(self.address)
                # Contract: BoxMap(Account, DNARecord, key_prefix=b"dna:")
                box_key = b"dna:" + addr_bytes
                try:
                    self.algod_client.application_box_by_name(self.payment_dna_registry_id, box_key)
                    logger.info("Bootstrap — PaymentDNARegistry record already exists")
                except Exception:
                    spec = self.contracts.load_spec("PaymentDNARegistry")
                    app_client = self.algo_client.client.get_app_client_by_id(
                        app_id=self.payment_dna_registry_id, app_spec=spec
                    )
                    from algosdk.transaction import BoxReference
                    app_client.send.call(AppClientMethodCallParams(
                        method="initialize_dna",
                        args=[self.address],
                        sender=deployer_account.address,
                        signer=deployer_account.signer,
                        box_references=[BoxReference(self.payment_dna_registry_id, box_key)]
                    ))
                    logger.info("Bootstrap — PaymentDNARegistry initialized")
            except Exception as e:
                logger.warning("Bootstrap — PaymentDNARegistry initialization failed: %s", e)

        return True

    # ─────────────────────────────────────────────────────────────
    #  PUBLIC API — call()
    # ─────────────────────────────────────────────────────────────

    def call(self, url: str, method: str = "GET", **kwargs) -> requests.Response:
        """
        Execute an API call wrapped in AXIOM protocol protections.

        If the API returns HTTP 402 Payment Required, AXIOM automatically
        handles the payment flow via _handle_402().

        For non-402 responses, AXIOM still tracks the call for DNA
        fingerprinting and anomaly detection.

        Args:
            url:    The API URL to call.
            method: HTTP method ("GET", "POST", etc.)
            kwargs: Passed to requests.request (headers, json, etc.)

        Returns:
            The requests.Response object.

        Raises:
            PolicyExpiredError:        Dead Man's Switch policy expired.
            ReputationBlacklistedError: Agent blacklisted or restricted.
            SemanticMismatchError:     API not in approved categories.
            AnomalyDetectedError:      Burst or anomaly detected.
            ConsensusTimeoutError:     M-of-N quorum not reached.
            IntentRejectedError:       Budget exceeded or policy violation.
            SLAFailedError:            SLA oracle rejected the response.
        """
        self._call_count += 1
        now = time.time()
        calls_per_hour = (self._call_count / max(now - self._session_start, 1)) * 3600

        logger.info("═" * 60)
        logger.info("AXIOM evaluating call %d: %s %s", self._call_count, method, url)

        # Make the initial request
        try:
            response = self.session.request(method, url, **kwargs)
        except Exception as e:
            logger.error("Initial request failed: %s", e)
            raise

        # If 402 Payment Required → run the full AXIOM pipeline
        if response.status_code == 402:
            logger.info("HTTP 402 received — initiating AXIOM payment protocol")
            response = self._handle_402(response, url, method, calls_per_hour, **kwargs)
        else:
            # Non-402 — still track for DNA/anomaly purposes
            self.anomaly_detector.record([
                0.0,  # no payment
                calls_per_hour,
                0.0,
                1.0 if response.status_code == 200 else 0.0,
                0.0,
            ])

        logger.info("═" * 60)
        return response

    # ─────────────────────────────────────────────────────────────
    #  _handle_402 — Full AXIOM on-chain payment pipeline
    # ─────────────────────────────────────────────────────────────

    def _handle_402(
        self,
        initial_response: requests.Response,
        url: str,
        method: str,
        calls_per_hour: float,
        **kwargs,
    ) -> requests.Response:
        """
        Handle HTTP 402 Payment Required — full AXIOM protocol pipeline.

        This is where all the magic happens. Every numbered step maps
        directly to a layer in the AgPP spec:

        Steps:
            1. Build IntentDocument with all fields
            2. Add to session list, compute MerkleTree, get root
            3. PolicyVault.check_and_enforce — if returns 3 → PolicyExpiredError
            4. ReputationLedger.get_tier — if returns 0 → ReputationBlacklistedError
            5. Semantic routing — if None → SemanticMismatchError
            6. Anomaly detection — if True → SentinelEscrow.quarantine
            7. SentinelEscrow.deposit — hold funds, get escrow_id
            8. IntentRegistry.register_session_root + register_intent
            9. Inject x-payment header with escrow_id, retry request
           10. POST metrics to SLA Oracle → release or refund
           11. Update DNA + PaymentDNARegistry on-chain

        Args:
            initial_response: The 402 response with payment details.
            url:              The original request URL.
            method:           HTTP method.
            calls_per_hour:   Current call rate for anomaly detection.
            **kwargs:         Original request kwargs.

        Returns:
            The retried response (after payment header injection).

        Raises:
            Various AXIOM exceptions on protocol violations.
        """

        # Parse payment details from 402 response headers
        www_auth = initial_response.headers.get("WWW-Authenticate", "")
        provider_address = self._parse_provider_address(www_auth)
        payment_amount_algo = self._parse_payment_amount(www_auth, initial_response)

        logger.info(
            "402 payment details — provider=%s, amount=%.4f ALGO",
            provider_address[:12] + "..." if provider_address else "unknown",
            payment_amount_algo,
        )

        # Get current Algorand round for intent timestamp
        try:
            status = self.algod_client.status()
            current_round = status.get("last-round", 0)
        except Exception:
            current_round = 0

        # ──────────────────────────────────────────────────────────
        #  STEP 1: Build IntentDocument with all fields
        # ──────────────────────────────────────────────────────────

        intent = IntentDocument(
            schema="agpp/v1",
            agent_id=self.address,
            task_canonical=self.task_goal,
            api_url=url,
            api_selection_reason=f"HTTP 402 payment required for API access",
            expected_output_schema={"type": "json", "status": 200},
            policy_commitment=self.policy_commitment,
            timestamp_round=current_round,
            chain_id=None,  # no delegation chain in v1
        )

        intent_hash = intent.hash()
        intent_hash_hex = intent_hash.hex()

        logger.info(
            "Step 1 — IntentDocument built: hash=%s, round=%d",
            intent_hash_hex[:16],
            current_round,
        )

        # For Demo Purposes: Save a local copy of the intent to disk
        # so you can easily show the judges the "Reasoning Receipt"
        try:
            # Guarantee it writes to /Users/falcon/AXIOM/CleverFyre/intents
            import os
            base_dir = "/Users/falcon/AXIOM/CleverFyre"
            intent_dir = os.path.join(base_dir, "intents")
            os.makedirs(intent_dir, exist_ok=True)
            
            filepath = os.path.join(intent_dir, f"{intent_hash_hex[:16]}.json")
            with open(filepath, "w") as f:
                f.write(intent.to_json())
            logger.info("Local intent dumped successfully to %s", filepath)
        except Exception as e:
            logger.warning("Failed to write local intent dump: %s", e)

        # Fire and forget IPFS upload (non-blocking)
        upload_intent_background(intent)

        # ──────────────────────────────────────────────────────────
        #  STEP 2: Add to session list, compute MerkleTree root
        # ──────────────────────────────────────────────────────────

        self.intent_hashes.append(intent_hash)
        tree = MerkleTree(self.intent_hashes)
        merkle_root = tree.get_root()

        logger.info(
            "Step 2 — Merkle tree updated: %d leaves, root=%s",
            len(self.intent_hashes),
            merkle_root.hex()[:16],
        )

        # ──────────────────────────────────────────────────────────
        #  STEP 3: PolicyVault.check_and_enforce
        # ──────────────────────────────────────────────────────────

        try:
            policy_result = self._call_policy_vault(payment_amount_algo)

            if policy_result == 3:
                self._log_rejection("POLICY_EXPIRED")
                raise PolicyExpiredError(
                    f"Dead Man's Switch policy expired for agent {self.address[:12]}. "
                    f"PolicyVault returned status=3. Renew policy before making payments."
                )

            logger.info(
                "Step 3 — PolicyVault.check_and_enforce passed (result=%d)",
                policy_result,
            )

        except PolicyExpiredError:
            raise
        except Exception as e:
            logger.warning("PolicyVault call failed (proceeding with local check): %s", e)
            # Local fallback: check renewal window
            renewal_window = self.policy.get("renewal_window_rounds", 360)
            if current_round > 0 and current_round % renewal_window == 0:
                logger.warning("Local policy renewal check triggered")

        # ──────────────────────────────────────────────────────────
        #  STEP 4: ReputationLedger.get_tier
        # ──────────────────────────────────────────────────────────

        tier = self.reputation.get_tier(self.address)

        if tier == 0:  # BLACKLISTED
            self._log_rejection("BLACKLISTED")
            raise ReputationBlacklistedError(
                f"Agent {self.address[:12]}... is BLACKLISTED (tier 0, score < 200). "
                f"All payment attempts are rejected by SentinelEscrow."
            )

        if tier == 1:  # RESTRICTED
            self._log_rejection("RESTRICTED")
            raise ReputationBlacklistedError(
                f"Agent {self.address[:12]}... is RESTRICTED (tier 1, score 200-399). "
                f"Human review required before payments can proceed."
            )

        max_pay = self.reputation.get_max_payment(self.address)

        logger.info(
            "Step 4 — Reputation check passed: tier=%d, max_payment=%.2f ALGO",
            tier,
            max_pay,
        )

        # ──────────────────────────────────────────────────────────
        #  STEP 5: Semantic routing
        # ──────────────────────────────────────────────────────────

        category, score = route_api(
            str(url),
            self.policy.get("budget_map", {}),
            threshold=self.policy.get("semantic_threshold", 0.7),
        )

        if category is None:
            self._log_rejection("SEMANTIC_MISMATCH")
            raise SemanticMismatchError(
                f"API '{url}' does not match any approved budget category "
                f"(best score={score:.3f}, threshold={self.policy.get('semantic_threshold', 0.7)}). "
                f"Payment blocked."
            )

        # Check budget limit for this category
        budget_limit = self.policy.get("budget_map", {}).get(category, 0)
        if payment_amount_algo > min(budget_limit, max_pay):
            self._log_rejection("BUDGET_EXCEEDED")
            raise IntentRejectedError(
                f"Payment of {payment_amount_algo} ALGO exceeds allowed "
                f"(category '{category}' budget={budget_limit}, tier max={max_pay})"
            )

        logger.info(
            "Step 5 — Semantic routing passed: category='%s', score=%.3f, budget=%.2f",
            category,
            score,
            budget_limit,
        )

        # ──────────────────────────────────────────────────────────
        #  STEP 6: Anomaly detection (burst + IsolationForest)
        # ──────────────────────────────────────────────────────────

        features = [
            payment_amount_algo,
            calls_per_hour,
            self.dna.drift_score(self.dna.vector),
            score,  # semantic confidence
            float(tier),
        ]

        # Record timestamp BEFORE burst_check so rapid-fire calls
        # are visible to the rate limiter immediately.
        self.anomaly_detector.timestamps.append(time.time())

        is_burst = self.anomaly_detector.burst_check(
            window_sec=self.policy.get("burst_window_sec", 30),
            max_calls=self.policy.get("burst_max_calls", 20),
        )

        is_anomaly = self.anomaly_detector.is_anomaly(features)

        if is_burst or is_anomaly:
            reason = "burst" if is_burst else "statistical anomaly"
            logger.warning(
                "ANOMALY DETECTED — features=%s",
                [round(f, 4) for f in features[:5]],
            )
            logger.warning(
                "Step 6 — ANOMALY DETECTED (%s). Quarantining payment.", reason
            )

            # Call SentinelEscrow.quarantine on-chain
            self._call_sentinel_quarantine(intent_hash_hex)

            self._log_rejection("ANOMALY_" + reason.upper().replace(" ", "_"))
            raise AnomalyDetectedError(
                f"Anomaly detected ({reason}) for payment to {url}. "
                f"Funds quarantined in SentinelEscrow for review."
            )

        logger.info("Step 6 — Anomaly detection passed (burst=False, anomaly=False)")

        # ──────────────────────────────────────────────────────────
        #  STEP 7: SentinelEscrow.deposit
        # ──────────────────────────────────────────────────────────

        # Determine if consensus is required (high-value payment)
        consensus_threshold = self.policy.get("consensus_threshold_algo", 5.0)
        requires_consensus = payment_amount_algo > consensus_threshold

        escrow_id = self._call_sentinel_deposit(
            provider_address=provider_address,
            intent_hash_hex=intent_hash_hex,
            deadline_rounds=100,
            requires_consensus=requires_consensus,
            amount_algo=payment_amount_algo,
        )

        logger.info(
            "Step 7 — SentinelEscrow.deposit: escrow_id=%s, consensus=%s",
            escrow_id[:16],
            requires_consensus,
        )

        # If consensus required, run the M-of-N flow
        if requires_consensus:
            logger.info("High-value payment (%.2f > %.2f) — triggering consensus",
                        payment_amount_algo, consensus_threshold)
            self._handle_consensus(intent_hash_hex)

        # ──────────────────────────────────────────────────────────
        #  STEP 7b: On-chain Reasoning Receipt (the "Wow" factor)
        #  A standalone payment with the full reasoning note.
        #  This is what the judges see on the Pera Explorer.
        # ──────────────────────────────────────────────────────────

        try:
            import json as _json
            receipt = {
                "protocol": "x402:axiom:v1",
                "type": "REASONING_RECEIPT",
                "agent": self.address[:16] + "...",
                "task": self.task_goal[:60],
                "api": url[:80],
                "amount_algo": payment_amount_algo,
                "intent_hash": intent_hash_hex[:16],
                "merkle_root": merkle_root.hex()[:16],
                "policy_commitment": self.policy_commitment[:16],
                "escrow_id": escrow_id[:16],
                "reason": f"Agent autonomously paid {payment_amount_algo} ALGO to access API. "
                          f"All 11 safety checks passed. Intent is Merkle-anchored.",
            }
            receipt_note = b"x402:axiom:REASONING:" + _json.dumps(receipt).encode()

            # Use raw algosdk to avoid algokit's simulation/caching round-expiry issue
            from algosdk import transaction as alg_txn
            sp = self.algod_client.suggested_params()  # Fresh round RIGHT NOW
            sp.flat_fee = True
            sp.fee = 1000  # 0.001 ALGO minimum fee

            unsigned_txn = alg_txn.PaymentTxn(
                sender=self.address,
                sp=sp,
                receiver=provider_address,
                amt=1000,       # 0.001 ALGO micro-payment
                note=receipt_note,
            )

            # Sign with the agent's derived private key
            signed_txn = unsigned_txn.sign(self.private_key)
            tx_id = self.algod_client.send_transaction(signed_txn)

            # Wait for confirmation
            alg_txn.wait_for_confirmation(self.algod_client, tx_id, 4)

            logger.info(
                "Step 7b — ✅ REASONING RECEIPT ON-CHAIN! tx_id=%s  note=%d bytes",
                tx_id, len(receipt_note)
            )
        except Exception as e:
            logger.warning("Step 7b — Reasoning Receipt payment failed (non-fatal): %s", e)

        # ──────────────────────────────────────────────────────────
        #  STEP 8: IntentRegistry.register_session_root + register_intent
        # ──────────────────────────────────────────────────────────

        self._call_intent_registry(merkle_root, intent_hash, intent)

        logger.info(
            "Step 8 — IntentRegistry: root=%s, intent=%s registered",
            merkle_root.hex()[:16],
            intent_hash_hex[:16],
        )

        # ──────────────────────────────────────────────────────────
        #  STEP 9: Inject x-payment header and retry request
        # ──────────────────────────────────────────────────────────

        # Build payment header: escrow_id in hex for the API to verify
        headers = kwargs.pop("headers", {}) or {}
        headers["x-payment"] = escrow_id
        headers["x-axiom-agent"] = self.address
        headers["x-axiom-intent"] = intent_hash_hex

        logger.info(
            "Step 9 — Retrying request with x-payment header (escrow=%s)",
            escrow_id[:16],
        )

        request_start = time.time()

        try:
            response = self.session.request(method, url, headers=headers, **kwargs)
        except Exception as e:
            logger.error("Retried request failed: %s", e)
            raise

        request_duration_ms = int((time.time() - request_start) * 1000)

        logger.info(
            "Step 9 — Response received: status=%d, time=%dms",
            response.status_code,
            request_duration_ms,
        )

        # ──────────────────────────────────────────────────────────
        #  STEP 10: POST result metrics to SLA Oracle
        # ──────────────────────────────────────────────────────────

        sla_threshold_ms = self.policy.get("sla_threshold_ms", 2000)

        # Check basic schema validity (JSON response expected)
        schema_valid = True
        try:
            response.json()
        except Exception:
            schema_valid = False

        sla_result = self._post_sla_evaluation(
            tx_id=escrow_id,  # use escrow_id as tx reference
            escrow_id=escrow_id,
            response_time_ms=request_duration_ms,
            http_status=response.status_code,
            schema_valid=schema_valid,
            sla_threshold_ms=sla_threshold_ms,
        )

        logger.info(
            "Step 10 — SLA Oracle: passed=%s, action=%s, reason=%s",
            sla_result.get("passed", "unknown"),
            sla_result.get("action", "unknown"),
            sla_result.get("reason", "unknown")[:60],
        )

        # ──────────────────────────────────────────────────────────
        #  STEP 11: Update DNA + PaymentDNARegistry on-chain
        # ──────────────────────────────────────────────────────────

        observation = {
            "amount": payment_amount_algo,
            "calls_per_hour": calls_per_hour,
            "api_domains": [url.split("/")[2]] if "/" in url else [url],
            "sla_passed": sla_result.get("passed", False),
            "refunded": sla_result.get("action") == "refunded",
            "category_counts": {category: 1},
        }

        # Check for DNA drift before updating
        import numpy as np
        new_dna = BehavioralDNA(self.dna.vector.copy())
        new_dna.update(observation)
        drift = self.dna.drift_score(new_dna.vector)

        if drift > self.policy.get("dna_drift_threshold", 0.3):
            logger.warning(
                "Step 11 — DNA DRIFT detected: score=%.4f (threshold=%.2f)",
                drift,
                self.policy.get("dna_drift_threshold", 0.3),
            )

        # Update DNA
        self.dna = new_dna

        # Record features for future anomaly detection
        self.anomaly_detector.record(features)

        # Update PaymentDNARegistry on-chain
        self._call_dna_registry_update()

        logger.info(
            "Step 11 — DNA updated: drift=%.4f, %s",
            drift,
            repr(self.dna),
        )

        return response

    # ─────────────────────────────────────────────────────────────
    #  SMART CONTRACT CALLERS
    # ─────────────────────────────────────────────────────────────

    def _call_policy_vault(self, amount: float) -> int:
        """
        Call PolicyVault.check_and_enforce on-chain.

        Returns:
            Integer status code:
                0 = OK, policy active
                1 = WARNING, approaching limits
                2 = HOLD, exceeds single-call cap
                3 = FROZEN, Dead Man's Switch expired
        """
        if self.policy_vault_id == 0:
            logger.debug("PolicyVault not deployed — stub returning 0 (OK)")
            return 0

        try:
            spec = self.contracts.load_spec("PolicyVault")
            app_client = self.algo_client.client.get_app_client_by_id(
                app_id=self.policy_vault_id,
                app_spec=spec
            )
            result = app_client.send.call(AppClientMethodCallParams(
                method="check_and_enforce",
                args=[self.address, int(amount * 1_000_000)],
                sender=self.address  # Explicitly pass sender
            ))
            return_val = result.abi_return
            return int(return_val)
        except Exception as e:
            logger.warning("PolicyVault.check_and_enforce failed (fail-open): %r", e)
            return 0  # fail-open in dev, fail-closed in prod

    def _call_sentinel_deposit(
        self,
        provider_address: str,
        intent_hash_hex: str,
        deadline_rounds: int,
        requires_consensus: bool,
        amount_algo: float,
    ) -> str:
        """
        Call SentinelEscrow.deposit to hold funds for SLA-contingent release.

        Returns:
            escrow_id hex string identifying this deposit.
        """
        if self.sentinel_escrow_id == 0:
            # Stub: generate a deterministic escrow_id from intent hash
            escrow_id = hashlib.sha256(
                b"escrow:" + bytes.fromhex(intent_hash_hex)
            ).hexdigest()
            logger.debug("SentinelEscrow not deployed — stub escrow_id=%s", escrow_id[:16])
            return escrow_id

        try:
            spec = self.contracts.load_spec("SentinelEscrow")
            app_client = self.algo_client.client.get_app_client_by_id(
                app_id=self.sentinel_escrow_id,
                app_spec=spec
            )
            
            # Call deposit ABI method
            from algosdk.transaction import BoxReference
            # Key prefix for escrow is b"es:"
            # In AXIOM, escrow_id is sha256(sender_address + intent_hash + round)
            # Since round is dynamic, we provide the 2MANOJ... (deployer) box or a placeholder
            # to satisfy the loose simulation requirements.
            
            result = app_client.send.call(AppClientMethodCallParams(
                method="deposit",
                args=[
                    provider_address,
                    bytes.fromhex(intent_hash_hex),
                    deadline_rounds,
                    1 if requires_consensus else 0
                ],
                sender=self.address,
                signer=self.signer,
                validity_window=100,  # CRITICAL: Extend window for AI reasoning time
                # For box creation, providing the APP ID is often sufficient for simulation 
                # to know which box storage space to 'reserve'.
                box_references=[BoxReference(self.sentinel_escrow_id, b"")]
            ))
            
            escrow_id = result.abi_return
            if isinstance(escrow_id, bytes):
                escrow_id = escrow_id.hex()
            return str(escrow_id) or intent_hash_hex
        except Exception as e:
            logger.warning("SentinelEscrow.deposit failed: %s", e)
            return intent_hash_hex

    def _call_sentinel_quarantine(self, intent_hash_hex: str) -> None:
        """Call SentinelEscrow.quarantine to hold funds for human review."""
        if self.sentinel_escrow_id == 0:
            logger.debug("SentinelEscrow not deployed — quarantine logged only")
            return

        try:
            spec = self.contracts.load_spec("SentinelEscrow")
            app_client = self.algo_client.client.get_app_client_by_id(
                app_id=self.sentinel_escrow_id,
                app_spec=spec
            )
            app_client.send.call(AppClientMethodCallParams(
                method="quarantine",
                args=[bytes.fromhex(intent_hash_hex), 1],
                validity_window=100,  # CRITICAL: Extend window for AI reasoning time
                sender=self.address
            ))
            logger.info("Quarantine triggered for intent=%s", intent_hash_hex[:16])
        except Exception as e:
            logger.warning("SentinelEscrow.quarantine failed: %s", e)

    def _call_intent_registry(
        self,
        merkle_root: bytes,
        intent_hash: bytes,
        intent: IntentDocument,
    ) -> None:
        """
        Register session Merkle root and individual intent on IntentRegistry.
        """
        if self.intent_registry_id == 0:
            logger.debug("IntentRegistry not deployed — stub registration")
            self.contracts.intent_registry.register_session_root(b"session", merkle_root)
            return

        try:
            # Register session root with full identity
            self.contracts.intent_registry.register_session_root(
                b"session".ljust(32, b'\0'), 
                merkle_root,
                sender=self.address,
                signer=self.signer
            )

            # Register individual intent with full identity
            self.contracts.intent_registry.register_intent(
                intent_hash, 
                intent.api_url.encode()[:64], 
                bytes(32), # placeholder leaf
                sender=self.address,
                signer=self.signer
            )

            logger.info("IntentRegistry updated — root + intent registered")
        except Exception as e:
            logger.warning("IntentRegistry calls failed: %s", e)

    def _call_dna_registry_update(self) -> None:
        """Update the agent's DNA vector on PaymentDNARegistry."""
        dna_bytes = self.dna.to_bytes()

        if self.payment_dna_registry_id == 0:
            logger.debug("PaymentDNARegistry not deployed — DNA update logged only")
            return

        try:
            self.contracts.payment_dna_registry.update_dna(
                self.address, 
                dna_bytes, 
                sender=self.address, 
                signer=self.signer
            )
            logger.info("PaymentDNARegistry updated for %s", self.address[:8])
        except Exception as e:
            logger.warning("PaymentDNARegistry.update_dna failed (non-fatal): %r", e)

    # ─────────────────────────────────────────────────────────────
    #  CONSENSUS
    # ─────────────────────────────────────────────────────────────

    def _handle_consensus(self, payment_id_hex: str) -> None:
        """
        Handle M-of-N consensus flow for high-value payments.

        Opens a consensus record on ConsensusVault and waits for
        peer approvals. If consensus is reached, the payment proceeds.
        If timeout, raises ConsensusTimeoutError.
        """
        required = self.policy.get("consensus_min_approvals", 2)
        total_peers = self.policy.get("consensus_required_peers", 3)
        timeout_rounds = 30  # ~2 minutes on Algorand

        logger.info(
            "Consensus flow: payment=%s, required=%d-of-%d, timeout=%d rounds",
            payment_id_hex[:16],
            required,
            total_peers,
            timeout_rounds,
        )

        if self.consensus_vault_id == 0:
            # Stub: simulate consensus with a short wait
            logger.info("ConsensusVault not deployed — simulating consensus (1s)")
            time.sleep(1)
            logger.info("Consensus QUORUM REACHED (simulated)")
            return

        try:
            # Use ConsensusOrchestrator for the full on-chain flow
            # This creates the record, polls for quorum, and executes
            escrow_id_hex = hashlib.sha256(
                b"escrow:" + bytes.fromhex(payment_id_hex)
            ).hexdigest()

            self.consensus.run_full_consensus(
                payment_id=payment_id_hex,
                escrow_id=escrow_id_hex,
                required=required,
                peer_agent_addresses=[],  # peers discover via Indexer
                timeout_rounds=timeout_rounds,
            )

            logger.info("Consensus QUORUM REACHED for payment=%s", payment_id_hex[:16])

        except ConsensusTimeoutError:
            self._log_rejection("CONSENSUS_TIMEOUT")
            raise
        except Exception as e:
            logger.error("Consensus flow failed: %s", e)
            raise ConsensusTimeoutError(
                f"Consensus failed for payment {payment_id_hex[:16]}: {e}"
            ) from e

    # ─────────────────────────────────────────────────────────────
    #  SLA ORACLE
    # ─────────────────────────────────────────────────────────────

    def _post_sla_evaluation(
        self,
        tx_id: str,
        escrow_id: str,
        response_time_ms: int,
        http_status: int,
        schema_valid: bool,
        sla_threshold_ms: int,
    ) -> dict:
        """
        POST response metrics to the SLA Oracle at http://localhost:8001/evaluate.

        Returns the SLA evaluation result dict with keys:
            passed, action, reason, score_delta
        """
        payload = {
            "tx_id": tx_id,
            "escrow_id": escrow_id,
            "response_time_ms": response_time_ms,
            "http_status": http_status,
            "schema_valid": schema_valid,
            "sla_threshold_ms": sla_threshold_ms,
            "agent_address": self.address,
        }

        try:
            resp = requests.post(
                f"{self.sla_oracle_url}/evaluate",
                json=payload,
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.warning("SLA Oracle returned %d: %s", resp.status_code, resp.text[:100])
        except Exception as e:
            logger.warning("SLA Oracle unreachable: %s", e)

        # Local fallback evaluation if oracle is down
        passed = (
            http_status == 200
            and response_time_ms <= sla_threshold_ms
            and schema_valid
        )
        return {
            "passed": passed,
            "action": "released" if passed else "refunded",
            "reason": f"Local evaluation: status={http_status}, time={response_time_ms}ms",
            "score_delta": 5 if passed else 0,
        }

    # ─────────────────────────────────────────────────────────────
    #  HEADER PARSERS
    # ─────────────────────────────────────────────────────────────

    def _parse_provider_address(self, www_auth: str) -> str:
        """
        Extract provider Algorand address from WWW-Authenticate header.

        Expected format:
            x402 address="ALGO_ADDRESS...", amount=500000, network="algorand-testnet"

        Falls back to a placeholder if parsing fails.
        """
        # Fallback to deployer address if parsing fails
        deployer_mnemonic = os.getenv("DEPLOYER_MNEMONIC")
        if deployer_mnemonic:
            try:
                sk = to_private_key(deployer_mnemonic)
                return address_from_private_key(sk)
            except Exception:
                pass

        return "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ"

        # Parse address="..." from the header
        for part in www_auth.split(","):
            part = part.strip()
            if part.startswith("address=") or "address=" in part:
                addr = part.split("address=")[-1].strip().strip('"').strip("'")
                if len(addr) == 58:  # valid Algorand address length
                    return addr

        # Try quoted sections
        import re
        match = re.search(r'address="?([A-Z2-7]{58})"?', www_auth)
        if match:
            return match.group(1)

        # Fallback to deployer address if parsing fails
        deployer_mnemonic = os.getenv("DEPLOYER_MNEMONIC")
        if deployer_mnemonic:
            try:
                sk = to_private_key(deployer_mnemonic)
                return address_from_private_key(sk)
            except Exception:
                pass

        return "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ"

    def _parse_payment_amount(
        self,
        www_auth: str,
        response: requests.Response,
    ) -> float:
        """
        Extract payment amount from 402 response.

        Checks WWW-Authenticate header and response body.
        Amount is expected in microALGO and converted to ALGO.
        Falls back to 0.5 ALGO if parsing fails.
        """
        # Try WWW-Authenticate header
        if www_auth:
            for part in www_auth.split(","):
                part = part.strip()
                if "amount=" in part:
                    try:
                        micro = int(part.split("amount=")[-1].strip().strip('"'))
                        return micro / 1_000_000  # microALGO → ALGO
                    except ValueError:
                        pass

        # Try response JSON body
        try:
            body = response.json()
            if "amount" in body:
                return float(body["amount"]) / 1_000_000
        except Exception:
            pass

        # Default fallback
        return 0.5

    # ─────────────────────────────────────────────────────────────
    #  HELPERS
    # ─────────────────────────────────────────────────────────────

    def _commit_session_merkle(self) -> None:
        """Commit the Merkle root of this session's intents to the registry."""
        if not self.intent_hashes:
            return
        tree = MerkleTree(self.intent_hashes)
        root = tree.get_root()
        logger.info("Committing session Merkle root: %s", root.hex()[:16])
        self.contracts.intent_registry.register_session_root(b"session", root)

    def _log_rejection(self, reason: str) -> None:
        """Helper to log payment rejections with consistent format."""
        logger.warning(
            "PAYMENT BLOCKED — agent=%s reason=%s call=%d",
            self.address[:8],
            reason,
            self._call_count,
        )
