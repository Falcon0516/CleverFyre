"""
AXIOM AgPP — Consensus Orchestrator

M-of-N atomic peer agent consent for high-value payments.
Uses Algorand's AtomicTransactionComposer to bundle consent transactions
plus the payment transaction atomically — all succeed or all fail.

When a payment exceeds the consensus_threshold_algo from policy.yaml,
this module coordinates multiple peer agents to approve the payment
before SentinelEscrow releases the funds.

Architecture:
    1. open_consensus()    — Creates a consensus record on ConsensusVault
    2. collect_consents()  — Polls the contract until M-of-N peers approve or deadline
    3. submit_atomic_group() — Bundles all consents + payment atomically via ATC
"""

import os
import time
import hashlib
import logging
from typing import Optional

from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    TransactionWithSigner,
)
from algosdk.transaction import PaymentTxn
from algosdk.v2client import algod

from algokit_utils import AlgorandClient

from axiom_agpp.exceptions import ConsensusTimeoutError

logger = logging.getLogger(__name__)


class ConsensusOrchestrator:
    """
    Orchestrates M-of-N peer agent consensus for high-value AXIOM payments.

    The ConsensusVault smart contract stores consensus records on-chain.
    Each record tracks:
      - escrow_id:            Link to the SentinelEscrow holding the funds
      - required_approvals:   M (minimum peer approvals needed)
      - collected:            Current number of peer approvals received
      - deadline_round:       Algorand round after which consensus times out
      - resolved:             Whether this consensus has been finalized

    Workflow:
      1. SentinelEscrow deposits funds and flags requires_consensus=1
      2. This orchestrator opens a consensus record on ConsensusVault
      3. Peer agents submit consent hashes via submit_consent()
      4. Once collected >= required, execute_if_consensus() triggers release
      5. If deadline passes without quorum, timeout_reject() triggers refund
    """

    # Algorand block time in seconds (~3.3s, we use 4s as safe upper bound)
    BLOCK_TIME_SECONDS = 4.0

    # How many rounds to wait between polls (2 rounds ≈ 8 seconds)
    POLL_INTERVAL_ROUNDS = 2

    def __init__(
        self,
        consensus_vault_id: Optional[int] = None,
        sentinel_escrow_id: Optional[int] = None,
    ):
        """
        Initialize the ConsensusOrchestrator.

        Args:
            consensus_vault_id: Application ID of the deployed ConsensusVault contract.
                                Falls back to CONSENSUS_VAULT_ID env var.
            sentinel_escrow_id: Application ID of the deployed SentinelEscrow contract.
                                Falls back to SENTINEL_ESCROW_ID env var.
        """
        self.vault_id = consensus_vault_id or int(
            os.getenv("CONSENSUS_VAULT_ID", "0")
        )
        self.escrow_id = sentinel_escrow_id or int(
            os.getenv("SENTINEL_ESCROW_ID", "0")
        )

        # AlgorandClient from algokit_utils — reads ALGOD_* env vars automatically
        self.algo_client = AlgorandClient.from_environment()

        # Raw algod client for lower-level operations (ATC, status queries)
        self.algod_client = algod.AlgodClient(
            os.getenv("ALGOD_TOKEN", "a" * 64),
            f"{os.getenv('ALGOD_SERVER', 'http://localhost')}:{os.getenv('ALGOD_PORT', '4001')}",
        )

        logger.info(
            "ConsensusOrchestrator initialized — vault_id=%d, escrow_id=%d",
            self.vault_id,
            self.escrow_id,
        )

    # ─────────────────────────────────────────────────────────────
    #  PUBLIC API
    # ─────────────────────────────────────────────────────────────

    def open_consensus(
        self,
        payment_id: str,
        escrow_id: str,
        required: int,
        peer_agent_addresses: list[str] | None = None,
    ) -> None:
        """
        Open a new consensus record on the ConsensusVault contract.

        This creates an on-chain record that peer agents can vote on.
        The record has a deadline of +30 rounds from current round (~2 minutes).

        Args:
            payment_id:           Unique identifier for this consensus vote (hex string).
            escrow_id:            SentinelEscrow escrow_id (hex string) holding the funds.
            required:             Minimum number of peer approvals needed (M in M-of-N).
            peer_agent_addresses: List of Algorand addresses of peer agents eligible to vote.
                                  Stored off-chain for notification; on-chain anyone can submit.

        Raises:
            Exception: If the contract call fails (e.g. invalid app ID, network error).
        """
        logger.info(
            "Opening consensus for payment=%s, escrow=%s, required=%d peers",
            payment_id[:16],
            escrow_id[:16],
            required,
        )

        try:
            # Get the typed client for ConsensusVault via algokit
            # The typed client is auto-generated by `algokit compile python`
            # and lives in smart_contracts/artifacts/consensus_vault/
            app_client = self.algo_client.client.get_app_client_by_id(
                app_id=self.vault_id,
            )

            # Call ConsensusVault.open_consensus(payment_id, escrow_id, required)
            app_client.call(
                "open_consensus",
                payment_id=bytes.fromhex(payment_id),
                escrow_id=bytes.fromhex(escrow_id),
                required=required,
            )

            logger.info(
                "Consensus record created on-chain for payment=%s (deadline=current+30 rounds)",
                payment_id[:16],
            )

            # Log peer addresses for off-chain notification / monitoring
            if peer_agent_addresses:
                logger.info(
                    "Eligible peers: %s",
                    ", ".join(addr[:8] + "..." for addr in peer_agent_addresses),
                )

        except Exception as e:
            logger.error("Failed to open consensus: %s", e)
            raise

    def collect_consents(
        self,
        payment_id: str,
        timeout_rounds: int = 30,
    ) -> bool:
        """
        Poll the ConsensusVault contract until quorum is reached or deadline passes.

        Checks every POLL_INTERVAL_ROUNDS (~8 seconds) whether enough peer agents
        have submitted their consent hashes.

        Args:
            payment_id:     The payment ID to poll consensus status for (hex string).
            timeout_rounds: Maximum number of rounds to wait from now.
                            Defaults to 30 rounds (~2 minutes on Algorand).

        Returns:
            True if consensus was reached (collected >= required).

        Raises:
            ConsensusTimeoutError: If the deadline passes without reaching quorum.
        """
        logger.info(
            "Polling consensus for payment=%s (timeout=%d rounds)",
            payment_id[:16],
            timeout_rounds,
        )

        # Determine the absolute deadline round
        current_round = self._get_current_round()
        deadline_round = current_round + timeout_rounds

        polls = 0
        while True:
            polls += 1
            now_round = self._get_current_round()

            # Check if deadline has passed
            if now_round > deadline_round:
                logger.warning(
                    "Consensus TIMED OUT for payment=%s at round %d (deadline was %d)",
                    payment_id[:16],
                    now_round,
                    deadline_round,
                )
                # Trigger on-chain timeout rejection
                self._trigger_timeout_reject(payment_id)
                raise ConsensusTimeoutError(
                    f"Consensus for payment {payment_id[:16]}... timed out at round "
                    f"{now_round} (deadline was {deadline_round}). "
                    f"Escrow funds will be refunded via SentinelEscrow."
                )

            # Query the contract for current consensus status
            try:
                result = self._query_consensus_status(payment_id)
                collected = result.get("collected", 0)
                required = result.get("required", 1)
                resolved = result.get("resolved", False)

                logger.debug(
                    "Poll #%d — payment=%s: collected=%d/%d, resolved=%s, round=%d/%d",
                    polls,
                    payment_id[:16],
                    collected,
                    required,
                    resolved,
                    now_round,
                    deadline_round,
                )

                # Already resolved by another caller
                if resolved:
                    logger.info(
                        "Consensus already resolved for payment=%s", payment_id[:16]
                    )
                    return collected >= required

                # Quorum reached!
                if collected >= required:
                    logger.info(
                        "✓ Consensus REACHED for payment=%s (%d/%d peers approved)",
                        payment_id[:16],
                        collected,
                        required,
                    )
                    return True

            except Exception as e:
                logger.warning("Error querying consensus status (will retry): %s", e)

            # Wait for POLL_INTERVAL_ROUNDS before next check
            sleep_seconds = self.POLL_INTERVAL_ROUNDS * self.BLOCK_TIME_SECONDS
            time.sleep(sleep_seconds)

    def submit_consent(
        self,
        payment_id: str,
        agent_private_key: str,
        agent_address: str,
    ) -> str:
        """
        Submit a single peer agent's consent hash to the ConsensusVault.

        The consent hash is sha256(payment_id + agent_address) proving the agent
        reviewed and approved this specific payment.

        Args:
            payment_id:        The payment ID to consent to (hex string).
            agent_private_key: The consenting agent's private key (base64 string).
            agent_address:     The consenting agent's Algorand address.

        Returns:
            Transaction ID of the consent submission.
        """
        # Derive consent hash: sha256(payment_id_bytes + agent_address_bytes)
        consent_hash = hashlib.sha256(
            bytes.fromhex(payment_id) + agent_address.encode()
        ).digest()

        logger.info(
            "Submitting consent for payment=%s from agent=%s...",
            payment_id[:16],
            agent_address[:8],
        )

        try:
            app_client = self.algo_client.client.get_app_client_by_id(
                app_id=self.vault_id,
            )

            result = app_client.call(
                "submit_consent",
                payment_id=bytes.fromhex(payment_id),
                consent_hash=consent_hash,
            )

            tx_id = result.tx_id if hasattr(result, "tx_id") else ""
            logger.info("Consent submitted — tx_id=%s", tx_id)
            return tx_id

        except Exception as e:
            logger.error("Failed to submit consent: %s", e)
            raise

    def submit_atomic_group(
        self,
        consent_txns: list[TransactionWithSigner],
        payment_txn: TransactionWithSigner,
    ) -> str:
        """
        Bundle all consent transactions + the payment transaction atomically.

        Uses Algorand's AtomicTransactionComposer (ATC) to ensure that either
        ALL transactions in the group succeed or ALL of them fail. This prevents
        partial execution — e.g., consents recorded but payment not executed.

        The atomic group typically contains:
          - N consent submission transactions (one per approving peer)
          - 1 execute_if_consensus call (triggers SentinelEscrow.release)

        Args:
            consent_txns: List of TransactionWithSigner objects, each representing
                          a peer agent's consent submission to ConsensusVault.
            payment_txn:  TransactionWithSigner for the final execute_if_consensus
                          call that triggers fund release from SentinelEscrow.

        Returns:
            The group transaction ID string (first tx_id in the atomic group).

        Raises:
            ConsensusTimeoutError: If the atomic group fails to execute
                                   (e.g., consensus deadline passed during assembly).
            Exception:             If any transaction in the group is malformed.
        """
        logger.info(
            "Assembling atomic group: %d consent txns + 1 payment txn",
            len(consent_txns),
        )

        atc = AtomicTransactionComposer()

        # Add each consent transaction to the atomic group
        for i, consent_tws in enumerate(consent_txns):
            atc.add_transaction(consent_tws)
            logger.debug("Added consent txn #%d to atomic group", i + 1)

        # Add the final payment/release transaction
        atc.add_transaction(payment_txn)
        logger.debug("Added payment txn to atomic group")

        # Execute the atomic group — all succeed or all fail
        try:
            result = atc.execute(self.algod_client, wait_rounds=4)

            group_tx_id = result.tx_ids[0] if result.tx_ids else ""
            logger.info(
                "✓ Atomic group executed successfully — group_tx_id=%s (%d txns)",
                group_tx_id,
                len(result.tx_ids),
            )

            # Log all individual transaction IDs for audit trail
            for i, tx_id in enumerate(result.tx_ids):
                logger.debug("  tx[%d]: %s", i, tx_id)

            return group_tx_id

        except Exception as e:
            error_msg = (
                f"Atomic group execution failed: {e}. "
                f"All {len(consent_txns) + 1} transactions rolled back."
            )
            logger.error(error_msg)
            raise ConsensusTimeoutError(error_msg) from e

    # ─────────────────────────────────────────────────────────────
    #  CONVENIENCE: Build consent TransactionWithSigner objects
    # ─────────────────────────────────────────────────────────────

    def build_consent_transaction(
        self,
        payment_id: str,
        agent_address: str,
        agent_signer,
    ) -> TransactionWithSigner:
        """
        Build a TransactionWithSigner for a peer agent's consent, ready for
        inclusion in an atomic group via submit_atomic_group().

        Args:
            payment_id:    The payment ID to consent to (hex string).
            agent_address: The consenting agent's Algorand address.
            agent_signer:  An AccountTransactionSigner for the agent's key.

        Returns:
            TransactionWithSigner ready to add to an AtomicTransactionComposer.
        """
        consent_hash = hashlib.sha256(
            bytes.fromhex(payment_id) + agent_address.encode()
        ).digest()

        # Build an application call transaction to ConsensusVault.submit_consent
        sp = self.algod_client.suggested_params()

        from algosdk.transaction import ApplicationCallTxn
        from algosdk.abi import Method

        # ABI method signature for submit_consent(byte[],byte[])void
        method = Method.from_signature("submit_consent(byte[],byte[])void")

        txn = ApplicationCallTxn(
            sender=agent_address,
            sp=sp,
            index=self.vault_id,
            app_args=[
                method.get_selector(),
                bytes.fromhex(payment_id),
                consent_hash,
            ],
            note=b"x402:axiom:CONSENT",
        )

        return TransactionWithSigner(txn=txn, signer=agent_signer)

    def build_execute_transaction(
        self,
        payment_id: str,
        sender_address: str,
        sender_signer,
    ) -> TransactionWithSigner:
        """
        Build a TransactionWithSigner for execute_if_consensus, triggering
        SentinelEscrow.release() if quorum has been met.

        Args:
            payment_id:     The payment ID to execute (hex string).
            sender_address: The address calling execute (typically the orchestrating agent).
            sender_signer:  An AccountTransactionSigner for the sender's key.

        Returns:
            TransactionWithSigner ready to add to an AtomicTransactionComposer.
        """
        sp = self.algod_client.suggested_params()

        from algosdk.transaction import ApplicationCallTxn
        from algosdk.abi import Method

        method = Method.from_signature("execute_if_consensus(byte[])uint64")

        txn = ApplicationCallTxn(
            sender=sender_address,
            sp=sp,
            index=self.vault_id,
            app_args=[
                method.get_selector(),
                bytes.fromhex(payment_id),
            ],
            note=b"x402:axiom:EXECUTE_CONSENSUS",
        )

        return TransactionWithSigner(txn=txn, signer=sender_signer)

    # ─────────────────────────────────────────────────────────────
    #  FULL WORKFLOW HELPER
    # ─────────────────────────────────────────────────────────────

    def run_full_consensus(
        self,
        payment_id: str,
        escrow_id: str,
        required: int,
        peer_agent_addresses: list[str],
        timeout_rounds: int = 30,
    ) -> str:
        """
        Execute the complete consensus workflow end-to-end:
          1. Open consensus record on-chain
          2. Poll until quorum is reached or deadline passes
          3. Call execute_if_consensus to trigger SentinelEscrow.release()

        This is the high-level entry point used by AXIOMWrapper._handle_402()
        for payments exceeding the consensus_threshold_algo.

        Args:
            payment_id:           Unique payment identifier (hex string).
            escrow_id:            SentinelEscrow escrow ID (hex string).
            required:             Minimum peer approvals (M in M-of-N).
            peer_agent_addresses: Eligible peer Algorand addresses.
            timeout_rounds:       Max rounds to wait (default 30 ≈ 2 min).

        Returns:
            Transaction ID of the execute_if_consensus call.

        Raises:
            ConsensusTimeoutError: If quorum is not reached before deadline.
        """
        logger.info(
            "═══ Starting full consensus workflow for payment=%s ═══",
            payment_id[:16],
        )

        # Step 1: Open consensus record on ConsensusVault
        self.open_consensus(payment_id, escrow_id, required, peer_agent_addresses)

        # Step 2: Poll until quorum (peers submit consents independently)
        consensus_reached = self.collect_consents(payment_id, timeout_rounds)

        if not consensus_reached:
            raise ConsensusTimeoutError(
                f"Consensus not reached for payment {payment_id[:16]}..."
            )

        # Step 3: Execute — triggers SentinelEscrow.release() on-chain
        try:
            app_client = self.algo_client.client.get_app_client_by_id(
                app_id=self.vault_id,
            )
            result = app_client.call(
                "execute_if_consensus",
                payment_id=bytes.fromhex(payment_id),
            )
            tx_id = result.tx_id if hasattr(result, "tx_id") else ""
            logger.info(
                "═══ Consensus executed — payment=%s released, tx=%s ═══",
                payment_id[:16],
                tx_id,
            )
            return tx_id

        except Exception as e:
            logger.error("Failed to execute consensus: %s", e)
            raise ConsensusTimeoutError(
                f"Consensus reached but execution failed: {e}"
            ) from e

    # ─────────────────────────────────────────────────────────────
    #  INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────────

    def _get_current_round(self) -> int:
        """Query algod for the latest confirmed round."""
        try:
            status = self.algod_client.status()
            return status.get("last-round", 0)
        except Exception as e:
            logger.warning("Failed to get current round: %s", e)
            return 0

    def _query_consensus_status(self, payment_id: str) -> dict:
        """
        Query the ConsensusVault for the current state of a consensus record.

        Returns a dict with keys: collected, required, resolved, deadline_round.
        Falls back to stub values if contract is not yet deployed.
        """
        try:
            app_client = self.algo_client.client.get_app_client_by_id(
                app_id=self.vault_id,
            )

            # Try calling execute_if_consensus as a read — returns 1 if executed, 0 if waiting
            # For status, we read the box storage directly
            payment_bytes = bytes.fromhex(payment_id)
            box_name = payment_bytes  # ConsensusVault keys by payment_id bytes

            # Read box value from the contract's box storage
            box_response = self.algod_client.application_box_by_name(
                self.vault_id, box_name
            )
            box_value = box_response.get("value", "")

            if box_value:
                import base64

                raw = base64.b64decode(box_value)
                # ConsensusRecord layout (ARC4 encoding):
                #   escrow_id:            32 bytes
                #   required_approvals:   8 bytes (uint64)
                #   collected:            8 bytes (uint64)
                #   deadline_round:       8 bytes (uint64)
                #   resolved:             8 bytes (uint64)
                if len(raw) >= 64:
                    required = int.from_bytes(raw[32:40], "big")
                    collected = int.from_bytes(raw[40:48], "big")
                    deadline = int.from_bytes(raw[48:56], "big")
                    resolved = int.from_bytes(raw[56:64], "big") != 0
                    return {
                        "collected": collected,
                        "required": required,
                        "deadline_round": deadline,
                        "resolved": resolved,
                    }

        except Exception as e:
            logger.debug("Box read failed (contract may not be deployed): %s", e)

        # Stub fallback — returns "waiting" status until contracts are live
        return {
            "collected": 0,
            "required": 1,
            "deadline_round": self._get_current_round() + 30,
            "resolved": False,
        }

    def _trigger_timeout_reject(self, payment_id: str) -> None:
        """
        Call ConsensusVault.timeout_reject() to trigger SentinelEscrow.refund().
        Called automatically when collect_consents() detects deadline has passed.
        """
        try:
            app_client = self.algo_client.client.get_app_client_by_id(
                app_id=self.vault_id,
            )
            app_client.call(
                "timeout_reject",
                payment_id=bytes.fromhex(payment_id),
            )
            logger.info(
                "Timeout reject triggered for payment=%s — funds refunding",
                payment_id[:16],
            )
        except Exception as e:
            logger.error(
                "Failed to trigger timeout_reject (manual intervention may be needed): %s",
                e,
            )
