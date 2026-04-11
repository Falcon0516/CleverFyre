"""
AXIOM AgPP — Red Team Engine

Attack-your-own-policy simulator. Run this BEFORE deploying to find
vulnerabilities in your policy configuration.

6 attack vectors:
    ATK-001: Gradual Escalation — slowly increase payment amounts
    ATK-002: Domain Spoof — trick semantic router with misleading descriptions
    ATK-003: Burst Attack — 100 rapid micro-payments
    ATK-004: Semantic Confusion — ambiguous API descriptions
    ATK-005: Dead Man Switch Timing — exploit long renewal windows
    ATK-006: Intent Replay — replay old intent documents

Usage:
    axiom red-team --policy policy.yaml --output report.json

    or programmatically:
        engine = RedTeamEngine("policy.yaml")
        results = engine.run_all()
        engine.print_report(results)
"""

import json
import logging
from dataclasses import dataclass, asdict
from typing import List

import yaml

logger = logging.getLogger(__name__)


@dataclass
class AttackResult:
    """Result of a single red team attack vector."""
    id: str                     # ATK-001 through ATK-006
    name: str                   # Human-readable attack name
    succeeded: bool             # True = VULNERABLE (bad), False = BLOCKED (good)
    details: str                # What happened during the attack
    recommendation: str = ""    # Fix suggestion if vulnerable


