import os
import requests
from dotenv import load_dotenv
from axiom_agpp import AXIOMWrapper, patch_http
import logging

logging.basicConfig(level=logging.INFO)
load_dotenv(".env")

# 1. Initialize AXIOM
wrapper = AXIOMWrapper(
    org_id="acme",
    agent_role="monkey-patcher",
    task_goal="Verifying HTTP interception",
    org_secret=b"test-secret-monkey"
)
wrapper.bootstrap() # Make sure it's funded

# 2. Apply Monkey Patch (The magic 5th line)
patch_http(wrapper)

# 3. Use standard naive Requests to a 402 API
print("Executing standard requests.get() against a 402 endpoint...")
try:
    # This simulates a native agent (LangChain etc) trying to parse data
    res = requests.get("http://localhost:8000/api/v1/mock-402")
    print("\nResult Status:", res.status_code)
    print("Result Body:", res.json())
except Exception as e:
    print("Error:", e)
