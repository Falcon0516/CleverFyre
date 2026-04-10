"""
AXIOM AgPP — Custom Exception Types
Used across all SDK modules to signal specific protocol violations.
"""


class PolicyExpiredError(Exception):
    """Raised when an agent's Dead Man's Switch policy has fully expired (tier 3 frozen)."""
    pass


class AnomalyDetectedError(Exception):
    """Raised when the anomaly detector flags suspicious payment behavior."""
    pass


class ConsensusTimeoutError(Exception):
    """Raised when M-of-N peer consensus is not reached before the deadline round."""
    pass


class IntentRejectedError(Exception):
    """Raised when an intent document fails validation or policy checks."""
    pass


class ReputationBlacklistedError(Exception):
    """Raised when an agent's reputation score falls below 200 (tier 0 blacklisted)."""
    pass


class SLAFailedError(Exception):
    """Raised when the SLA oracle determines the API response failed quality checks."""
    pass


class MissionDriftError(Exception):
    """Raised when Wasserstein distance on category distribution exceeds threshold."""
    pass


class SemanticMismatchError(Exception):
    """Raised when semantic routing cannot match the API to an allowed budget category."""
    pass