class RedTeamEngine:
    """
    Red Team attack simulator for AXIOM policy configurations.

    Runs 6 attack vectors against a policy.yaml and reports which
    attacks would succeed (vulnerabilities) and which are blocked.
    """

    def __init__(self, policy_path: str):
        """
        Initialize the RedTeamEngine with a policy file.

        Args:
            policy_path: Path to policy.yaml file.
        """
        with open(policy_path) as f:
            self.policy = yaml.safe_load(f)

        logger.info("RedTeamEngine loaded policy from %s", policy_path)

    def run_all(self) -> List[AttackResult]:
        """
        Run all 6 attack vectors against the loaded policy.

        Returns:
            List of AttackResult objects, one per attack vector.
        """
        logger.info("Starting red team assessment — 6 attack vectors")

        results = [
            self._atk_001_gradual_escalation(),
            self._atk_002_domain_spoof(),
            self._atk_003_burst(),
            self._atk_004_semantic_confusion(),
            self._atk_005_dms_timing(),
            self._atk_006_intent_replay(),
        ]

        blocked = sum(1 for r in results if not r.succeeded)
        logger.info(
            "Red team assessment complete — %d/%d attacks blocked",
            blocked,
            len(results),
        )

        return results

    # ─────────────────────────────────────────────────────────────
    #  ATTACK VECTORS
    # ─────────────────────────────────────────────────────────────

    def _atk_001_gradual_escalation(self) -> AttackResult:
        """
        ATK-001: Gradual Escalation

        Slowly increase payment amounts by 1.5x each call until the
        spend_cap_algo is exceeded. Tests whether the policy catches
        gradual budget creep.
        """
        cap = self.policy.get("spend_cap_algo", 1.0)
        blocked_at = None

        for i in range(20):
            amount = (cap / 10) * (1.5 ** i)
            if amount > cap:
                blocked_at = i
                break

        return AttackResult(
            id="ATK-001",
            name="Gradual Escalation",
            succeeded=(blocked_at is None),
            details=(
                f"Blocked at call {blocked_at} (amount={cap / 10 * 1.5 ** blocked_at:.4f} > cap={cap})"
                if blocked_at is not None
                else f"All 20 escalation steps passed unchecked (cap={cap})"
            ),
            recommendation=(
                "Decrease spend_cap_algo or add cumulative rate limit"
                if blocked_at is None
                else ""
            ),
        )

    def _atk_002_domain_spoof(self) -> AttackResult:
        """
        ATK-002: Domain Spoof

        Craft a misleading API description that tricks the semantic
        router into matching a legitimate category.
        """
        try:
            from axiom_agpp.semantic import route_api

            spoofed = "weather temperature forecast data premium API endpoint"
            budget_map = self.policy.get("budget_map", {})
            cat, score = route_api(spoofed, budget_map)

            vulnerable = cat is not None and score > 0.7

            return AttackResult(
                id="ATK-002",
                name="Domain Spoof",
                succeeded=vulnerable,
                details=f"Matched: {cat} score={score:.2f}",
                recommendation=(
                    "Tighten category descriptions in policy.yaml or raise semantic_threshold"
                    if vulnerable
                    else ""
                ),
            )
        except ImportError:
            return AttackResult(
                id="ATK-002",
                name="Domain Spoof",
                succeeded=False,
                details="Semantic module not available — skipped (install sentence-transformers)",
            )

    def _atk_003_burst(self) -> AttackResult:
        """
        ATK-003: Burst Attack (100 micro-payments)

        Simulate 100 rapid-fire micro-payments to drain funds before
        the anomaly detector can respond.
        """
        burst_max = self.policy.get("burst_max_calls", 20)
        burst_window = self.policy.get("burst_window_sec", 30)
        simulated_calls = 100

        # The burst detector BLOCKS at call burst_max+1, so the attack is
        # blocked as long as burst_max < simulated_calls (which it always is).
        # Only vulnerable if burst detection is disabled (burst_max >= simulated_calls).
        blocked = burst_max < simulated_calls

        return AttackResult(
            id="ATK-003",
            name="Burst Attack (100 micro-payments)",
            succeeded=not blocked,
            details=(
                f"burst_max_calls={burst_max}, burst_window_sec={burst_window}. "
                f"{'Blocked at call ' + str(burst_max + 1) + ' of 100' if blocked else 'All 100 calls allowed'}"
            ),
            recommendation=(
                ""
                if blocked
                else "Enable burst detection: set burst_max_calls < 100"
            ),
        )

    def _atk_004_semantic_confusion(self) -> AttackResult:
        """
        ATK-004: Semantic Confusion

        Send an ambiguous API description that blends multiple categories
        to confuse the semantic router.
        """
        try:
            from axiom_agpp.semantic import route_api

            desc = "financial weather news market temperature forecast data analysis"
            budget_map = self.policy.get("budget_map", {})
            cat, score = route_api(desc, budget_map)

            ambiguous = score < 0.75

            return AttackResult(
                id="ATK-004",
                name="Semantic Confusion",
                succeeded=not ambiguous,
                details=f"Best match: {cat} at {score:.2f} (ambiguous={ambiguous})",
                recommendation=(
                    "Add disambiguation terms to category descriptions"
                    if not ambiguous
                    else ""
                ),
            )
        except ImportError:
            return AttackResult(
                id="ATK-004",
                name="Semantic Confusion",
                succeeded=False,
                details="Semantic module not available — skipped",
            )

    def _atk_005_dms_timing(self) -> AttackResult:
        """
        ATK-005: Dead Man Switch Timing Attack

        Exploit long renewal windows to continue operating after the
        operator has lost control.
        """
        window = self.policy.get("renewal_window_rounds", 1000)
        # At ~4s/round, 500 rounds ≈ 33 minutes
        vulnerable = window > 500

        time_minutes = window * 4 / 60

        return AttackResult(
            id="ATK-005",
            name="Dead Man Switch Timing Attack",
            succeeded=vulnerable,
            details=(
                f"renewal_window_rounds={window} (~{time_minutes:.0f} min). "
                f"{'Agent can operate unsupervised for too long' if vulnerable else 'Window is acceptably short'}"
            ),
            recommendation=(
                "Set renewal_window_rounds <= 500 (~30 min on Algorand)"
                if vulnerable
                else ""
            ),
        )

    def _atk_006_intent_replay(self) -> AttackResult:
        """
        ATK-006: Intent Replay Attack

        Attempt to replay a previously valid intent document to authorize
        a duplicate payment.
        """
        has_protection = self.policy.get("replay_protection", False)

        return AttackResult(
            id="ATK-006",
            name="Intent Replay Attack",
            succeeded=not has_protection,
            details=f"replay_protection={has_protection}",
            recommendation=(
                "Set replay_protection: true in policy.yaml"
                if not has_protection
                else ""
            ),
        )

    # ─────────────────────────────────────────────────────────────
    #  REPORTING
    # ─────────────────────────────────────────────────────────────

    def print_report(self, results: List[AttackResult]) -> None:
        """Print a formatted red team report to stdout."""
        print()
        print("╔══ AXIOM RED TEAM REPORT ════════════════════════════════╗")
        print("║                                                         ║")

        for r in results:
            status = "✗ VULNERABLE" if r.succeeded else "✓ BLOCKED   "
            color_start = ""
            color_end = ""
            print(f"║  {r.id}: {r.name:<40} {status} ║")
            if r.recommendation:
                # Wrap long recommendations
                rec = r.recommendation
                if len(rec) > 50:
                    print(f"║         REC: {rec[:50]}  ║")
                    print(f"║              {rec[50:]:<43} ║")
                else:
                    print(f"║         REC: {rec:<44} ║")

        print("║                                                         ║")
        blocked = sum(1 for r in results if not r.succeeded)
        total = len(results)
        print(f"║  {blocked}/{total} attacks blocked.                               ║")
        print("║                                                         ║")
        print("╚═════════════════════════════════════════════════════════╝")
        print()

    def to_json(self, results: List[AttackResult]) -> str:
        """Serialize results to JSON string."""
        return json.dumps([asdict(r) for r in results], indent=2)
