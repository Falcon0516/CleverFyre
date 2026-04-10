"""
AXIOM — One-command deploy script for all 6 smart contracts.

Usage:
    python smart_contracts/deploy.py               # default: localnet
    python smart_contracts/deploy.py localnet
    python smart_contracts/deploy.py testnet

After deploying, contract app IDs are written to .env at the repo root.
"""

from __future__ import annotations

import os
import sys
import json
import logging
from pathlib import Path

from algokit_utils import AlgorandClient
from dotenv import load_dotenv, set_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
log = logging.getLogger("axiom.deploy")

# Repo root is two levels up from this file (smart_contracts/deploy.py)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE  = REPO_ROOT / ".env"


def load_env() -> None:
    load_dotenv(ENV_FILE)
    load_dotenv()


def get_client(network: str) -> AlgorandClient:
    """Return an AlgorandClient configured for the target network."""
    if network == "testnet":
        return AlgorandClient.testnet()
    # default: localnet
    return AlgorandClient.default_localnet()


def deploy_all(network: str = "localnet") -> dict[str, int]:
    load_env()

    log.info(f"Deploying AXIOM contracts to {network.upper()}")

    client = get_client(network)

    mnemonic = os.environ.get("DEPLOYER_MNEMONIC", "")
    if not mnemonic:
        raise EnvironmentError(
            "DEPLOYER_MNEMONIC not set. "
            "Run: algokit localnet accounts   — then copy a mnemonic to .env"
        )

    deployer = client.account.from_mnemonic(mnemonic)
    log.info(f"Deployer address: {deployer.address}")

    ids: dict[str, int] = {}

    # ------------------------------------------------------------------ #
    # 1. PolicyVault
    # ------------------------------------------------------------------ #
    try:
        log.info("— Deploying PolicyVault …")
        from smart_contracts.artifacts.policy_vault.policy_vault_client import (
            PolicyVaultFactory,
        )
        factory = client.client.get_app_factory(
            PolicyVaultFactory, default_sender=deployer.address
        )
        app_client, _ = factory.deploy(
            on_schema_break="replace",
            on_update="update",
        )
        ids["POLICY_VAULT_ID"] = app_client.app_id
        log.info(f"  PolicyVault app_id = {app_client.app_id}")
    except Exception as exc:
        log.error(f"  PolicyVault deploy FAILED: {exc}")

    # ------------------------------------------------------------------ #
    # 2. IntentRegistry
    # ------------------------------------------------------------------ #
    try:
        log.info("— Deploying IntentRegistry …")
        from smart_contracts.artifacts.intent_registry.intent_registry_client import (
            IntentRegistryFactory,
        )
        factory = client.client.get_app_factory(
            IntentRegistryFactory, default_sender=deployer.address
        )
        app_client, _ = factory.deploy(
            on_schema_break="replace",
            on_update="update",
        )
        ids["INTENT_REGISTRY_ID"] = app_client.app_id
        log.info(f"  IntentRegistry app_id = {app_client.app_id}")
    except Exception as exc:
        log.error(f"  IntentRegistry deploy FAILED: {exc}")

    # ------------------------------------------------------------------ #
    # 3. SentinelEscrow  (needs PolicyVault app_id)
    # ------------------------------------------------------------------ #
    try:
        log.info("— Deploying SentinelEscrow …")
        from smart_contracts.artifacts.sentinel_escrow.sentinel_escrow_client import (
            SentinelEscrowFactory,
        )
        policy_vault_id = ids.get("POLICY_VAULT_ID", 0)
        factory = client.client.get_app_factory(
            SentinelEscrowFactory, default_sender=deployer.address
        )
        app_client, _ = factory.deploy(
            on_schema_break="replace",
            on_update="update",
            deploy_time_params={"policy_vault_app_id": policy_vault_id},
        )
        ids["SENTINEL_ESCROW_ID"] = app_client.app_id
        log.info(f"  SentinelEscrow app_id = {app_client.app_id}")
    except Exception as exc:
        log.error(f"  SentinelEscrow deploy FAILED: {exc}")

    # ------------------------------------------------------------------ #
    # 4. PaymentDNARegistry  (needs SentinelEscrow app_id)
    # ------------------------------------------------------------------ #
    try:
        log.info("— Deploying PaymentDNARegistry …")
        from smart_contracts.artifacts.payment_dna_registry.payment_dna_registry_client import (
            PaymentDnaRegistryFactory,
        )
        sentinel_id = ids.get("SENTINEL_ESCROW_ID", 0)
        factory = client.client.get_app_factory(
            PaymentDnaRegistryFactory, default_sender=deployer.address
        )
        app_client, _ = factory.deploy(
            on_schema_break="replace",
            on_update="update",
            deploy_time_params={"sentinel_escrow_app_id": sentinel_id},
        )
        ids["PAYMENT_DNA_REGISTRY_ID"] = app_client.app_id
        log.info(f"  PaymentDNARegistry app_id = {app_client.app_id}")
    except Exception as exc:
        log.error(f"  PaymentDNARegistry deploy FAILED: {exc}")

    # ------------------------------------------------------------------ #
    # 5. ConsensusVault  (needs SentinelEscrow app_id)
    # ------------------------------------------------------------------ #
    try:
        log.info("— Deploying ConsensusVault …")
        from smart_contracts.artifacts.consensus_vault.consensus_vault_client import (
            ConsensusVaultFactory,
        )
        sentinel_id = ids.get("SENTINEL_ESCROW_ID", 0)
        factory = client.client.get_app_factory(
            ConsensusVaultFactory, default_sender=deployer.address
        )
        app_client, _ = factory.deploy(
            on_schema_break="replace",
            on_update="update",
            deploy_time_params={"sentinel_escrow_app_id": sentinel_id},
        )
        ids["CONSENSUS_VAULT_ID"] = app_client.app_id
        log.info(f"  ConsensusVault app_id = {app_client.app_id}")
    except Exception as exc:
        log.error(f"  ConsensusVault deploy FAILED: {exc}")

    # ------------------------------------------------------------------ #
    # 6. ReputationLedger  (needs SentinelEscrow + PolicyVault app_ids)
    # ------------------------------------------------------------------ #
    try:
        log.info("— Deploying ReputationLedger …")
        from smart_contracts.artifacts.reputation_ledger.reputation_ledger_client import (
            ReputationLedgerFactory,
        )
        sentinel_id     = ids.get("SENTINEL_ESCROW_ID", 0)
        policy_vault_id = ids.get("POLICY_VAULT_ID", 0)
        factory = client.client.get_app_factory(
            ReputationLedgerFactory, default_sender=deployer.address
        )
        app_client, _ = factory.deploy(
            on_schema_break="replace",
            on_update="update",
            deploy_time_params={
                "sentinel_escrow_app_id": sentinel_id,
                "policy_vault_app_id":    policy_vault_id,
            },
        )
        ids["REPUTATION_LEDGER_ID"] = app_client.app_id
        log.info(f"  ReputationLedger app_id = {app_client.app_id}")
    except Exception as exc:
        log.error(f"  ReputationLedger deploy FAILED: {exc}")

    # ------------------------------------------------------------------ #
    # Write IDs to .env
    # ------------------------------------------------------------------ #
    ENV_FILE.touch(exist_ok=True)
    for key, val in ids.items():
        set_key(str(ENV_FILE), key, str(val))
        log.info(f"  Written to .env: {key}={val}")

    # Pretty summary
    width = 52
    print("\n" + "=" * width)
    print("  AXIOM CONTRACTS DEPLOYED".center(width))
    print(f"  Network: {network.upper()}".center(width))
    print("=" * width)
    for k, v in ids.items():
        label = k.replace("_ID", "").replace("_", " ").title()
        print(f"  {label:<28} {v}")
    print("=" * width + "\n")

    return ids


if __name__ == "__main__":
    net = sys.argv[1] if len(sys.argv) > 1 else "localnet"
    result = deploy_all(net)
    sys.exit(0 if result else 1)
