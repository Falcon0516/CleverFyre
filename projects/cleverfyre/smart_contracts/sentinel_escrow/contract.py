from algopy import (
    ARC4Contract,
    BoxMap,
    Bytes,
    Account,
    UInt64,
    Global,
    Txn,
    itxn,
    op,
)
from algopy.arc4 import abimethod, Struct


class EscrowRecord(Struct):
    """
    One escrowed payment.

    payer              : ALGO sender (the AI agent).
    provider           : API provider to pay on SLA pass.
    amount             : microALGO held in escrow.
    deadline_round     : if not released by this round, refund is valid.
    quarantine_flag    : 0 = clear, 1 = quarantined (human review needed).
    consensus_required : 0 = auto-release, 1 = requires ConsensusVault approval.
    intent_hash        : 32-byte sha256 of the IntentDocument JSON.
    status             : 0=open, 1=released, 2=refunded, 3=quarantined.
    """
    payer: Account
    provider: Account
    amount: UInt64
    deadline_round: UInt64
    quarantine_flag: UInt64
    consensus_required: UInt64
    intent_hash: Bytes
    status: UInt64


class BlockedEvent(Struct):
    """Audit record written to box storage when a payment is blocked."""
    escrow_id: Bytes
    reason_code: UInt64
    blocked_round: UInt64
    payer: Account


AXIOM_PREFIX = b"x402:axiom:"


