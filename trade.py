import json
from xrpl.models import XRP, IssuedCurrency
from xrpl.utils import xrp_to_drops
from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import OfferCreate
from xrpl.wallet import Wallet
from xrpl.transaction import submit
from xrpl.asyncio.transaction import autofill_and_sign
from xrpl.transaction import submit_and_wait, sign_and_submit

# Load a wallet from a file
def load_wallet_from_file(filename):
    with open(filename, 'r') as f:
        wallet_dict = json.load(f)
    print(wallet_dict)
    # create a Wallet object from the loaded details
    return Wallet(wallet_dict["public_key"], wallet_dict["private_key"])

wallet = load_wallet_from_file('wallets/wallet_mm.json')

# Define the network client
client = JsonRpcClient("https://s.altnet.rippletest.net:51234")

def build_tx(side, amount):
# Define the proposed trade.
    tst_tx = {
        "currency": IssuedCurrency(
            currency="TST",
            issuer="rP9jPyP5kyvFRb6ZiRghAGw5u8SGAmU4bd"
        ),
        "value": amount,
    }

    xrp_txt = {
        "currency": XRP(),
        # 25 TST * 10 XRP per TST * 15% financial exchange (FX) cost
        "value_buy": xrp_to_drops(amount * amount/2.5 * 1.15),
        "value_sell": xrp_to_drops(amount * amount/2.5 * 0.4),
        }
    if side == 'buy':
        buy_tx = OfferCreate(
            account=wallet.address,
            taker_gets=xrp_txt["value_buy"],
            taker_pays=tst_tx["currency"].to_amount(tst_tx["value"]),
        )
        return buy_tx
    
    if side == 'sell':
        sell_tx = OfferCreate(
            account=wallet.address,
            taker_gets=tst_tx["currency"].to_amount(tst_tx["value"]),
            taker_pays=xrp_txt["value_sell"],
        )
        return sell_tx

def trade_tst(side, amount):
    if side == 'sell':
        sell_tx = build_tx(side, amount)
        return sign_and_submit(sell_tx, client, wallet)
    if side == 'buy':
        buy_tx = build_tx(side, amount)
        return sign_and_submit(buy_tx, client, wallet)


# Buy: You pay 8.7XRP per TST (0.115)
# Sell: You get 8.5 XRP per TST  (0.1176)