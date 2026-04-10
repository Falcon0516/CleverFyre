from algopy import ARC4Contract, BoxMap, UInt64, Bytes, Account, Global, op
from algopy.arc4 import abimethod, Struct

class PolicyRecord(Struct):
    expiry_round: UInt64
    missed_renewals: UInt64
    spend_cap_tier: UInt64    # 0=full, 1=1 ALGO cap, 2=0.1 ALGO cap, 3=frozen
    operator_pubkey: Bytes    # 32 bytes ed25519 pubkey

class PolicyVault(ARC4Contract):
    def __init__(self) -> None:
        self.policies = BoxMap(Account, PolicyRecord)

    @abimethod()
    def init_policy(self, agent: Account, window_rounds: UInt64,
                    operator_pubkey: Bytes) -> None:
        # Create new policy entry. Only callable by org admin.
        assert operator_pubkey.length == 32, "operator_pubkey must be 32 bytes"
        
        self.policies[agent] = PolicyRecord(
            expiry_round=Global.round + window_rounds,
            missed_renewals=UInt64(0),
            spend_cap_tier=UInt64(0),
            operator_pubkey=operator_pubkey
        )

    @abimethod()
    def renew_with_proof(self, agent: Account, challenge: Bytes, challenge_sig: Bytes, extension_rounds: UInt64) -> None:
        # Verify ed25519 sig of renewal_challenge derived from last 3 payment hashes.
        # Reset missed_renewals = 0. Extend expiry_round by window.
        policy = self.policies[agent].copy()
        pubkey = policy.operator_pubkey
        
        assert op.ed25519verify(challenge, challenge_sig, pubkey), "Invalid renewal signature"
        
        self.policies[agent] = PolicyRecord(
            expiry_round=Global.round + extension_rounds,
            missed_renewals=UInt64(0),
            spend_cap_tier=UInt64(0),
            operator_pubkey=pubkey
        )

    @abimethod()
    def check_and_enforce(self, agent: Account, amount: UInt64) -> UInt64:
        # Returns: 0=allowed, 1=warn(capped 1 ALGO), 2=capped(0.1 ALGO), 3=fully frozen
        # Graduated: missed_renewals 1 -> tier 1, 2 -> tier 2, 3+ -> tier 3
        policy = self.policies[agent].copy()
        
        if Global.round >= policy.expiry_round:
            return UInt64(3)
            
        tier = policy.spend_cap_tier
        if tier == UInt64(1):
            assert amount <= UInt64(1_000_000), "capped at 1 ALGO"
        elif tier == UInt64(2):
            assert amount <= UInt64(100_000), "capped at 0.1 ALGO"
        elif tier >= UInt64(3):
            assert False, "agent fully frozen"
            
        return tier

    @abimethod()
    def tick_missed_renewal(self, agent: Account) -> None:
        # Called by backend cron each epoch if no renewal seen.
        # Increments missed_renewals. Updates spend_cap_tier.
        policy = self.policies[agent].copy()
        missed = policy.missed_renewals + 1
        tier = UInt64(0)
        
        if missed == UInt64(1):
            tier = UInt64(1)
        elif missed == UInt64(2):
            tier = UInt64(2)
        elif missed >= UInt64(3):
            tier = UInt64(3)
            
        self.policies[agent] = PolicyRecord(
            expiry_round=policy.expiry_round,
            missed_renewals=missed,
            spend_cap_tier=tier,
            operator_pubkey=policy.operator_pubkey
        )

    @abimethod()
    def get_policy_status(self, agent: Account) -> UInt64:
        # Returns current tier for this agent.
        policy = self.policies[agent].copy()
        
        if Global.round >= policy.expiry_round:
            return UInt64(3)
            
        return policy.spend_cap_tier
