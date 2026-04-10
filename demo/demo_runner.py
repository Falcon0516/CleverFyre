"""
AXIOM Demo Runner — Scripted 5-minute demo agent.

Triggers every visual feature in the frontend:
    1. Normal payments (weather, financial, news APIs)
    2. Burst attack (6 rapid calls → anomaly detection)
    3. High-value payment (triggers M-of-N consensus)
    4. Semantic mismatch (unrecognized API → blocked)

Run:
    python demo/demo_runner.py

Watch the frontend at http://localhost:5173 while running.
"""

import os
import sys
import time

# Ensure axiom_agpp is importable from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from axiom_agpp.wrapper import AXIOMWrapper


DEMO_STEPS = [
    # (description, url, mode)
    (
        "Normal payment — weather API",
        "https://api.openweathermap.org/data/2.5/weather?q=London",
        "normal",
    ),
    (
        "Normal payment — financial data",
        "https://financialmodelingprep.com/api/v3/quote/AAPL",
        "normal",
    ),
    (
        "Normal payment — news API",
        "https://newsapi.org/v2/top-headlines?country=us",
        "normal",
    ),
    (
        "BURST ATTACK — 6 rapid calls to trigger anomaly",
        "https://api.openweathermap.org/data/2.5/weather?q=Paris",
        "burst",
    ),
    (
        "High-value compute API — triggers M-of-N consensus",
        "https://api.openai.com/v1/completions",
        "normal",
    ),
    (
        "Semantic mismatch — unrecognized API category",
        "https://unknown-niche-api.io/v1/obscure-endpoint",
        "normal",
    ),
]


def run_demo():
    """Execute the scripted demo sequence."""
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║                AXIOM DEMO RUNNER                        ║")
    print("║  Triggers all AXIOM visual features for the frontend    ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    wrapper = AXIOMWrapper(
        org_id="acme-corp",
        agent_role="market-researcher",
        task_goal="Gather Q3 2026 semiconductor supply chain disruption data",
        org_secret=b"hackathon-secret-2026",
    )

    print(f"  Agent address: {wrapper.address}")
    print(f"  Task goal:     {wrapper.task_goal}")
    print()
    print("─" * 58)

    for i, (desc, url, mode) in enumerate(DEMO_STEPS):
        step_num = i + 1
        print(f"\n  [Step {step_num}/{len(DEMO_STEPS)}] {desc}")
        print(f"  URL: {url}")

        if mode == "burst":
            # Burst attack: 6 rapid-fire calls
            for j in range(6):
                try:
                    wrapper.call(url)
                    print(f"    Call {j + 1}: ✓ sent")
                except Exception as e:
                    print(f"    Call {j + 1}: ✗ BLOCKED — {e}")
                time.sleep(0.3)
        else:
            # Normal single call
            try:
                r = wrapper.call(url)
                print(f"    Response: {r.status_code}")
            except Exception as e:
                print(f"    BLOCKED/FAILED: {e}")

        # Pause between steps so the frontend can animate
        if step_num < len(DEMO_STEPS):
            print("    Waiting 3s for frontend animation...")
            time.sleep(3)

    print()
    print("─" * 58)
    print()
    print("  Demo complete!")
    print("  Check the frontend for live graph updates.")
    print("  Drag the Temporal Scrubber to replay the demo.")
    print()


if __name__ == "__main__":
    run_demo()
