import os
import time
from algosdk.v2client import algod
from algosdk.logic import get_application_address
from dotenv import load_dotenv
import algokit_utils

load_dotenv(".env", override=True)

algod_server = os.getenv('ALGOD_SERVER')
client = algod.AlgodClient('', algod_server, headers={})
algo_client = algokit_utils.AlgorandClient.from_environment()

deployer_mnemonic = os.getenv("DEPLOYER_MNEMONIC")
deployer_account = algo_client.account.from_mnemonic(mnemonic=deployer_mnemonic)

# We only need to fund the 3 remaining accounts that failed
app_ids = [
    os.getenv('SENTINEL_ESCROW_ID'),
    os.getenv('PAYMENT_DNA_REGISTRY_ID'),
    os.getenv('CONSENSUS_VAULT_ID'),
    os.getenv('REPUTATION_LEDGER_ID')
]

for app_id in app_ids:
    if not app_id: continue
    app_id = int(app_id)
    app_addr = get_application_address(app_id)
    print(f"Funding App {app_id} ({app_addr}) with 0.2 ALGO...")
    
    try:
        algo_client.send.payment(algokit_utils.PaymentParams(
            sender=deployer_account.address,
            receiver=app_addr,
            amount=algokit_utils.AlgoAmount(algo=0.2), # Reduced to 0.2 ALGO (PLENTY for boxes)
            signer=deployer_account.signer,
            note=b"axiom:mbr_fund_micro"
        ))
        print("Success.")
    except Exception as e:
        print(f"Failed: {e}")
        
print("All App Accounts funded!")
