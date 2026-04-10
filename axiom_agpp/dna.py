"""
AXIOM AgPP — Behavioral DNA (Payment Fingerprint)

32-dimensional behavioral fingerprint for each AI agent, stored as
int8[32] in the PaymentDNARegistry contract's box storage.

Each dimension captures a different aspect of the agent's payment behavior:
    d[0]    — log-normalized payment amount
    d[1]    — EMA of calls per hour
    d[2]    — Shannon entropy of API domains
    d[3]    — SLA pass ratio
    d[4]    — refund ratio
    d[5]    — reserved
    d[6:32] — 26 API category distribution buckets

Drift detection uses cosine distance between the stored DNA vector and
a new observation vector. A drift score > 0.3 triggers an anomaly check.

Mission drift uses Wasserstein distance on category distributions.
A mission drift score > 0.4 triggers a mission drift alert.

Usage:
    dna = BehavioralDNA()
    dna.update({"amount": 0.5, "calls_per_hour": 10, ...})
    drift = dna.drift_score(new_observation_vector)
    if drift > 0.3:
        raise AnomalyDetectedError("DNA drift detected")
"""

import logging
from collections import Counter
from typing import Optional

import numpy as np
from scipy.spatial.distance import cosine
from scipy.stats import wasserstein_distance

logger = logging.getLogger(__name__)


