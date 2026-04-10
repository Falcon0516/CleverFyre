"""
AXIOM AgPP — Command Line Interface

CLI commands for managing AXIOM agent identities, deploying contracts,
checking reputation, running red team attacks, and auditing history.

Commands:
    axiom init       — Derive and display agent address
    axiom deploy     — Deploy all 6 AXIOM contracts
    axiom status     — Show agent reputation score and tier
    axiom red-team   — Run attack simulator against a policy
    axiom audit      — Reconstruct agent history at a given round

Usage:
    pip install -e .
    axiom --help
    axiom init --org acme-corp --role market-researcher
    axiom red-team --policy policy.yaml --output report.json
"""

import json
import os
import subprocess
import sys

import click


@click.group()
def cli():
    """AXIOM — Agentic Payment Protocol CLI"""
    pass


# ─────────────────────────────────────────────────────────────────
#  INIT — Derive agent address
# ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--org", required=True, help="Organization ID (e.g. acme-corp)")
@click.option("--role", required=True, help="Agent role (e.g. market-researcher)")
@click.option("--code", default=None, help="Path to agent code (default: this file)")
def init(org, role, code):
    """Derive and display agent address for an org/role pair."""
    from axiom_agpp.identity import derive_agent_address

    secret = os.environ.get("ORG_SECRET", "dev-secret").encode()
    code_path = code or __file__

    _, address = derive_agent_address(secret, org, role, code_path)

    click.echo()
    click.echo("═══════════════════════════════════════════════")
    click.echo("  AXIOM Agent Identity Derived")
    click.echo("═══════════════════════════════════════════════")
    click.echo(f"  Org:     {org}")
    click.echo(f"  Role:    {role}")
    click.echo(f"  Code:    {code_path}")
    click.echo(f"  Address: {address}")
    click.echo("═══════════════════════════════════════════════")
    click.echo()
    click.echo("Add this address to your policy.yaml allowed_agents list.")


# ─────────────────────────────────────────────────────────────────
#  DEPLOY — Deploy all contracts
# ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option(
    "--network",
    default="localnet",
    type=click.Choice(["localnet", "testnet"]),
    help="Target network (localnet or testnet)",
)
def deploy(network):
    """Deploy all 6 AXIOM contracts to Algorand."""
    click.echo(f"\nDeploying AXIOM contracts to {network}...\n")

    result = subprocess.run(
        [sys.executable, "smart_contracts/deploy.py", network],
        capture_output=False,
    )

    if result.returncode != 0:
        click.echo("Deploy failed. Check:")
        click.echo("  - algokit localnet status")
        click.echo("  - .env has DEPLOYER_MNEMONIC set")
        click.echo("  - Contracts compile: algokit compile python <contract.py>")
    else:
        click.echo("\nDeploy complete. Contract IDs written to .env")


# ─────────────────────────────────────────────────────────────────
#  STATUS — Show agent reputation
# ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--agent-addr", required=True, help="Algorand address of agent")
def status(agent_addr):
    """Show agent reputation score, tier, and policy status."""
    from axiom_agpp.reputation_client import ReputationClient, TIER_NAMES

    rc = ReputationClient()
    score = rc.get_score(agent_addr)
    tier = rc.get_tier(agent_addr)
    tier_name = TIER_NAMES.get(tier, "UNKNOWN")
    max_pay = rc.get_max_payment(agent_addr)

    click.echo()
    click.echo("═══════════════════════════════════════════════")
    click.echo("  AXIOM Agent Status")
    click.echo("═══════════════════════════════════════════════")
    click.echo(f"  Address:     {agent_addr}")
    click.echo(f"  Score:       {score}/1000")
    click.echo(f"  Tier:        {tier} — {tier_name}")
    click.echo(f"  Max Payment: {max_pay} ALGO per call")
    click.echo("═══════════════════════════════════════════════")
    click.echo()


# ─────────────────────────────────────────────────────────────────
#  RED-TEAM — Attack simulator
# ─────────────────────────────────────────────────────────────────

@cli.command("red-team")
@click.option("--policy", required=True, help="Path to policy.yaml")
@click.option("--output", default="report.json", help="Output JSON report file")
def red_team(policy, output):
    """Run red team attack simulator against a policy configuration."""
    from axiom_agpp.red_team import RedTeamEngine

    click.echo(f"\nLoading policy from {policy}...")
    engine = RedTeamEngine(policy)

    click.echo("Running 6 attack vectors...\n")
    results = engine.run_all()

    # Print formatted report
    engine.print_report(results)

    # Save JSON report
    with open(output, "w") as f:
        json.dump([vars(r) for r in results], f, indent=2)

    click.echo(f"Full report saved to: {output}")


# ─────────────────────────────────────────────────────────────────
#  AUDIT — Temporal reconstruction
# ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--agent-addr", required=True, help="Algorand address to audit")
@click.option("--from-round", required=True, type=int, help="Algorand round number")
def audit(agent_addr, from_round):
    """Reconstruct agent history from Algorand Indexer at a given round."""
    from axiom_agpp.temporal import TemporalQuery

    click.echo(f"\nReconstructing state at round {from_round:,}...")

    tq = TemporalQuery()
    snap = tq.reconstruct_at(from_round)

    agent = snap.agents.get(agent_addr)

    click.echo()
    click.echo("═══════════════════════════════════════════════")
    click.echo("  AXIOM Temporal Audit")
    click.echo(f"  Round: {from_round:,}")
    click.echo("═══════════════════════════════════════════════")

    if agent:
        click.echo(f"  Agent:    {agent_addr}")
        click.echo(f"  Score:    {agent.reputation_score}/1000")
        click.echo(f"  Tier:     {agent.tier}")
        click.echo(f"  Payments: {agent.payments_made} made, "
                   f"{agent.payments_blocked} blocked")
        click.echo(f"  Status:   {agent.policy_status}")
        click.echo(f"  Drift:    {agent.dna_drift:.4f}")
    else:
        click.echo(f"  No AXIOM history found for {agent_addr}")
        click.echo(f"  at round {from_round:,}.")

    # Show recent events for this agent
    agent_events = [e for e in snap.events if e.get("sender") == agent_addr]
    if agent_events:
        click.echo(f"\n  Recent events ({len(agent_events)} total):")
        for ev in agent_events[-10:]:
            click.echo(
                f"    [{ev['type']:>10}] round={ev['round']:,} "
                f"amount={ev.get('amount', 0)} tx={ev.get('tx_id', '')[:12]}..."
            )

    click.echo("═══════════════════════════════════════════════")
    click.echo()


if __name__ == "__main__":
    cli()