class SentinelEscrow(ARC4Contract):
    """
    Payment hub — ALL ALGO for AXIOM-governed payments flows through here.

    Deposit -> (oracle evaluates SLA) -> Release  OR  Refund
                                      -> Quarantine -> admin_resolve

    Note prefix on all inner transactions: b"x402:axiom:"
    """

    def __init__(self) -> None:
        self.escrows = BoxMap(Bytes, EscrowRecord, key_prefix=b"es:")
        self.blocked_log = BoxMap(Bytes, BlockedEvent, key_prefix=b"bl:")
        # App IDs of trusted callers (set in create)
        self.policy_vault_app_id = UInt64(0)
        self.reputation_ledger_app_id = UInt64(0)
        self.dna_registry_app_id = UInt64(0)

    @abimethod(create="require")
    def create(
        self,
        policy_vault_app_id: UInt64,
    ) -> None:
        """Called once on deploy. Records the PolicyVault app ID."""
        self.policy_vault_app_id = policy_vault_app_id

    # ------------------------------------------------------------------ #
    #  Core escrow lifecycle
    # ------------------------------------------------------------------ #

    @abimethod()
    def deposit(
        self,
        provider: Account,
        intent_hash: Bytes,
        deadline_rounds: UInt64,
        requires_consensus: UInt64,
    ) -> Bytes:
        """
        Accept an incoming ALGO payment and open an escrow record.

        The caller must attach a PaymentTransaction (inner group) whose
        receiver is this app's address.  Amount is read from that txn.

        Returns the 32-byte escrow_id = sha256(payer_bytes + intent_hash + round_bytes).
        """
        assert intent_hash.length == 32, "intent_hash must be 32 bytes"

        payer = Txn.sender
        amount = Txn.fee  # placeholder — real amount from attached pay txn

        # Derive deterministic escrow_id
        round_bytes = op.itob(Global.round)
        escrow_id = op.sha256(
            Txn.sender.bytes + intent_hash + round_bytes
        )

        self.escrows[escrow_id] = EscrowRecord(
            payer=Account(payer.bytes),
            provider=Account(provider.bytes),
            amount=amount,
            deadline_round=Global.round + deadline_rounds,
            quarantine_flag=UInt64(0),
            consensus_required=requires_consensus,
            intent_hash=intent_hash,
            status=UInt64(0),
        )

        return escrow_id

    @abimethod()
    def release(self, escrow_id: Bytes) -> None:
        """
        SLA passed — transfer ALGO to provider.
        Oracle calls this when HTTP 200 + latency within threshold.
        Emits b"x402:axiom:RELEASE" in inner-txn note.
        """
        assert escrow_id.length == 32, "invalid escrow_id"
        record, exists = self.escrows.maybe(escrow_id)
        assert exists, "escrow not found"
        assert record.status == UInt64(0), "escrow already settled"
        assert record.quarantine_flag == UInt64(0), "escrow is quarantined"

        # Inner payment to provider
        itxn.Payment(
            receiver=record.provider,
            amount=record.amount,
            note=AXIOM_PREFIX + b"RELEASE",
            fee=UInt64(0),
        ).submit()

        # Mark settled
        self.escrows[escrow_id] = EscrowRecord(
            payer=record.payer,
            provider=record.provider,
            amount=record.amount,
            deadline_round=record.deadline_round,
            quarantine_flag=record.quarantine_flag,
            consensus_required=record.consensus_required,
            intent_hash=record.intent_hash,
            status=UInt64(1),
        )

    @abimethod()
    def refund(self, escrow_id: Bytes) -> None:
        """
        SLA failed or deadline passed — return ALGO to payer.
        Emits b"x402:axiom:REFUND" in inner-txn note.
        """
        assert escrow_id.length == 32, "invalid escrow_id"
        record, exists = self.escrows.maybe(escrow_id)
        assert exists, "escrow not found"
        assert record.status == UInt64(0), "escrow already settled"

        # Allow refund if: deadline passed OR oracle explicitly calls
        is_overdue = Global.round > record.deadline_round
        assert is_overdue or Txn.sender == Global.creator_address, (
            "not yet overdue and caller is not oracle"
        )

        itxn.Payment(
            receiver=record.payer,
            amount=record.amount,
            note=AXIOM_PREFIX + b"REFUND",
            fee=UInt64(0),
        ).submit()

        self.escrows[escrow_id] = EscrowRecord(
            payer=record.payer,
            provider=record.provider,
            amount=record.amount,
            deadline_round=record.deadline_round,
            quarantine_flag=record.quarantine_flag,
            consensus_required=record.consensus_required,
            intent_hash=record.intent_hash,
            status=UInt64(2),
        )

    @abimethod()
    def quarantine(self, escrow_id: Bytes, reason_code: UInt64) -> None:
        """
        Flag a payment for human review.
        Triggered by: anomaly detector, burst check, DNA drift > threshold.
        reason_code:
          1 = anomaly detected
          2 = burst rate exceeded
          3 = DNA drift > 0.30
          4 = reputation too low
          5 = semantic mismatch
          6 = policy expired
        """
        assert escrow_id.length == 32, "invalid escrow_id"
        record, exists = self.escrows.maybe(escrow_id)
        assert exists, "escrow not found"
        assert record.status == UInt64(0), "escrow already settled"

        self.escrows[escrow_id] = EscrowRecord(
            payer=record.payer,
            provider=record.provider,
            amount=record.amount,
            deadline_round=record.deadline_round,
            quarantine_flag=UInt64(1),
            consensus_required=record.consensus_required,
            intent_hash=record.intent_hash,
            status=UInt64(3),
        )

        # Write audit log to blocked_log box
        log_key = op.sha256(escrow_id + op.itob(Global.round))
        self.blocked_log[log_key] = BlockedEvent(
            escrow_id=escrow_id,
            reason_code=reason_code,
            blocked_round=Global.round,
            payer=record.payer,
        )

    @abimethod()
    def admin_resolve(self, escrow_id: Bytes, approved: UInt64) -> None:
        """
        Operator approves or rejects a quarantined payment.
        approved=1 -> release()  |  approved=0 -> refund()
        Must be called by the contract creator (org admin).
        """
        assert Txn.sender == Global.creator_address, "only admin can resolve"
        record, exists = self.escrows.maybe(escrow_id)
        assert exists, "escrow not found"
        assert record.status == UInt64(3), "escrow is not quarantined"

        # Clear quarantine flag so release/refund can proceed
        self.escrows[escrow_id] = EscrowRecord(
            payer=record.payer,
            provider=record.provider,
            amount=record.amount,
            deadline_round=record.deadline_round,
            quarantine_flag=UInt64(0),
            consensus_required=record.consensus_required,
            intent_hash=record.intent_hash,
            status=UInt64(0),
        )

        if approved == UInt64(1):
            self.release(escrow_id)
        else:
            self.refund(escrow_id)

    # ------------------------------------------------------------------ #
    #  Read methods
    # ------------------------------------------------------------------ #

    @abimethod()
    def get_escrow_status(self, escrow_id: Bytes) -> UInt64:
        """Returns status: 0=open, 1=released, 2=refunded, 3=quarantined."""
        record, exists = self.escrows.maybe(escrow_id)
        assert exists, "escrow not found"
        return record.status

    @abimethod()
    def get_escrow_amount(self, escrow_id: Bytes) -> UInt64:
        """Returns the escrowed microALGO amount."""
        record, exists = self.escrows.maybe(escrow_id)
        assert exists, "escrow not found"
        return record.amount
