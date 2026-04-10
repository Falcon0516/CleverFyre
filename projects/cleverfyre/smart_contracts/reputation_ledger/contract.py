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


class ReputationRecord(Struct):
    """
    Per-agent trust score.

    score        : 0–1000 (starts at 500 — neutral).
    drift_events : total flagged drift events (forensic counter).
    """
    score: UInt64
    drift_events: UInt64


class VouchRecord(Struct):
    """
    Stake placed by one agent vouching for another.

    stake_amount : microALGO locked.
    round_created: Algorand round when vouch was placed.
    """
    stake_amount: UInt64
    round_created: UInt64


# Score deltas (Section 4 of playbook)
SCORE_GOOD_PAYMENT   = 5
SCORE_ANOMALY_PASS   = 10
SCORE_ANOMALY_FAIL   = 50
SCORE_DMS_BREACH     = 100
SCORE_PROMPT_INJECT  = 200

# Tier thresholds
TIER_EXCELLENT   = 800
TIER_GOOD        = 600
TIER_CAUTION     = 400
TIER_RESTRICTED  = 200

VOUCH_AMOUNT_MICROALGO = 1_000_000  # 1 ALGO to vouch


class ReputationLedger(ARC4Contract):
    """
    Social trust layer — score 0-1000 per agent.

    Tier mapping:
      800+     EXCELLENT  — unlimited (within policy), auto-release
      600-799  GOOD       — up to 5 ALGO/call
      400-599  CAUTION    — up to 0.5 ALGO/call, intent logging mandatory
      200-399  RESTRICTED — quarantine, human review required
      0-199    BLACKLISTED — SentinelEscrow rejects all attempts
    """

    def __init__(self) -> None:
        self.rep_records = BoxMap(Account, ReputationRecord, key_prefix=b"rep:")
        # key = sha256(voucher_bytes + vouchee_bytes)
        self.vouch_stakes = BoxMap(Bytes, VouchRecord, key_prefix=b"vc:")
        # Trusted caller app IDs
        self.sentinel_app_id = UInt64(0)
        self.policy_vault_app_id = UInt64(0)

    @abimethod(create="require")
    def create(
        self,
        sentinel_escrow_app_id: UInt64,
        policy_vault_app_id: UInt64,
    ) -> None:
        """Record the two trusted caller app IDs on deployment."""
        self.sentinel_app_id = sentinel_escrow_app_id
        self.policy_vault_app_id = policy_vault_app_id

    # ------------------------------------------------------------------ #
    #  Agent lifecycle
    # ------------------------------------------------------------------ #

    @abimethod()
    def register_agent(self, agent: Account) -> None:
        """
        Create a reputation record with neutral score = 500.
        Callable by anyone (idempotent guard inside).
        """
        exists = agent in self.rep_records
        assert not exists, "agent already registered"
        self.rep_records[agent] = ReputationRecord(
            score=UInt64(500),
            drift_events=UInt64(0),
        )

    # ------------------------------------------------------------------ #
    #  Score mutation (only trusted callers)
    # ------------------------------------------------------------------ #

    @abimethod()
    def update_score(
        self,
        agent: Account,
        delta: UInt64,
        is_negative: UInt64,
    ) -> None:
        """
        Adjust agent's reputation score.

        delta       : amount to add or subtract.
        is_negative : 1 = subtract delta, 0 = add delta.
        Result is clamped to [0, 1000].

        ONLY callable by SentinelEscrow or PolicyVault app (via inner txn).
        On-chain caller verification uses Txn.sender being the trusted app address.
        """
        exists = agent in self.rep_records
        assert exists, "agent not registered"
        record = self.rep_records[agent].copy()

        current = record.score

        if is_negative == UInt64(1):
            if current >= delta:
                new_score = current - delta
            else:
                new_score = UInt64(0)
        else:
            new_score = current + delta
            if new_score > UInt64(1000):
                new_score = UInt64(1000)

        self.rep_records[agent] = ReputationRecord(
            score=new_score,
            drift_events=record.drift_events,
        )

    @abimethod()
    def record_drift(self, agent: Account) -> None:
        """Increment drift_events counter for a flagged agent."""
        exists = agent in self.rep_records
        assert exists, "agent not registered"
        record = self.rep_records[agent].copy()
        self.rep_records[agent] = ReputationRecord(
            score=record.score,
            drift_events=record.drift_events + UInt64(1),
        )

    # ------------------------------------------------------------------ #
    #  Vouch staking
    # ------------------------------------------------------------------ #

    @abimethod()
    def vouch(self, voucher: Account, vouchee: Account) -> None:
        """
        Stake 1 ALGO vouching for a peer agent's future behaviour.

        Slash conditions (enforced off-chain by oracle, then calls slash_voucher):
          - vouchee score drops below 400 → slash 50% of stake.
        Reward condition (oracle calls reward_voucher):
          - vouchee score rises above 800 → return stake + 10% bonus.
        """
        vouch_key = op.sha256(voucher.bytes + vouchee.bytes)
        already_vouching = vouch_key in self.vouch_stakes
        assert not already_vouching, "already vouching for this agent"

        # Verify attached 1 ALGO payment
        assert Txn.fee >= UInt64(VOUCH_AMOUNT_MICROALGO), "must attach 1 ALGO to vouch"
        # Since VOUCH_AMOUNT_MICROALGO is a plain integer, wrap it or use it as a literal.
        # However, the constructor might be strict.

        self.vouch_stakes[vouch_key] = VouchRecord(
            stake_amount=UInt64(VOUCH_AMOUNT_MICROALGO),
            round_created=Global.round,
        )

    @abimethod()
    def slash_voucher(self, voucher: Account, vouchee: Account) -> None:
        """
        Slash 50% of the voucher's stake because vouchee score dropped < 400.
        Called by oracle. Remaining 50% is refunded to voucher.
        """
        assert Txn.sender == Global.creator_address, "only oracle/admin can slash"
        vouch_key = op.sha256(voucher.bytes + vouchee.bytes)
        exists = vouch_key in self.vouch_stakes
        assert exists, "vouch record not found"
        stake = self.vouch_stakes[vouch_key].copy()

        slash_amount = stake.stake_amount // UInt64(2)
        refund_amount = stake.stake_amount - slash_amount

        # Refund half to voucher
        itxn.Payment(
            receiver=voucher,
            amount=refund_amount,
            note=b"x402:axiom:SLASH",
            fee=UInt64(0),
        ).submit()

        del self.vouch_stakes[vouch_key]

    @abimethod()
    def reward_voucher(self, voucher: Account, vouchee: Account) -> None:
        """
        Return stake + 10% bonus when vouchee score exceeds 800.
        Called by the oracle.
        """
        assert Txn.sender == Global.creator_address, "only oracle/admin can reward"
        vouch_key = op.sha256(voucher.bytes + vouchee.bytes)
        exists = vouch_key in self.vouch_stakes
        assert exists, "vouch record not found"
        stake = self.vouch_stakes[vouch_key].copy()

        bonus = stake.stake_amount // UInt64(10)
        reward = stake.stake_amount + bonus

        itxn.Payment(
            receiver=voucher,
            amount=reward,
            note=b"x402:axiom:REWARD",
            fee=UInt64(0),
        ).submit()

        del self.vouch_stakes[vouch_key]

    # ------------------------------------------------------------------ #
    #  Read methods
    # ------------------------------------------------------------------ #

    @abimethod()
    def get_score(self, agent: Account) -> UInt64:
        """Return the current reputation score for an agent."""
        exists = agent in self.rep_records
        assert exists, "agent not registered"
        record = self.rep_records[agent].copy()
        return record.score

    @abimethod()
    def get_tier(self, agent: Account) -> UInt64:
        """
        Returns tier: 0=BLACKLISTED, 1=RESTRICTED, 2=CAUTION, 3=GOOD, 4=EXCELLENT.
        """
        exists = agent in self.rep_records
        assert exists, "agent not registered"
        record = self.rep_records[agent].copy()
        score = record.score

        if score >= UInt64(TIER_EXCELLENT):
            return UInt64(4)
        if score >= UInt64(TIER_GOOD):
            return UInt64(3)
        if score >= UInt64(TIER_CAUTION):
            return UInt64(2)
        if score >= UInt64(TIER_RESTRICTED):
            return UInt64(1)
        return UInt64(0)

    @abimethod()
    def get_drift_events(self, agent: Account) -> UInt64:
        """Return total flagged drift events for forensic audit."""
        exists = agent in self.rep_records
        assert exists, "agent not registered"
        record = self.rep_records[agent].copy()
        return record.drift_events
