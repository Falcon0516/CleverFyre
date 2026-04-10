import logging
import os
from algokit_utils import AlgorandClient
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def deploy() -> None:
    """Stub deploy for PolicyVault — real deploy handled by smart_contracts/deploy.py."""
    logger.info("PolicyVault deploy_config.deploy() called — use deploy.py for full deploy")
