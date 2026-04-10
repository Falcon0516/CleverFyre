"""
AXIOM AgPP — Agentic Payment Protocol SDK
Reference implementation of the AgPP v1 specification.

Usage:
    from axiom_agpp import AXIOMWrapper
    wrapper = AXIOMWrapper(org_id="acme", agent_role="researcher",
                           task_goal="Find supply chain data")
    response = wrapper.call("https://premium-data.io/endpoint")
"""

__version__ = "0.1.0"
