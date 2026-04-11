import os
import logging
from dotenv import load_dotenv
from axiom_agpp.wrapper import AXIOMWrapper

logging.basicConfig(level=logging.INFO)
# FORCE reload .env to be 100% sure we are on Testnet
load_dotenv(".env", override=True)

print("NETWORK:", os.getenv("ALGOD_SERVER"))
print("DEPLOYER:", os.getenv("DEPLOYER_MNEMONIC")[:20] + "...")

try:
    wrapper = AXIOMWrapper(
        org_id="acme",
        agent_role="troubleshooter",
        task_goal="Find why Testnet transactions aren't appearing",
        org_secret=b"hackathon-secret-2026"
    )
    
    print("\nAttempting Bootstrap...")
    wrapper.bootstrap()
    
    print("\nAttempting 402 Call...")
    # Using the local mock which will return a 402
    url = "http://localhost:8000/api/v1/mock-402"
    res = wrapper.call(url)
    print("Call response status:", res.status_code)
    
except Exception as e:
    logging.exception("Manual trigger failed:")
