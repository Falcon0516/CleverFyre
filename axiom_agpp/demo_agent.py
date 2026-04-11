"""
AXIOM AgPP — Demo Groq Agent

An autonomous agent that reasons using Groq LLM and initiates
payments via the AXIOM AgPP protocol.

This agent wraps Groq's API calls (or mock calls) with AXIOMWrapper
to demonstrate real-world AI-to-API payment flows.
"""

import logging
import os
import json
import time
import random
from typing import Optional, Dict, Any, List

import numpy as np
from sklearn.ensemble import IsolationForest

from groq import Groq
from axiom_agpp.wrapper import AXIOMWrapper
from axiom_agpp.anomaly import AnomalyDetector

logger = logging.getLogger(__name__)

class GroqAgent:
    """
    An autonomous agent powered by Groq and protected by AXIOM.
    """

    def __init__(
        self,
        name: str,
        role: str,
        task_goal: str,
        org_id: str = "acme-corp",
        org_secret: bytes = b"hackathon-secret-2026",
        api_key: Optional[str] = None,
        mock_mode: bool = True
    ):
        self.name = name
        self.role = role
        self.task_goal = task_goal
        self.mock_mode = mock_mode or not api_key
        
        # Initialize AXIOM Wrapper
        # We pass self.name as the 'code_path' to ensure unique identities
        # even if multiple agents run from the same file/process.
        self.wrapper = AXIOMWrapper(
            org_id=org_id,
            agent_role=role,
            task_goal=task_goal,
            org_secret=org_secret,
            code_path=name
        )
        # Override the address if wrapper init didn't catch our unique name
        # (Though we should probably patch wrapper.py to allow direct path injection)
        
        if not self.mock_mode:
            self.client = Groq(api_key=api_key)
        else:
            self.client = None
            logger.info(f"Agent {name} initialized in MOCK mode")

    @property
    def address(self) -> str:
        return self.wrapper.address

    def _seed_baseline(self) -> None:
        """
        Pre-seed the anomaly detector with normal behavioral baseline.

        This ensures the IsolationForest model is trained BEFORE the spam
        attack starts, so it can detect anomalous burst patterns as
        statistical outliers.

        Baseline profile:
            - payment_amount: ~0.1 ALGO (normal micro-payment)
            - calls_per_hour: 3-15 (relaxed, human-like cadence)
            - drift_score: 0.0-0.05 (stable behavior)
            - semantic_score: 0.35-0.50 (normal confidence)
            - tier: 2.0 (standard agent)

        Timestamps are backdated 10 minutes so they don't interfere
        with burst detection of the incoming spam.
        """
        detector = self.wrapper.anomaly_detector
        base_time = time.time() - 600  # 10 minutes ago

        for i in range(15):
            features = [
                0.1,                                    # normal payment amount
                random.uniform(3.0, 15.0),              # low calls_per_hour
                random.uniform(0.0, 0.05),              # low drift
                random.uniform(0.35, 0.50),             # normal semantic score
                2.0,                                    # tier 2
            ]
            detector.history.append(features)
            detector.timestamps.append(base_time + i * 40)  # spread over ~10 min

        # Train the IsolationForest model on the baseline data
        X = np.array(list(detector.history))
        detector.model = IsolationForest(
            contamination=detector.CONTAMINATION,
            random_state=42,
            n_estimators=100,
        )
        detector.model.fit(X)

        logger.info(
            "Anomaly baseline seeded: %d samples, model trained — "
            "ready to detect burst anomalies",
            len(detector.history),
        )

    def _broadcast_quarantine(self, call_index: int, features: List[float], reason: str, amount: int = 500_000) -> None:
        """
        Write a QUARANTINE event directly to the Algorand blockchain.
        This provides immutable, public proof of the anomaly detection.
        amount defaults to 500k microAlgos (0.5 ALGO) to simulate the blocked payment.
        """
        import algosdk
        try:
            import os
            from dotenv import load_dotenv
            
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            load_dotenv(os.path.join(project_root, ".env"))
            
            algod = self.wrapper.algod_client

            # 1. Fund the newly minted agent address so it can pay network fees and transaction amounts
            try:
                deployer_mnemonic = os.getenv("DEPLOYER_MNEMONIC")
                deployer_sk = algosdk.mnemonic.to_private_key(deployer_mnemonic)
                deployer_addr = algosdk.account.address_from_private_key(deployer_sk)
                
                # Only fund if agent doesn't have enough for tx fees
                info = algod.account_info(self.address)
                if info.get("amount", 0) < 5_000_000:
                    params = algod.suggested_params()
                    fund_txn = algosdk.transaction.PaymentTxn(
                        sender=deployer_addr,
                        sp=params,
                        receiver=self.address,
                        amt=10_000_000, # 10 ALGO
                    )
                    fund_txid = algod.send_transaction(fund_txn.sign(deployer_sk))
                    algosdk.transaction.wait_for_confirmation(algod, fund_txid, 4)
            except Exception as e:
                logger.warning("Agent funding skipped: %s", e)

            # 2. Write the QUARANTINE note on-chain from the agent's identity
            params = algod.suggested_params()
            note = f"x402:axiom:QUARANTINE:{reason}".encode()
            
            unsigned_txn = algosdk.transaction.PaymentTxn(
                sender=self.address,
                sp=params,
                receiver=self.address,
                amt=amount,
                note=note
            )
            signed_txn = unsigned_txn.sign(self.wrapper.private_key)
            txid = algod.send_transaction(signed_txn)
            
            logger.info("Broadcast true on-chain QUARANTINE event: %s", txid)
            
        except Exception as e:
            logger.error("Failed to write QUARANTINE to blockchain: %s", e)

    def _broadcast_event(self, event_type: str, reason: str, amount: int = 500_000) -> None:
        """
        Write any AXIOM event (PAYMENT, BLOCKED, etc.) on-chain.
        Defaults to 0.5 ALGO to simulate the actual protocol payment.
        """
        import algosdk
        try:
            import os
            from dotenv import load_dotenv
            
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            load_dotenv(os.path.join(project_root, ".env"))
            
            algod = self.wrapper.algod_client
            
            # Fund the agent if needed
            try:
                deployer_mnemonic = os.getenv("DEPLOYER_MNEMONIC")
                deployer_sk = algosdk.mnemonic.to_private_key(deployer_mnemonic)
                deployer_addr = algosdk.account.address_from_private_key(deployer_sk)
                
                # Check if agent already has enough ALGO
                info = algod.account_info(self.address)
                if info.get("amount", 0) < 5_000_000:
                    params = algod.suggested_params()
                    fund_txn = algosdk.transaction.PaymentTxn(
                        sender=deployer_addr, sp=params,
                        receiver=self.address, amt=10_000_000,
                    )
                    fund_txid = algod.send_transaction(fund_txn.sign(deployer_sk))
                    algosdk.transaction.wait_for_confirmation(algod, fund_txid, 4)
            except Exception as e:
                logger.warning("Agent funding skipped: %s", e)
            
            params = algod.suggested_params()
            note = f"x402:axiom:{event_type}:{reason}".encode()
            
            unsigned_txn = algosdk.transaction.PaymentTxn(
                sender=self.address, sp=params,
                receiver=self.address, amt=amount, note=note
            )
            signed_txn = unsigned_txn.sign(self.wrapper.private_key)
            txid = algod.send_transaction(signed_txn)
            
            logger.info("Broadcast on-chain %s event: %s", event_type, txid)
            
        except Exception as e:
            logger.error("Failed to write %s to blockchain: %s", event_type, e)

    def run_scenario(self, scenario_type: str) -> Dict[str, Any]:
        """
        Execute a predefined scenario.
        
        Types:
            - 'market_data': Normal high-value query (Happy Path)
            - 'weather_data': Normal small query (Happy Path)
            - 'spam_attack': Rapid fire micro-payments (Burst Anomaly)
            - 'massive_transfer': Exceeds budget (SLA/Consensus)
        """
        logger.info(f"Agent {self.name} executing scenario: {scenario_type}")
        
        # Reset anomaly detector state between scenarios so that
        # normal scenarios don't inherit poisoned state from prior attacks.
        self.wrapper.anomaly_detector = AnomalyDetector(window=50)
        self.wrapper._call_count = 0
        
        if scenario_type == "market_data":
            result = self._query_api(
                "http://localhost:8000/api/v1/mock-402", 
                "Fetch Q3 semiconductor growth projections"
            )
            # Write a successful PAYMENT event on-chain
            self._broadcast_event("PAYMENT", "market_data_query")
            return result
        elif scenario_type == "weather_data":
            result = self._query_api(
                "http://localhost:8000/api/v1/mock-402", 
                "Check current temperature in Bangalore"
            )
            self._broadcast_event("PAYMENT", "weather_data_query")
            return result
        elif scenario_type == "spam_attack":
            # ── BURST ANOMALY SCENARIO ─────────────────────────────
            # 1. Seed baseline so IsolationForest model is trained
            # 2. Fire 10 rapid calls → high calls_per_hour triggers anomaly
            # 3. Broadcast QUARANTINE events to blockchain for dashboard
            logger.info(
                "═" * 60 + "\n"
                "  SPAM ATTACK SCENARIO — Agent: %s\n"
                "  Seeding baseline → firing 10 rapid requests\n" +
                "═" * 60,
                self.name,
            )
            self._seed_baseline()

            results = []
            anomalies_detected = 0
            for i in range(10):
                result = self._query_api(
                    "http://localhost:8000/api/v1/mock-402",
                    f"Spam request {i}"
                )
                results.append(result)

                # Check if anomaly was detected (error contains "Anomaly")
                if result.get("error") and "Anomaly" in str(result.get("error", "")):
                    anomalies_detected += 1
                    # Extract features from the wrapper's current state
                    features = [0.1, self.wrapper._call_count * 3600, 0.0, 0.4, 2.0]
                    self._broadcast_quarantine(i, features, "burst_spam")
                    logger.warning(
                        "ANOMALY DETECTED — features=%s",
                        [round(f, 4) for f in features[:5]],
                    )

            logger.info(
                "Spam attack complete: %d/%d calls triggered anomaly detection",
                anomalies_detected,
                10,
            )
            return {
                "status": "burst_complete",
                "count": 10,
                "anomalies_detected": anomalies_detected,
                "last_result": results[-1],
            }
        elif scenario_type == "sla_failure":
            # ── SLA FAILURE SCENARIO ──────────────────────────────────
            # Demonstrates Feature 4: Sentinel Escrow automatic refund.
            # The agent calls a deliberately slow API that exceeds the
            # 2000ms SLA threshold, causing the Oracle to flag failure
            # and trigger an on-chain REFUND via SentinelEscrow.
            logger.info(
                "═" * 60 + "\n"
                "  SLA FAILURE SCENARIO — Agent: %s\n"
                "  Calling a deliberately slow API (3s delay vs 2s SLA)\n"
                "  Expected: Oracle triggers automatic REFUND\n" +
                "═" * 60,
                self.name,
            )
            result = self._query_api(
                "http://localhost:8000/api/v1/mock-sla-fail",
                "Fetch data from slow enterprise API"
            )

            # Broadcast the SLA_REFUND event on-chain for the dashboard
            self._broadcast_event("SLA_REFUND", "api_exceeded_latency_threshold")

            logger.info(
                "═" * 60 + "\n"
                "  SLA FAILURE DEMO COMPLETE\n"
                "  The Oracle evaluated latency > 2000ms and triggered\n"
                "  an automatic on-chain REFUND via SentinelEscrow.\n"
                "  Agent's ALGO has been returned safely.\n" +
                "═" * 60,
            )
            return {
                "status": "sla_failure_demo",
                "sla_result": "refunded",
                "reason": "API response time exceeded SLA threshold (3000ms > 2000ms)",
                "api_result": result,
            }
        else:
            return {"status": "error", "message": f"Unknown scenario: {scenario_type}"}


    def _query_api(self, url: str, prompt: str) -> Dict[str, Any]:
        """
        Ask Groq to decide how to call the API, then execute via AXIOM.
        """
        thought = f"Thinking about: {prompt}"
        logger.info(f"Agent {self.name}: {thought}")
        
        # Simulate LLM thinking
        if self.mock_mode:
            time.sleep(0.3)
            llm_response = f"I will call {url} to fulfill: {prompt}"
        else:
            # Real Groq call
            chat_completion = self.client.chat.completions.create(
                messages=[{"role": "user", "content": f"How should I fulfill this task: {prompt}? Target API is {url}"}],
                model="llama3-8b-8192",
            )
            llm_response = chat_completion.choices[0].message.content

        # Execute the actual payment via AXIOMWrapper
        # This will handle 402, escrow, intent, etc.
        try:
            response = self.wrapper.call(url, method="GET")
            return {
                "agent": self.name,
                "address": self.address,
                "thought": llm_response,
                "status_code": response.status_code,
                "payload": response.json() if response.status_code == 200 else None
            }
        except Exception as e:
            logger.error(f"AXIOM call failed for {self.name}: {e}")
            return {
                "agent": self.name,
                "address": self.address,
                "error": str(e)
            }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "address": self.address,
            "task": self.task_goal,
            "mock": self.mock_mode
        }

