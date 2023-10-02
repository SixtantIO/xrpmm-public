from xrpl.clients import JsonRpcClient
from xrpl.wallet import generate_faucet_wallet, Wallet
from xrpl.models.transactions import Payment
from xrpl.models import IssuedCurrencyAmount, Payment, TrustSet
from xrpl.utils import xrp_to_drops
from xrpl.transaction import submit_and_wait, sign_and_submit
import json
import os

rec_wallet_name = "wallet_mm"

send_wallet_name = "new"
destination_tag = 462556643
send_amount = 530
asset = "USD"

if asset == "XRP":
    send_amount_drops = xrp_to_drops(float(send_amount))
else:
    send_amount_drops = send_amount


# Possibly should go in some init function
if not os.path.exists("wallets"):
    os.makedirs("wallets")

# JSON_RPC_URL = "https://s2.ripple.com:51234/"  # Production URL
JSON_RPC_URL = "https://s.altnet.rippletest.net:51234/" # Testnet URL
client = JsonRpcClient(JSON_RPC_URL)

# Specify the path to the file where the wallet details will be saved
send_filename = f'wallets/{send_wallet_name}.json'
rec_filename = f'wallets/{rec_wallet_name}.json'

# Generate a wallet from the testnet faucet
def save_wallet_to_file(wallet, filename):
    with open(filename, 'w') as f:
        # save the wallet's classic address and private key as a dictionary
        json.dump({"public_key": wallet.public_key,"classic_address": wallet.classic_address, "private_key": wallet.private_key}, f)

# Load a wallet from a file
def load_wallet_from_file(filename):
    with open(filename, 'r') as f:
        wallet_dict = json.load(f)
    print(wallet_dict)
    # create a Wallet object from the loaded details
    return Wallet(wallet_dict["public_key"], wallet_dict["private_key"])

def create_or_reuse(filename):
    # Check if the wallet file already exists
    if os.path.isfile(filename):
        # If it does, load the wallet details from the file
        wallet = load_wallet_from_file(filename)
        return wallet
    else:
        # If not, generate a new wallet and save the details to the file
        wallet = generate_faucet_wallet(client, debug=True)
        save_wallet_to_file(wallet, filename)
        return wallet

send_wallet = create_or_reuse(send_filename)
rec_wallet = create_or_reuse(rec_filename)

# Create an account str from the wallet
send_account = send_wallet.address
rec_account = rec_wallet.address

# Send XRP transaction

def send_xrp():
    print(f"Send amount is {send_amount}")
    my_tx_payment = Payment(
        account=send_account,
        amount=send_amount_drops,
        destination=rec_account,
        destination_tag=destination_tag, 
    )
    return submit_and_wait(my_tx_payment, client, send_wallet)

def send_asset():
    my_tx_payment = Payment(
        account=send_wallet.classic_address,
        amount=IssuedCurrencyAmount(
            issuer=send_wallet.classic_address,
            currency=asset,
            value=send_amount_drops,
            ),
        destination=rec_wallet.classic_address,
    )
    return sign_and_submit(my_tx_payment, client, send_wallet)

def set_trustline():
    my_tx =   TrustSet(
    account=rec_wallet.classic_address,
    limit_amount=IssuedCurrencyAmount(
      issuer=send_wallet.classic_address,
      currency=asset,
      value="1000000"
      )
    )
    return sign_and_submit(my_tx, client, rec_wallet)

if asset == "XRP":
    send_xrp()
else:
    set_trustline()
    send_asset()

# for i in range(1,50):
#     send_wallet_name = f"fund_wallet{i}"
#     send_filename = f'wallets/{send_wallet_name}.json'
#     send_wallet = create_or_reuse(send_filename)
#     send_account = send_wallet.address
#     send_xrp()