class BehavioralDNA:
    """
    32-dimensional behavioral fingerprint for an AI agent.

    The vector is quantized to int8 for on-chain storage (32 bytes total).
    All values are normalized to [-1, 1] range before quantization.
    """

    DIMENSIONS = 32
    DRIFT_THRESHOLD = 0.30       # cosine distance — triggers anomaly check
    MISSION_DRIFT_THRESHOLD = 0.40  # wasserstein distance — triggers alert
    EMA_ALPHA = 0.1              # exponential moving average smoothing factor

    def __init__(self, vector: Optional[np.ndarray] = None):
        """
        Initialize a BehavioralDNA instance.

        Args:
            vector: Optional 32-dim numpy array. Defaults to zero vector
                    (new agent with no payment history).
        """
        if vector is not None:
            self.vector = vector.copy()
        else:
            self.vector = np.zeros(self.DIMENSIONS)

        self._payment_count = 0
        self._sla_passes = 0
        self._refunds = 0

    def update(self, observation: dict) -> None:
        """
        Update the DNA vector with a new payment observation.

        Uses exponential moving average (EMA) to blend new observations
        into the existing fingerprint, giving more weight to recent behavior
        while preserving historical patterns.

        Args:
            observation: Dict with payment behavioral features:
                amount          (float)  — payment amount in ALGO
                calls_per_hour  (float)  — current call rate
                api_domains     (list[str]) — domains called in this session
                sla_passed      (bool)   — whether SLA check passed
                refunded        (bool)   — whether payment was refunded
                category_counts (dict)   — {category: count} for 26 buckets
        """
        self._payment_count += 1

        # d[0]: Log-normalized payment amount (0-1 range mapped to [-1, 1])
        amount = observation.get("amount", 0)
        self.vector[0] = np.clip(np.log1p(amount) / 10, -1, 1)

        # d[1]: Exponential moving average of calls per hour
        calls = observation.get("calls_per_hour", 0)
        self.vector[1] = (
            self.EMA_ALPHA * calls + (1 - self.EMA_ALPHA) * self.vector[1]
        )

        # d[2]: Shannon entropy of API domain distribution
        domains = observation.get("api_domains", [])
        if domains:
            counts = np.array(list(Counter(domains).values()), dtype=float)
            probs = counts / counts.sum()
            entropy = float(-np.sum(probs * np.log2(probs + 1e-10)))
            max_entropy = np.log2(len(probs) + 1)
            self.vector[2] = entropy / max_entropy if max_entropy > 0 else 0

        # d[3]: SLA pass ratio (cumulative)
        if observation.get("sla_passed", False):
            self._sla_passes += 1
        self.vector[3] = self._sla_passes / max(self._payment_count, 1)

        # d[4]: Refund ratio (cumulative)
        if observation.get("refunded", False):
            self._refunds += 1
        self.vector[4] = self._refunds / max(self._payment_count, 1)

        # d[5]: Reserved for future use
        # self.vector[5] = 0

        # d[6:32]: 26 API category distribution buckets
        cat = observation.get("category_counts", {})
        total = sum(cat.values()) or 1
        for i, (_, v) in enumerate(list(cat.items())[:26]):
            self.vector[6 + i] = v / total

        # Clamp all values to [-1, 1]
        self.vector = np.clip(self.vector, -1, 1)

        logger.debug(
            "DNA updated — payment #%d, amount=%.4f, drift_self=%.4f",
            self._payment_count,
            amount,
            self.drift_score(self.vector),
        )

    def drift_score(self, observation_vec: np.ndarray) -> float:
        """
        Compute cosine distance between stored DNA and a new observation.

        Range: 0.0 (identical) to 1.0 (completely different).
        Threshold: > 0.3 triggers anomaly check in the AXIOM pipeline.

        Args:
            observation_vec: 32-dim numpy array representing the new observation.

        Returns:
            Cosine distance as float (0-1).
        """
        if np.all(self.vector == 0):
            return 0.0  # No baseline yet — can't detect drift
        if np.all(observation_vec == 0):
            return 0.0

        return float(cosine(self.vector, observation_vec))

    def mission_drift_score(self, expected: dict, actual: dict) -> float:
        """
        Compute Wasserstein distance between expected and actual
        API category distributions.

        Range: 0.0 (perfect match) to ~1.0 (completely different).
        Threshold: > 0.4 triggers mission drift alert.

        Args:
            expected: Dict of {category: weight} for expected distribution.
            actual:   Dict of {category: weight} for actual distribution.

        Returns:
            Wasserstein distance as float.
        """
        cats = sorted(set(list(expected.keys()) + list(actual.keys())))
        if not cats:
            return 0.0

        # Use category indices as "positions" and distribution values
        # as weights for Wasserstein distance (earth mover's distance).
        # This correctly measures how much "mass" must be moved between
        # the expected and actual distributions.
        positions = np.arange(len(cats), dtype=float)

        e_weights = np.array([expected.get(c, 0) for c in cats], dtype=float)
        a_weights = np.array([actual.get(c, 0) for c in cats], dtype=float)

        e_sum = e_weights.sum()
        a_sum = a_weights.sum()
        e_weights = e_weights / e_sum if e_sum > 0 else e_weights
        a_weights = a_weights / a_sum if a_sum > 0 else a_weights

        return float(wasserstein_distance(
            positions, positions,
            u_weights=e_weights, v_weights=a_weights,
        ))

    def to_bytes(self) -> bytes:
        """
        Quantize the DNA vector to int8 and serialize to 32 bytes.

        This is the format stored in PaymentDNARegistry box storage.
        Values are scaled from [-1, 1] float to [-127, 127] int8.
        """
        return (self.vector * 127).astype(np.int8).tobytes()

    @classmethod
    def from_bytes(cls, b: bytes) -> "BehavioralDNA":
        """
        Deserialize a 32-byte int8 vector back to a BehavioralDNA instance.

        Args:
            b: 32 bytes representing a quantized DNA vector.

        Returns:
            BehavioralDNA instance with the deserialized vector.
        """
        vec = np.frombuffer(b, dtype=np.int8).astype(float) / 127.0
        return cls(vec)

    def __repr__(self) -> str:
        nonzero = int(np.count_nonzero(self.vector))
        norm = float(np.linalg.norm(self.vector))
        return f"BehavioralDNA(nonzero={nonzero}/32, norm={norm:.4f})"
