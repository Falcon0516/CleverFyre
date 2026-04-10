"""
AXIOM AgPP — Intent Document

Structured representation of an agent's payment intent.
Each payment is preceded by an IntentDocument that records WHY the
agent is making the payment — the task, the API, the reason, and
the policy commitment.

The intent hash becomes a Merkle leaf committed on Algorand.
The full document is stored on IPFS for later retrieval.

Fields:
    schema              — protocol version ("agpp/v1")
    agent_id            — deterministic Algorand address
    task_canonical      — the agent's stated goal
    api_url             — target API endpoint
    api_selection_reason — WHY this API was chosen
    expected_output_schema — expected response format
    policy_commitment   — hash of policy.yaml in effect
    timestamp_round     — Algorand round at time of intent
    chain_id            — parent intent ID if delegated

Usage:
    intent = IntentDocument(
        agent_id=address,
        task_canonical="Find weather data",
        api_url="https://api.weather.com/v1/forecast",
    )
    leaf_hash = intent.hash()
    note = intent.to_note()  # 32-byte Algorand transaction note
"""

import hashlib
import json
from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class IntentDocument:
    """
    AgPP Intent Document — records the justification for a payment.

    Every field is included in the hash, making the intent
    tamper-evident once committed on-chain.
    """

    schema: str = "agpp/v1"
    agent_id: str = ""
    task_canonical: str = ""
    api_url: str = ""
    api_selection_reason: str = ""
    expected_output_schema: dict = field(default_factory=dict)
    policy_commitment: str = ""
    timestamp_round: int = 0
    chain_id: Optional[str] = None  # parent intent if delegated

    def to_json(self) -> str:
        """
        Serialize to deterministic JSON string.

        Keys are sorted to ensure the same document always produces
        the same JSON string (and therefore the same hash).
        """
        return json.dumps(asdict(self), sort_keys=True)

    def hash(self) -> bytes:
        """
        Compute SHA-256 hash of the intent document.

        This hash becomes a Merkle leaf and is committed on-chain
        via IntentRegistry. It binds the payment to its justification.

        Returns:
            32-byte SHA-256 hash.
        """
        return hashlib.sha256(self.to_json().encode()).digest()

    def to_note(self) -> bytes:
        """
        Build an Algorand transaction note.

        Format: "x402:axiom:" prefix (11 bytes) + first 21 bytes of hash
        = 32 bytes total. This fits in Algorand's note field and allows
        filtering via Indexer note_prefix queries.

        Returns:
            32-byte note for Algorand transaction.
        """
        return b"x402:axiom:" + self.hash()[:21]

    def to_dict(self) -> dict:
        """Convert to dictionary (for JSON serialization)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "IntentDocument":
        """Create an IntentDocument from a dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, json_str: str) -> "IntentDocument":
        """Create an IntentDocument from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    def __repr__(self) -> str:
        hash_hex = self.hash().hex()[:12]
        return (
            f"IntentDocument(agent={self.agent_id[:8]}..., "
            f"api={self.api_url[:30]}..., hash={hash_hex}...)"
        )
