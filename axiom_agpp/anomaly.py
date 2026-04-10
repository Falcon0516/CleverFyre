"""
AXIOM AgPP — Anomaly Detector

Real-time anomaly detection using Isolation Forest and burst rate checking.
Monitors AI agent payment patterns for statistical outliers and rapid-fire
micro-payment attacks.

Two detection modes:
    1. Statistical anomaly — IsolationForest trained on rolling window of
       payment features. Detects behavioral deviations that don't match
       the agent's established pattern.
    2. Burst detection — Simple rate limiter checking if the agent exceeds
       max_calls within a time window. Prevents micro-payment flooding.

Usage:
    detector = AnomalyDetector(window=50)
    detector.record([amount, calls_per_hour, entropy, ...])
    if detector.is_anomaly([new_features]) or detector.burst_check():
        quarantine_payment()
"""

import logging
import time
from collections import deque
from typing import Optional

import numpy as np
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """
    Real-time anomaly detection for AI agent payment behavior.

    Maintains a rolling window of payment feature vectors and trains
    an IsolationForest model incrementally. Also tracks timestamps
    for burst rate detection.
    """

    # Minimum samples needed before the model can detect anomalies
    MIN_SAMPLES = 10

    # IsolationForest contamination parameter — expected anomaly rate
    CONTAMINATION = 0.1

    def __init__(self, window: int = 50):
        """
        Initialize the anomaly detector.

        Args:
            window: Size of the rolling window for feature history.
                    Larger windows give more stable detection but slower
                    adaptation to legitimate behavior changes.
        """
        self.window = window
        self.history: deque = deque(maxlen=window)
        self.timestamps: deque = deque(maxlen=200)
        self.model: Optional[IsolationForest] = None
        self._anomaly_count = 0
        self._total_checks = 0

    def record(self, features: list) -> None:
        """
        Record a payment observation and retrain the model.

        The model is retrained on every call once MIN_SAMPLES are collected.
        This is fast enough for real-time use since IsolationForest training
        on 50 samples with low-dim features takes <1ms.

        Args:
            features: List of numeric features describing this payment.
                      Typically: [amount, calls_per_hour, entropy, sla_ratio, ...]
        """
        self.history.append(features)
        self.timestamps.append(time.time())

        # Retrain the model when we have enough samples
        if len(self.history) >= self.MIN_SAMPLES:
            X = np.array(list(self.history))
            self.model = IsolationForest(
                contamination=self.CONTAMINATION,
                random_state=42,
                n_estimators=100,
            )
            self.model.fit(X)
            logger.debug(
                "Anomaly model retrained on %d samples", len(self.history)
            )

    def is_anomaly(self, features: list) -> bool:
        """
        Check if a payment feature vector is anomalous.

        Returns False if the model hasn't been trained yet (insufficient data).
        This is intentional — we don't block payments before establishing
        a behavioral baseline.

        Args:
            features: List of numeric features for the payment to check.

        Returns:
            True if the model classifies this as an anomaly (-1),
            False otherwise (1 = normal, or model not ready).
        """
        self._total_checks += 1

        if self.model is None:
            return False

        prediction = self.model.predict([features])[0]
        is_anom = prediction == -1

        if is_anom:
            self._anomaly_count += 1
            logger.warning(
                "ANOMALY DETECTED — features=%s (anomaly #%d of %d checks)",
                [round(f, 4) for f in features[:5]],
                self._anomaly_count,
                self._total_checks,
            )

        return is_anom

    def burst_check(
        self, window_sec: float = 30.0, max_calls: int = 20
    ) -> bool:
        """
        Check if the agent is making too many calls in a short time window.

        This is a simple rate limiter to prevent micro-payment flooding
        attacks where an agent makes many small payments rapidly to
        drain funds before the anomaly detector can respond.

        Args:
            window_sec: Time window in seconds to check. Default 30s.
            max_calls:  Maximum allowed calls within the window. Default 20.

        Returns:
            True if the burst rate exceeds the threshold (BLOCK this payment).
        """
        now = time.time()
        recent = sum(1 for t in self.timestamps if now - t < window_sec)
        is_burst = recent > max_calls

        if is_burst:
            logger.warning(
                "BURST DETECTED — %d calls in %.0fs (max=%d)",
                recent,
                window_sec,
                max_calls,
            )

        return is_burst

    def get_anomaly_score(self, features: list) -> float:
        """
        Get the raw anomaly score for a feature vector.

        Lower (more negative) scores indicate more anomalous behavior.
        Useful for gradual responses rather than binary anomaly detection.

        Args:
            features: List of numeric features.

        Returns:
            Anomaly score (float). More negative = more anomalous.
            Returns 0.0 if model is not trained yet.
        """
        if self.model is None:
            return 0.0
        return float(self.model.score_samples([features])[0])

    def get_stats(self) -> dict:
        """Return detector statistics for monitoring."""
        return {
            "total_checks": self._total_checks,
            "anomalies_detected": self._anomaly_count,
            "anomaly_rate": (
                self._anomaly_count / max(self._total_checks, 1)
            ),
            "history_size": len(self.history),
            "model_trained": self.model is not None,
            "recent_timestamps": len(self.timestamps),
        }
