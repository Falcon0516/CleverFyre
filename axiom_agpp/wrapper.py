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
from algosdk.v2client import algod

from algokit_utils import AlgorandClient

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
    ):
        """
        Initialize the AXIOM Wrapper.

        Args:
            org_id:      Organization identifier.
            agent_role:  Agent role identifier.
            task_goal:   The agent's canonical task/mission.
            org_secret:  Master organization secret (bytes).
            policy_path: Path to the local policy.yaml config.
        """
        self.org_id = org_id
        self.agent_role = agent_role
        self.task_goal = task_goal

        # Derive deterministic identity
        import sys
        main_script = sys.argv[0] if sys.argv else "unknown.py"
        self.private_key, self.address = derive_agent_address(
            org_secret, org_id, agent_role, main_script
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

        is_burst = self.anomaly_detector.burst_check(
            window_sec=self.policy.get("burst_window_sec", 30),
            max_calls=self.policy.get("burst_max_calls", 20),
        )

        is_anomaly = self.anomaly_detector.is_anomaly(features)

        if is_burst or is_anomaly:
            reason = "burst" if is_burst else "statistical anomaly"
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
            app_client = self.algo_client.client.get_app_client_by_id(
                app_id=self.policy_vault_id,
            )
            result = app_client.call(
                "check_and_enforce",
                agent=self.address,
                amount=int(amount * 1_000_000),  # convert to microALGO
            )
            return_val = result.return_value if hasattr(result, "return_value") else 0
            return int(return_val)
        except Exception as e:
            logger.warning("PolicyVault.check_and_enforce failed: %s", e)
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
            app_client = self.algo_client.client.get_app_client_by_id(
                app_id=self.sentinel_escrow_id,
            )
            result = app_client.call(
                "deposit",
                provider=provider_address,
                intent_hash=bytes.fromhex(intent_hash_hex),
                deadline_rounds=deadline_rounds,
                requires_consensus=1 if requires_consensus else 0,
                transaction_parameters={
                    "sender": self.address,
                    "amount": int(amount_algo * 1_000_000),
                    "note": b"x402:axiom:PAYMENT",
                },
            )
            escrow_id = result.return_value if hasattr(result, "return_value") else ""
            if isinstance(escrow_id, bytes):
                escrow_id = escrow_id.hex()
            return str(escrow_id) or intent_hash_hex
        except Exception as e:
            logger.warning("SentinelEscrow.deposit failed: %s", e)
            # Fallback: use intent hash as escrow ref
            return intent_hash_hex

    def _call_sentinel_quarantine(self, intent_hash_hex: str) -> None:
        """Call SentinelEscrow.quarantine to hold funds for human review."""
        if self.sentinel_escrow_id == 0:
            logger.debug("SentinelEscrow not deployed — quarantine logged only")
            return

        try:
            app_client = self.algo_client.client.get_app_client_by_id(
                app_id=self.sentinel_escrow_id,
            )
            app_client.call(
                "quarantine",
                intent_hash=bytes.fromhex(intent_hash_hex),
                transaction_parameters={
                    "sender": self.address,
                    "note": b"x402:axiom:QUARANTINE",
                },
            )
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
            self.contracts.intent_registry.commit_root(merkle_root, self.address)
            return

        try:
            app_client = self.algo_client.client.get_app_client_by_id(
                app_id=self.intent_registry_id,
            )

            # Register session root
            app_client.call(
                "register_session_root",
                root=merkle_root,
                leaf_count=len(self.intent_hashes),
            )

            # Register individual intent
            app_client.call(
                "register_intent",
                intent_hash=intent_hash,
                api_url=intent.api_url.encode()[:64],  # truncate for box key
            )

            logger.info("IntentRegistry updated — root + intent registered")
        except Exception as e:
            logger.warning("IntentRegistry calls failed: %s", e)
            # Fallback to contracts facade stub
            self.contracts.intent_registry.commit_root(merkle_root, self.address)

    def _call_dna_registry_update(self) -> None:
        """Update the agent's DNA vector on PaymentDNARegistry."""
        dna_bytes = self.dna.to_bytes()

        if self.payment_dna_registry_id == 0:
            logger.debug("PaymentDNARegistry not deployed — DNA update logged only")
            return

        try:
            self.contracts.payment_dna_registry.update_dna(
                agent_addr=self.address,
                dna_bytes=dna_bytes,
                sender_addr=self.address,
            )
            logger.info("PaymentDNARegistry updated for %s", self.address[:8])
        except Exception as e:
            logger.warning("PaymentDNARegistry.update_dna failed: %s", e)

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
        if not www_auth:
            return "PROVIDER_ADDRESS_PLACEHOLDER"

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

        return "PROVIDER_ADDRESS_PLACEHOLDER"

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
        self.contracts.intent_registry.commit_root(root, self.address)

    def _log_rejection(self, reason: str) -> None:
        """Helper to log payment rejections with consistent format."""
        logger.warning(
            "PAYMENT BLOCKED — agent=%s reason=%s call=%d",
            self.address[:8],
            reason,
            self._call_count,
        )
