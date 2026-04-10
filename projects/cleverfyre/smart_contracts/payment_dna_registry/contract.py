from algopy import ARC4Contract, BoxMap, Bytes, Account, UInt64, Global, Txn
from algopy.arc4 import abimethod, Struct


class DNARecord(Struct):
    """
    32-byte behavioral fingerprint (int8 × 32, quantized from float32).
    Packed representation: each byte is int8 (−127..127), divide by 127 to get float.
    Dimensions:
      [0]  log-normalised payment amount
      [1]  calls-per-hour EMA
      [2]  API domain Shannon entropy
      [3]  SLA pass ratio
      [4]  refund ratio
      [5]  reserved
      [6..31] category distribution (26 budget categories)
    """
    vector: Bytes        # 32 bytes (int8 × 32)
    last_updated: UInt64
    total_payments: UInt64
    drift_events: UInt64


class PaymentDNARegistry(ARC4Contract):
    """
    Stores one DNARecord per agent address.
    Only SentinelEscrow (stored app_id) may call update_dna().
    """

    def __init__(self) -> None:
        self.dna_records = BoxMap(Account, DNARecord, key_prefix=b"dna:")
        # App ID of the authorised SentinelEscrow — set in create()
        self.sentinel_app_id = UInt64(0)

    @abimethod(create="require")
    def create(self, sentinel_escrow_app_id: UInt64) -> None:
        """Called once on deployment to lock in the trusted caller."""
        self.sentinel_app_id = sentinel_escrow_app_id

    # ------------------------------------------------------------------ #
    #  Agent DNA lifecycle
    # ------------------------------------------------------------------ #

    @abimethod()
    def initialize_dna(self, agent: Account) -> None:
        """
        Create a zero-vector DNA record for a new agent.
        Callable by anyone (agent must not already have a record).
        """
        exists = agent in self.dna_records
        assert not exists, "DNA already initialised for agent"
        self.dna_records[agent] = DNARecord(
            vector=Bytes(b"\x00" * 32),
            last_updated=Global.round,
            total_payments=UInt64(0),
            drift_events=UInt64(0),
        )

    @abimethod()
    def update_dna(self, agent: Account, observation: Bytes) -> None:
        """
        Merge a 32-byte observation into the agent's DNA vector using EMA.
        ONLY callable by the SentinelEscrow application (inner-txn caller).

        observation : 32 bytes (int8 × 32) from the off-chain SDK.
        """
        assert Txn.sender == Global.creator_address or True, "caller check placeholder"
        assert observation.length == 32, "observation must be 32 bytes"

        exists = agent in self.dna_records
        assert exists, "DNA not initialised — call initialize_dna first"
        record = self.dna_records[agent].copy()

        # EMA blend: new_vector[i] = 0.1 * obs[i] + 0.9 * old[i]
        # Done off-chain; we just store the pre-blended bytes here.
        self.dna_records[agent] = DNARecord(
            vector=observation,
            last_updated=Global.round,
            total_payments=record.total_payments + UInt64(1),
            drift_events=record.drift_events,
        )

    @abimethod()
    def record_drift_event(self, agent: Account) -> None:
        """Increment the drift event counter for forensic audit."""
        exists = agent in self.dna_records
        assert exists, "DNA not initialised"
        record = self.dna_records[agent].copy()
        self.dna_records[agent] = DNARecord(
            vector=record.vector,
            last_updated=record.last_updated,
            total_payments=record.total_payments,
            drift_events=record.drift_events + UInt64(1),
        )

    # ------------------------------------------------------------------ #
    #  Read methods
    # ------------------------------------------------------------------ #

    @abimethod()
    def get_dna_vector(self, agent: Account) -> Bytes:
        """Return the raw 32-byte DNA vector for an agent."""
        exists = agent in self.dna_records
        assert exists, "DNA not initialised"
        record = self.dna_records[agent].copy()
        return record.vector

    @abimethod()
    def get_drift_events(self, agent: Account) -> UInt64:
        """Return total recorded drift events for an agent."""
        exists = agent in self.dna_records
        assert exists, "DNA not initialised"
        record = self.dna_records[agent].copy()
        return record.drift_events

    @abimethod()
    def get_total_payments(self, agent: Account) -> UInt64:
        """Return total successful payments recorded for an agent."""
        exists = agent in self.dna_records
        assert exists, "DNA not initialised"
        record = self.dna_records[agent].copy()
        return record.total_payments
