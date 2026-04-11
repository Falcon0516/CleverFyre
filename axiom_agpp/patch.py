import logging
from typing import Any

import requests
from axiom_agpp.wrapper import AXIOMWrapper

logger = logging.getLogger(__name__)

# Save the original method to avoid infinite recursion
_original_requests_session_request = requests.Session.request


def patch_http(wrapper: AXIOMWrapper) -> None:
    """
    Monkey-patch standard HTTP libraries (e.g. requests) and route outbound 
    agent traffic through the AXIOM Agentic Payment Protocol automatically.
    
    This fulfills the "5-Line Integration" claim, enabling black-box agents
    like LangChain, CrewAI, and AutoGen to natively understand and pay 
    crypto-native APIs (HTTP 402) without changing the agent's underlying network code.
    """
    
    # Mark the wrapper's internal session so we don't intercept its own requests
    wrapper.session._is_axiom_internal = True

    def _axiom_patched_request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """
        Intercepted request. If it originates from the wrapper itself 
        (e.g., executing the actual payment call), we route natively. 
        Otherwise, we proxy through the AXIOM Wrapper to handle 402s and SLAs.
        """
        if getattr(self, "_is_axiom_internal", False):
            # This is AXIOM communicating with the network internally. Let it pass.
            return _original_requests_session_request(self, method, url, **kwargs)

        logger.info("AXIOM-Patch intercepted outbound %s request to %s", method, url)
        
        # Transparently pipe the black-box agent's request through AXIOM protocol.
        # AXIOMWrapper.call() handles 402s, escrow, anomaly detection, and routing.
        return wrapper.call(url, method=method, **kwargs)

    # Apply the monkey patch globally to requests.Session
    # (Since requests.get() uses Session() internally, this catches everything)
    requests.Session.request = _axiom_patched_request
    logger.info("AXIOM SDK successfully monkey-patched 'requests' library.")


def unpatch_http() -> None:
    """Remove the AXIOM HTTP interception."""
    requests.Session.request = _original_requests_session_request
    logger.info("AXIOM SDK monkey-patch removed.")
