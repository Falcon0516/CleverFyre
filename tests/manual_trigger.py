"""
Manual Trigger Script for AXIOM AgPP LocalNet
---------------------------------------------

This script instantiates an AXIOM AI agent and intentionally pings
the local mock-402 endpoint to trigger a real transaction on LocalNet.

Because the underlying `AXIOMWrapper` now includes the `x402:axiom:PAYMENT`
note in its Algorand contract calls, the backend Indexer will pick it up
naturally and broadcast it to your frontend.

Run this while having the Backend (uvicorn) and Frontend (npm run dev) open!
"""

import os
import sys

# Ensure projects can import axiom_agpp
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "projects", "cleverfyre"))

from axiom_agpp.wrapper import AXIOMWrapper

from dotenv import load_dotenv

def main():
    # Load contract IDs from .env before initializing AXIOMWrapper
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    
    print("Initializing AXIOM Agent...")
    wrapper = AXIOMWrapper(
        org_id="acme",
        agent_role="researcher",
        task_goal="Find stock prices",
        org_secret=b"hackathon-secret-2026",
        policy_path=os.path.join(PROJECT_ROOT, "policy.yaml")
    )

    # We call the mock-402 endpoint on our backend to simulate an API that
    # demands payment (HTTP 402 Payment Required). 
    # The wrapper intercepts this 402, and transparently executes the 
    # full LocalNet payment protocol before retrying.
    url = "http://localhost:8000/api/v1/mock-402"
    
    print(f"\nTriggering agent call to {url}")
    print("Watch your terminal and the frontend dashboard!\n")
    
    try:
        response = wrapper.call(url)
        print(f"\n[SUCCESS] Final response status code: {response.status_code}")
    except Exception as e:
        print(f"\n[BLOCKED] Call rejected by Sentinel Mesh: {e}")

if __name__ == "__main__":
    main()
