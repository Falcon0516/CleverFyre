import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def deploy() -> None:
    logger.info("IntentRegistry deploy_config.deploy() called — use deploy.py for full deploy")
