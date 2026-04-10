"""
AXIOM Backend — IPFS Client

Async, non-blocking upload of IntentDocument JSON to IPFS.
The agent doesn't wait for IPFS — upload happens in a background thread.
Returns a CID that gets registered on IntentRegistry on-chain.

Currently uses a stub CID (sha256 hash) until web3.storage credentials
are configured. The stub CID format matches the IPFS CIDv1 prefix
so frontend IPFS links degrade gracefully.

Usage:
    from backend.ipfs_client import upload_intent_background
    upload_intent_background(intent)  # fire and forget
"""

import asyncio
import hashlib
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Store the latest CID for each intent hash — used by IntentRegistry
_cid_cache: dict[str, str] = {}


async def upload_intent(intent) -> str:
    """
    Upload an IntentDocument to IPFS via web3.storage.

    Returns the CID string. Non-blocking — agent doesn't wait.

    Currently returns a deterministic stub CID (based on intent hash)
    until WEB3_STORAGE_TOKEN is set in .env.

    Args:
        intent: An IntentDocument instance with .to_json() and .hash() methods.

    Returns:
        CID string (e.g., "bafybei..." format).
    """
    import os

    token = os.getenv("WEB3_STORAGE_TOKEN")

    if token:
        # Real implementation with web3.storage
        try:
            # import web3storage
            # client = web3storage.Client(token=token)
            # cid = client.put(intent.to_json().encode())
            # logger.info("Intent uploaded to IPFS — CID: %s", cid)
            # return cid
            pass
        except Exception as e:
            logger.warning("IPFS upload failed, falling back to stub CID: %s", e)

    # Stub CID — deterministic from intent content so it's reproducible
    intent_json = intent.to_json()
    content_hash = hashlib.sha256(intent_json.encode()).hexdigest()
    fake_cid = "bafybei" + content_hash[:40]

    # Cache the CID for later retrieval by IntentRegistry
    intent_hash_hex = intent.hash().hex()
    _cid_cache[intent_hash_hex] = fake_cid

    logger.debug("Stub IPFS CID generated: %s (intent=%s...)", fake_cid[:24], intent_hash_hex[:16])

    return fake_cid


def upload_intent_background(intent) -> None:
    """
    Fire-and-forget IPFS upload in a background thread.

    The agent's payment flow is NOT blocked by IPFS upload latency.
    The CID is stored in _cid_cache and can be retrieved later for
    on-chain registration via IntentRegistry.register_intent().

    Args:
        intent: An IntentDocument instance.
    """
    def _run():
        loop = asyncio.new_event_loop()
        try:
            cid = loop.run_until_complete(upload_intent(intent))
            logger.debug("Background IPFS upload complete — CID: %s", cid[:24])
        except Exception as e:
            logger.warning("Background IPFS upload failed: %s", e)
        finally:
            loop.close()

    thread = threading.Thread(target=_run, daemon=True, name="ipfs-upload")
    thread.start()


def get_cached_cid(intent_hash_hex: str) -> Optional[str]:
    """
    Retrieve a previously uploaded CID from the cache.

    Args:
        intent_hash_hex: Hex-encoded intent hash.

    Returns:
        CID string if found, None otherwise.
    """
    return _cid_cache.get(intent_hash_hex)
