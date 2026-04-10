from algopy import ARC4Contract, BoxMap, Bytes, UInt64, Account, Global, Txn
from algopy.arc4 import abimethod, Struct


class ConsensusRecord(Struct):
    """
    Tracks M-of-N peer approval state for one high-value payment.

    escrow_id          : the SentinelEscrow escrow being gated.
    required_approvals : M (minimum approvals needed).
    collected          : number of consents submitted so far.
    deadline_round     : Global.round at which this consensus expires.
    resolved           : 0 = pending, 1 = executed, 2 = timed-out/rejected.
    """
    escrow_id: Bytes
    required_approvals: UInt64
    collected: UInt64
    deadline_round: UInt64
    resolved: UInt64


class ConsensusVault(ARC4Contract):
    """
    M-of-N on-chain consent gating for payments above consensus_threshold_algo.

    Workflow:
      1. SentinelEscrow calls open_consensus()  -> creates ConsensusRecord.
      2. Each peer agent calls submit_consent()  -> increments collected.
      3. Any party calls execute_if_consensus()  -> triggers escrow release.
      4. After deadline, anyone calls timeout_reject() -> triggers refund.

    Note prefix on all inner txns: b"x402:axiom:consensus"
    """

    def __init__(self) -> None:
        self.consensus_records = BoxMap(Bytes, ConsensusRecord, key_prefix=b"cv:")
        # Consent bitmap: key = payment_id + peer_address_bytes (36B total)
        self.submitted = BoxMap(Bytes, UInt64, key_prefix=b"cs:")
        # Trusted sentinel app (set on create)
        self.sentinel_app_id = UInt64(0)

    @abimethod(create="require")
    def create(self, sentinel_escrow_app_id: UInt64) -> None:
        self.sentinel_app_id = sentinel_escrow_app_id

    # ------------------------------------------------------------------ #
    #  Consensus lifecycle
    # ------------------------------------------------------------------ #

    @abimethod()
    def open_consensus(
        self,
        payment_id: Bytes,
        escrow_id: Bytes,
        required: UInt64,
    ) -> None:
        """
        Create a new consensus record.
        deadline_round = Global.round + 30  (~2 minutes on Algorand).
        Only SentinelEscrow or the contract creator should call this.
        """
        assert payment_id.length == 32, "payment_id must be 32 bytes"
        assert escrow_id.length == 32, "escrow_id must be 32 bytes"
        assert required >= UInt64(1), "required must be >= 1"

        _, exists = self.consensus_records.maybe(payment_id)
        assert not exists, "consensus already open for this payment_id"

        self.consensus_records[payment_id] = ConsensusRecord(
            escrow_id=escrow_id,
            required_approvals=required,
            collected=UInt64(0),
            deadline_round=Global.round + UInt64(30),
            resolved=UInt64(0),
        )

    @abimethod()
    def submit_consent(self, payment_id: Bytes, consent_hash: Bytes) -> None:
        """
        A peer agent submits consent for the payment.
        Each address may only consent once (bitmap check via BoxMap).
        consent_hash : sha256(payment_id + peer_address) — prevents replay.
        """
        assert payment_id.length == 32, "payment_id must be 32 bytes"
        assert consent_hash.length == 32, "consent_hash must be 32 bytes"

        record, exists = self.consensus_records.maybe(payment_id)
        assert exists, "no consensus record for this payment_id"
        assert record.resolved == UInt64(0), "consensus already resolved"
        assert Global.round <= record.deadline_round, "consensus deadline passed"

        # Use consent_hash as dedup key (peer can't vote twice with same hash)
        _, already_voted = self.submitted.maybe(consent_hash)
        assert not already_voted, "this consent already submitted"

        self.submitted[consent_hash] = UInt64(1)

        self.consensus_records[payment_id] = ConsensusRecord(
            escrow_id=record.escrow_id,
            required_approvals=record.required_approvals,
            collected=record.collected + UInt64(1),
            deadline_round=record.deadline_round,
            resolved=UInt64(0),
        )

    @abimethod()
    def execute_if_consensus(self, payment_id: Bytes) -> UInt64:
        """
        Check if collected >= required; if so, mark resolved=1.
        Returns 1 if consensus was reached, 0 if still waiting.
        The SDK layer then calls SentinelEscrow.release() in the same atomic group.
        """
        record, exists = self.consensus_records.maybe(payment_id)
        assert exists, "no consensus record for this payment_id"
        assert record.resolved == UInt64(0), "already resolved"

        if record.collected >= record.required_approvals:
            self.consensus_records[payment_id] = ConsensusRecord(
                escrow_id=record.escrow_id,
                required_approvals=record.required_approvals,
                collected=record.collected,
                deadline_round=record.deadline_round,
                resolved=UInt64(1),
            )
            return UInt64(1)
        return UInt64(0)

    @abimethod()
    def timeout_reject(self, payment_id: Bytes) -> None:
        """
        After deadline passes, mark resolved=2 (timed out / rejected).
        SDK layer then calls SentinelEscrow.refund() atomically.
        """
        record, exists = self.consensus_records.maybe(payment_id)
        assert exists, "no consensus record for this payment_id"
        assert record.resolved == UInt64(0), "already resolved"
        assert Global.round > record.deadline_round, "deadline not yet passed"

        self.consensus_records[payment_id] = ConsensusRecord(
            escrow_id=record.escrow_id,
            required_approvals=record.required_approvals,
            collected=record.collected,
            deadline_round=record.deadline_round,
            resolved=UInt64(2),
        )

    # ------------------------------------------------------------------ #
    #  Read methods
    # ------------------------------------------------------------------ #

    @abimethod()
    def get_consensus_status(self, payment_id: Bytes) -> UInt64:
        """Returns resolved field: 0=pending, 1=executed, 2=rejected/timed-out."""
        record, exists = self.consensus_records.maybe(payment_id)
        assert exists, "no consensus record for this payment_id"
        return record.resolved

    @abimethod()
    def get_collected(self, payment_id: Bytes) -> UInt64:
        """Returns how many consents have been collected so far."""
        record, exists = self.consensus_records.maybe(payment_id)
        assert exists, "no consensus record"
        return record.collected
