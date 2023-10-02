# Modules from the project
from forms import User, BorrowForm, WithdrawForm, PaybackForm, SwapForm
from db_setup import create_tables, create_connection
from pricefeed import get_exchange_rates
from trade import trade_tst
# Third party libraries
from flask import Flask, render_template, request, flash, redirect, url_for, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, join_room, leave_room, emit
import json
import random
import threading
import websocket
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet
from xrpl.utils import xrp_to_drops

from xrpl.transaction import submit_and_wait, sign_and_submit
from xrpl.models.transactions import Payment
from xrpl.models import IssuedCurrencyAmount, Payment
import numpy as np
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import os
from dotenv import load_dotenv
from flask import Blueprint
import logging
import bcrypt
import sqlite3

# logging.basicConfig(level=logging.DEBUG, filename='application.log', filemode='w', format='%(name)s - %(levelname)s - %(message)s')

# Global variables
create_tables()
JSON_RPC_URL = "https://s.altnet.rippletest.net:51234/" # Testnet URL
client = JsonRpcClient(JSON_RPC_URL)
mm_blueprint = Blueprint('mm', __name__, template_folder='templates', static_folder='static')

app = Flask(__name__)

load_dotenv()
app.secret_key = os.getenv("DEV_KEY")
pending_confirmations = {}  #
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'mm.login'
wallet_filename = 'wallets/wallet_mm.json'
transaction_pool = []
liquidation_threshold = 1.3 # Collateral can't be less than 133% of borrrowed
asset_prices = get_exchange_rates()
with open("assets.json", "r") as f:
    assets = json.load(f)

def mm_url_for(endpoint, **values):
    return url_for('mm.' + endpoint, **values)


def get_db_cursor():
    conn = sqlite3.connect('mydb.db')
    cursor = conn.cursor()
    return conn, cursor

@app.context_processor
def inject_mm_url_for():
    return dict(mm_url_for=mm_url_for)

def get_borrowed_assets(user_id):
    conn, cursor = get_db_cursor()
    cursor.execute("SELECT * FROM borrowed_assets WHERE user_id=?", (user_id,))
    
    borrowed_assets = {}
    for row in cursor.fetchall():
        asset = row[1]
        amount = row[2]
        if asset in borrowed_assets:
            borrowed_assets[asset] += amount
        else:
            borrowed_assets[asset] = amount

    conn.close()
    return borrowed_assets

# Load a wallet from a file
def load_wallet(filename):
    with open(filename, 'r') as f:
        wallet_dict = json.load(f)
    # create a Wallet object from the loaded details
    return Wallet(wallet_dict["public_key"], wallet_dict["private_key"])

mm_wallet = load_wallet(wallet_filename)
mm_wallet_address = mm_wallet.address

def calculate_interest_rate(utilization_rate):
    if utilization_rate <= 0.90:
        return 3 + (utilization_rate * (20 - 3) / 0.9)
    else:
        # Assumes that the rate grows exponentially as per e^(40*(utilization_rate-0.9))
        return np.exp(40 * (utilization_rate - 0.9))

def calculate_apy(supplied, borrowed):
    utilization_rate = borrowed / supplied
    apy = calculate_interest_rate(utilization_rate)
    return apy

def calculate_global_apy():
    conn, cursor = get_db_cursor()

    # Assuming the total supplied and borrowed amounts are stored per asset in 'supplied_assets' and 'borrowed_assets' tables
    cursor.execute("SELECT asset, SUM(balance) FROM user_assets GROUP BY asset")
    total_supplied_assets = {asset: amount for asset, amount in cursor.fetchall()}
    
    cursor.execute("SELECT asset, SUM(amount) FROM borrowed_assets GROUP BY asset")
    total_borrowed_assets = {asset: amount for asset, amount in cursor.fetchall()}

    conn.close()

    apy = {}
    for asset, total_supplied in total_supplied_assets.items():
        total_borrowed = total_borrowed_assets.get(asset, 0)
        if total_supplied > 0:
            apy[asset] = calculate_apy(total_supplied, total_borrowed)

    return apy

def calc_assets(user):
    conn, cursor = get_db_cursor()
    # Calculate borrowed assets
    cursor.execute("SELECT * FROM borrowed_assets WHERE user_id=?", (user,))
    borrowed_assets = cursor.fetchall()
    total_borrowed_assets_usd = sum([asset[2] * asset_prices[asset[1]] for asset in borrowed_assets])

    # Calculate supplied assets
    cursor.execute("SELECT * FROM user_assets WHERE user_id=?", (user,))
    supplied_assets = cursor.fetchall()
    total_supplied_assets_usd = sum([asset[2] * asset_prices[asset[1]] for asset in supplied_assets])

    # Calculate net assets
    net_assets = total_supplied_assets_usd - total_borrowed_assets_usd

    conn.close()

    return total_borrowed_assets_usd, total_supplied_assets_usd, net_assets


def create_transaction(to_address, amount, currency):
    if currency == "XRP":
        payment_transaction = Payment(
            account="r9UrR1XaxpF3ZZUvvRChFeNa2RpbiXkrxs",
            amount=xrp_to_drops(amount),
            destination=to_address,
        )
        response = submit_and_wait(payment_transaction, client, mm_wallet)
    else:
        payment_transaction = Payment(
            account="r9UrR1XaxpF3ZZUvvRChFeNa2RpbiXkrxs",
            amount=IssuedCurrencyAmount(
                issuer="r9UrR1XaxpF3ZZUvvRChFeNa2RpbiXkrxs",
                currency=currency,
                value=amount,
                ),
            destination=to_address,
        )
        client,
        response = sign_and_submit(payment_transaction, client, mm_wallet)

    return response.result

def process_transaction(transaction):
    conn = None
    try:
        tx = transaction['transaction']

        if tx['Destination'] == mm_wallet_address :
            user_id = tx['Account']
            conn, cursor = get_db_cursor()
            cursor.execute("SELECT * FROM users WHERE _id=?", (user_id,))
            user = cursor.fetchone()

            if isinstance(tx['Amount'], dict): # This is a currency transaction
                currency = tx['Amount']['currency']
                amount = float(tx['Amount']['value'])
            else: # This is an XRP transaction
                currency = 'XRP'
                amount = float(int(tx['Amount'])/1000000)

            if 'DestinationTag' in tx and tx['DestinationTag'] in pending_confirmations:
                pending_wallet_address, username, password = pending_confirmations[tx['DestinationTag']]
                if user_id == pending_wallet_address:
                    # Add a new key-value pair to the emitted dictionary
                    socketio.emit('confirmation', {
                            'message': 'Your transaction was confirmed and your account was created.',
                            'flash_message': 'Transaction confirmed and account created.',
                            'redirect': 'login', # Inform the client to redirect to login.html
                            'delay': 2000 # Delay time in milliseconds
                        })

                    cursor.execute("INSERT INTO users (_id, username, password) VALUES (?, ?, ?)", (user_id, username, password))
                    # Insert 0 balance for each asset in borrowed_assets and supplied_assets table for the new user
                    for asset in assets:
                        cursor.execute("SELECT * FROM user_assets WHERE user_id=? AND asset=?", (user_id, asset))
                        user_asset = cursor.fetchone()
                        if not user_asset:
                            cursor.execute("INSERT INTO user_assets (user_id, asset, balance) VALUES (?, ?, 0)", (user_id, asset))
                    cursor.execute("UPDATE user_assets SET balance = balance + ?, timestamp = ? WHERE user_id = ? AND asset = ?", (amount, datetime.now(), user_id, currency))
                    conn.commit()
                del pending_confirmations[tx['DestinationTag']]

            elif user is None:
                cursor.execute("INSERT INTO users (_id) VALUES (?)", (user_id,))
                cursor.execute("SELECT * FROM user_assets WHERE user_id=? AND asset=?", (user_id, currency))
                user_asset = cursor.fetchone()
                if not user_asset:
                    cursor.execute("INSERT INTO user_assets (user_id, asset, balance) VALUES (?, ?, ?)", (user_id, currency, amount))
                user = (user_id, 0)
            else:
                cursor.execute("SELECT * FROM user_assets WHERE user_id=? AND asset=?", (user_id, currency))
                user_asset = cursor.fetchone()
                current_time = datetime.now()
                if user_asset:
                    new_balance = user_asset[2] + amount
                    cursor.execute("UPDATE user_assets SET balance = ?, timestamp = ? WHERE user_id = ? AND asset = ?", (new_balance, current_time, user_id, currency))
                else:
                    # If asset does not exist for the user, insert a new row in the user_assets table
                    cursor.execute("INSERT INTO user_assets (user_id, asset, balance, timestamp) VALUES (?, ?, ?, ?)", (user_id, currency, amount, current_time))
                conn.commit()

            user_room = tx['Account']  # This should correspond to the user's ID
            if user_room:  
                socketio.emit('deposit', {'amount': amount, 'asset': currency}, room=user_room)

    except Exception as e:
        print(f"Error processing transaction: {e}")

    finally:
        if conn:
            conn.close()

# Interest rate saving logic.

def save_interest_rates():
    apy = calculate_global_apy()
    conn, cursor = get_db_cursor()

    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f') # Current server timestamp

    for asset, interest_rate in apy.items():
        cursor.execute("INSERT INTO interest_rates (asset, interest_rate, timestamp) VALUES (?, ?, ?)", (asset, interest_rate, current_time))

    conn.commit()
    conn.close()


def calculate_yield(asset, amount, user_id):
    conn, cursor = get_db_cursor()

    # Fetch historical interest rates for the asset
    cursor.execute("SELECT interest_rate, timestamp FROM interest_rates WHERE asset=? ORDER BY timestamp", (asset,))
    interest_rates = cursor.fetchall()

    # Fetch the timestamp when the user supplied the asset
    cursor.execute("SELECT timestamp FROM user_assets WHERE user_id=? AND asset=?", (user_id, asset))
    supplied_timestamp_row = cursor.fetchone()
    if supplied_timestamp_row:
        supplied_timestamp = parse_timestamp(supplied_timestamp_row[0])
    else:
        conn.close()
        return 0.0  # Return 0 if there is no supplied timestamp for the asset

    # Initialize yield
    asset_yield = 0.0

    # Iterate through the historical interest rates and calculate yield
    for i in range(len(interest_rates) - 1):
        rate, timestamp = interest_rates[i]
        next_rate, next_timestamp = interest_rates[i + 1]
        timestamp = parse_timestamp(timestamp)
        next_timestamp = parse_timestamp(next_timestamp)

        # Consider only the time period when the user has been providing the asset
        if next_timestamp < supplied_timestamp:
            continue
        if timestamp < supplied_timestamp:
            timestamp = supplied_timestamp

        # Calculate duration in minutes
        duration_minutes = (next_timestamp - timestamp).total_seconds() / 60

        # Convert the annual yield to a minute yield
        minute_yield = rate / 525600

        # Calculate the yield amount for the given duration
        yield_amount = minute_yield * amount * duration_minutes / 100
        asset_yield += yield_amount

    conn.close()
    return asset_yield

def calculate_accrued_interest(asset, amount, user_id):
    conn, cursor = get_db_cursor()

    # Fetch historical interest rates for the asset
    cursor.execute("SELECT interest_rate, timestamp FROM interest_rates WHERE asset=? ORDER BY timestamp", (asset,))
    interest_rates = cursor.fetchall()

    # Fetch the timestamp when the user borrowed the asset
    cursor.execute("SELECT timestamp FROM borrowed_assets WHERE user_id=? AND asset=?", (user_id, asset))
    borrowed_timestamp_row = cursor.fetchone()
    if borrowed_timestamp_row:
        borrowed_timestamp = parse_timestamp(borrowed_timestamp_row[0])
    else:
        conn.close()
        return 0.0  # Return 0 if there is no borrowed timestamp for the asset

    # Initialize accrued interest
    accrued_interest = 0.0

    # Iterate through the historical interest rates and calculate interest
    for i in range(len(interest_rates) - 1):
        rate, timestamp = interest_rates[i]
        next_rate, next_timestamp = interest_rates[i + 1]
        timestamp = parse_timestamp(timestamp)
        next_timestamp = parse_timestamp(next_timestamp)

        # Consider only the time period when the user has been borrowing the asset
        if next_timestamp < borrowed_timestamp:
            continue
        if timestamp < borrowed_timestamp:
            timestamp = borrowed_timestamp
        # Calculate duration in minutes
        duration_minutes = (next_timestamp - timestamp).total_seconds() / 60

        # Convert the annual yield to a minute yield
        minute_rate = rate / 525600

        # Calculate the yield amount for the given duration
        interest_amount = minute_rate * amount * duration_minutes / 100

        accrued_interest += interest_amount

    conn.close()
    return accrued_interest

def parse_timestamp(timestamp_str):
    try:
        # Try to parse the timestamp with fractional seconds
        return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
    except ValueError:
        # If that fails, try to parse the timestamp without fractional seconds
        return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')


@login_manager.user_loader
def load_user(user_id):
    conn, cursor = get_db_cursor()
    cursor.execute("SELECT * FROM users WHERE _id=?", (user_id,))
    user = cursor.fetchone()
    if user:
        # Fetch assets
        cursor.execute("SELECT * FROM user_assets WHERE user_id=?", (user_id,))
        assets = {row[1]: row[2] for row in cursor.fetchall()}
        # Fetch borrowed assets
        borrowed_assets = get_borrowed_assets(user_id)
        conn.close()
        return User(user[0], user[1], assets, borrowed_assets)
    else:
        conn.close()
        return None

@mm_blueprint.route('/')
def index():
    conn, cursor = get_db_cursor()

    # Query to get all assets and total balances
    cursor.execute("SELECT asset, SUM(balance) FROM user_assets GROUP BY asset")
    assets_provided = {row[0]: row[1] for row in cursor.fetchall()}

    # Query to get all borrowed assets and total amounts
    cursor.execute("SELECT asset, SUM(amount) FROM borrowed_assets GROUP BY asset")
    assets_borrowed = {row[0]: row[1] for row in cursor.fetchall()}

    markets = []
    for asset, supplied in assets_provided.items():
        borrowed = assets_borrowed.get(asset, 0)
        apy = calculate_apy(supplied, borrowed) if supplied > 0 else 0
        price = asset_prices.get(asset, 0)  # Get the price for the asset
        markets.append({'name': asset, 'provided_assets': supplied, 'borrowed_assets': borrowed, 'apy': apy, 'price': price})  # Add price to the market dictionary

    conn.close()
    return render_template('index.html', markets=markets)


@mm_blueprint.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        raw_password = request.form.get('password')
        password = bcrypt.hashpw(raw_password.encode('utf-8'), bcrypt.gensalt()).decode("utf-8")
        wallet_address = request.form.get('wallet_address')

        conn, cursor = get_db_cursor()

        # Check if user already exists
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        if user:
            conn.close()
            return "User already exists."

        # Generate a 9-digit number for destination tag
        unique_num = random.randint(100000000, 999999999)

        # Store this number along with user info in pending_confirmations
        pending_confirmations[unique_num] = (wallet_address, username, password)

        # Provide the user with the unique number and ask them to send a transaction with it as the DestinationTag
        return render_template('register.html', unique_num=unique_num)

    else:
        return render_template('register.html')


@mm_blueprint.route('/dashboard/<user_id>', methods=['GET'])
@login_required
def dashboard(user_id):
    conn, cursor = get_db_cursor()

    cursor.execute("SELECT * FROM users WHERE _id=?", (user_id,))
    user = cursor.fetchone()

    # Fetch borrowed assets for user
    cursor.execute("SELECT * FROM borrowed_assets WHERE user_id=?", (user_id,))
    borrowed_assets_db = cursor.fetchall()

    # Fetch liquidations for user
    cursor.execute("SELECT * FROM liquidations WHERE user_id=?", (user_id,))
    liquidations_db = cursor.fetchall()

    borrowed_assets = {asset: 0.0 for asset in assets}

    # Sum up the borrowed amounts for each asset
    for asset in borrowed_assets_db:
        if asset[1] in borrowed_assets:
            borrowed_assets[asset[1]] += asset[2]

    # Fetch total assets for user
    cursor.execute("SELECT * FROM user_assets WHERE user_id=?", (user_id,))
    total_assets_db = cursor.fetchall()
    total_assets = {asset[1]: asset[2] for asset in total_assets_db}

    # Initialize apy dictionary with zero values for all assets
    apy = {asset: 0.0 for asset in assets}

    # Calculate APY values for each asset globally
    global_apy = calculate_global_apy()

    for asset in assets:
        if asset in global_apy:
            apy[asset] = global_apy[asset]

  # Calculate accrued interest for borrowed assets
    borrowed_interest = {asset: calculate_accrued_interest(asset, amount, user_id) for asset, amount in borrowed_assets.items()}

    # Calculate yield for supplied assets
    supplied_yield = {asset: calculate_yield(asset, amount, user_id) for asset, amount in total_assets.items()}

    conn.close()

    # Sort the total_assets (supplied assets) by balance
    sorted_total_assets = sorted(total_assets.items(), key=lambda x: x[1], reverse=True)
    sorted_total_assets_dict = dict(sorted_total_assets)

    # Sort the borrowed_assets by balance
    sorted_borrowed_assets = sorted(borrowed_assets.items(), key=lambda x: x[1], reverse=True)
    sorted_borrowed_assets_dict = dict(sorted_borrowed_assets)

    # Get total borrowed, supplied, and net assets
    total_borrowed_usd, total_supplied_usd, net_assets_usd = calc_assets(user_id)


    if user and user[0] == current_user.id:
        return render_template('dashboard.html',
             user_id=current_user.id,
             user=user,
             borrowed_assets=sorted_borrowed_assets_dict,
             total_assets=sorted_total_assets_dict,
             apy=apy,
             borrowed_interest=borrowed_interest,
             supplied_yield=supplied_yield,
             total_borrowed_usd=total_borrowed_usd,
             total_supplied_usd=total_supplied_usd,
             net_assets_usd=net_assets_usd,
             liquidations=liquidations_db,)
    else:
        return "You don't have access to this page."

@mm_blueprint.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        raw_password = request.form.get('password')

        conn, cursor = get_db_cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()

        # Check if user exists
        if user is None:
            flash('Invalid username or password. Please try again.', 'error')
            return redirect(mm_url_for('login'))

        cursor.execute("SELECT asset, amount FROM borrowed_assets WHERE user_id=?", (user[0],))
        borrowed_assets = {asset: amount for asset, amount in cursor.fetchall()}
        conn.close()

        if user and bcrypt.checkpw(raw_password.encode('utf-8'), user[2].encode('utf-8')):
            user_obj = User(user[0], user[1], user[2], borrowed_assets)
            login_user(user_obj)
            return redirect(mm_url_for('dashboard', user_id=user[0]))

        else:
            flash('Invalid password. Please try again.', 'error')
            return redirect(mm_url_for('login'))

    return render_template('login.html')


@mm_blueprint.route('/withdraw', methods=['GET', 'POST'])
@login_required
def withdraw():
    form = WithdrawForm()

    total_borrowed_usd, total_supplied_usd, _ = calc_assets(current_user.id)

    # Calculate the total amount that must be kept in collateral
    collateral_required_usd = 2 * total_borrowed_usd

    # Sort assets by supplied amount
    sorted_assets = sorted(current_user.assets.items(), key=lambda x: -x[1] * asset_prices[x[0]])

    # Calculate total borrowed, supplied, and net assets
    total_borrowed_usd, total_supplied_usd, net_assets_usd = calc_assets(current_user.id)

    available_for_withdrawal = max(total_supplied_usd - total_borrowed_usd*2, 0)

    # Calculate available and locked assets using the waterfall design
    available_assets = {}
    locked_assets = {}
    remaining_collateral_required_usd = collateral_required_usd
    for asset, amount in sorted_assets:
        asset_value_usd = amount * asset_prices[asset]
        locked_value_usd = min(asset_value_usd, remaining_collateral_required_usd)
        available_value_usd = asset_value_usd - locked_value_usd
        available_assets[asset] = available_value_usd / asset_prices[asset]
        locked_assets[asset] = amount - available_assets[asset]
        remaining_collateral_required_usd -= locked_value_usd


    # Reorder the assets from highest value to lowest value
    sorted_assets = sorted(available_assets.keys(), key=lambda asset: -available_assets[asset] * asset_prices[asset])

    # Create an ordered list of available and locked assets
    ordered_available_assets = {asset: available_assets[asset] for asset in sorted_assets}
    ordered_locked_assets = {asset: locked_assets[asset] for asset in sorted_assets}
    if form.validate_on_submit():
        total_borrowed_usd, total_supplied_usd, _ = calc_assets(current_user.id)

        # Calculate the maximum amount the user can withdraw
        max_withdrawal = total_supplied_usd - 2 * total_borrowed_usd  # user needs to maintain 2x the borrowed amount as collateral

        # Check if the user has enough balance to withdraw
        withdrawal_usd = float(form.amount.data) * asset_prices[form.asset_type.data]
        if withdrawal_usd <= max_withdrawal:
            if current_user.assets[form.asset_type.data] >= form.amount.data:
                current_user.assets[form.asset_type.data] -= form.amount.data

                # Create a transaction to send the withdrawn amount to the user
                response = create_transaction(current_user.id, form.amount.data, form.asset_type.data)
                conn, cursor = get_db_cursor()
                # Save withdrawal to the database
                cursor.execute("UPDATE user_assets SET balance = balance - ? WHERE user_id = ? AND asset = ?",
                               (float(form.amount.data), current_user.id, form.asset_type.data))
                conn.commit()
                conn.close()

                flash(f'Withdrawn {form.amount.data} {form.asset_type.data}!', 'success')
                return redirect(mm_url_for('withdraw'))

            else:
                flash('Not enough balance!', 'danger')
                return redirect(mm_url_for('withdraw'))

        else:
            flash('Insufficient balance for withdrawal!', 'danger')
            return redirect(mm_url_for('withdraw'))

    return render_template('withdraw.html', title='Withdraw', form=form, available_assets=ordered_available_assets, locked_assets=ordered_locked_assets, legend='New Withdraw', total_borrowed_usd=total_borrowed_usd, total_supplied_usd=total_supplied_usd, available_for_withdrawal=available_for_withdrawal)

def check_for_liquidation(user_id):

    conn, cursor = get_db_cursor()

    # Calculate the net USD position of the user
    total_borrowed_usd, total_supplied_usd, net_usd = calc_assets(user_id)
    if total_borrowed_usd > 0:
        asset_ratio = total_supplied_usd / total_borrowed_usd 
    else:
        asset_ratio = 1000

    # If the collateral falls below threshold of the borrowed amount, trigger a liquidation
    if asset_ratio < liquidation_threshold:
        print(f"User {user_id} liquidated")

        # Fetch the user's account and assets
        cursor.execute("SELECT user_id, asset, balance FROM user_assets WHERE user_id=?", (user_id,))
        user_assets = cursor.fetchall()

        for user_asset in user_assets:
            account, asset, amount = user_asset

            # Only create an entry to the liquidations database for the assets that have balance that is not 0
            if amount > 0:
                # Get the current date
                current_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')

                # Insert into liquidations table
                cursor.execute("INSERT INTO liquidations (user_id, asset, amount, date) VALUES (?, ?, ?, ?)", 
                               (user_id, asset, amount, current_date))

        # Update user_assets and borrowed_assets tables
        cursor.execute("UPDATE user_assets SET balance = 0 WHERE user_id = ?", (user_id,))
        cursor.execute("UPDATE borrowed_assets SET amount = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

        return True
    else:
        conn.close()
        return False
        
def check_all_users_for_liquidation():
    print("Checking for liquidatons....")
    conn, cursor = get_db_cursor()
    cursor.execute("SELECT _id FROM users")
    user_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    for user_id in user_ids:
        check_for_liquidation(user_id)

@mm_blueprint.route('/borrow', methods=['GET', 'POST'])
@login_required
def borrow():
    form = BorrowForm()

    # Calculate net USD and collateral
    total_borrowed_usd, total_supplied_usd, net_usd = calc_assets(current_user.id)
    collateral = net_usd * 0.5  # User can borrow up to 50% of their net USD position

    # Retrieve borrowed assets
    conn, cursor = get_db_cursor()
    cursor.execute("SELECT asset, SUM(amount) FROM borrowed_assets WHERE user_id=? GROUP BY asset", (current_user.id,))
    borrowed_assets = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    # Create the assets_details dictionary with the current balance, borrowed assets, and max borrowable amount for each asset
    assets_details = {}
    for asset, price in asset_prices.items():
        balance = current_user.assets.get(asset, 0)
        borrowed = borrowed_assets.get(asset, 0)
        max_borrowable = collateral / asset_prices[asset] # Independent max borrowable for each asset
        assets_details[asset] = {
            'balance': balance,
            'borrowed': borrowed,
            'max_borrowable': max_borrowable
        }

    # Sort assets_details by borrowed amount
    sorted_assets_details = sorted(assets_details.items(), key=lambda x: x[1]['borrowed'], reverse=True)

    if form.validate_on_submit():
        selected_asset = form.asset_type.data
        borrow_amount = float(form.amount.data)

        borrow_amount_usd = borrow_amount * asset_prices[selected_asset]
        if borrow_amount_usd <= collateral:
            # Increase the available balance in user_assets
            conn, cursor = get_db_cursor()
            cursor.execute("UPDATE user_assets SET balance = balance + ? WHERE user_id = ? AND asset = ?",
                           (borrow_amount, current_user.id, selected_asset))

            # Save the borrowing to the database
            cursor.execute("INSERT INTO borrowed_assets (user_id, asset, amount) VALUES (?, ?, ?)",
                           (current_user.id, selected_asset, borrow_amount))
            conn.commit()
            conn.close()

            # Update the current user's asset in memory (if needed)
            current_user.assets[selected_asset] = current_user.assets.get(selected_asset, 0) + borrow_amount

            flash(f'Borrowed {form.amount.data} {form.asset_type.data}!', 'success')
            return redirect(mm_url_for('borrow', user_id=current_user.id))
        else:
            flash('Insufficient collateral!', 'danger')
            return redirect(mm_url_for('borrow'))

    return render_template('borrow.html', title='Borrow', form=form, assets_details=sorted_assets_details, legend='New Borrow')

@mm_blueprint.route('/payback', methods=['GET', 'POST'])
@login_required
def payback():
    form = PaybackForm()

    # Retrieve borrowed assets
    conn, cursor = get_db_cursor()
    cursor.execute("SELECT asset, SUM(amount) FROM borrowed_assets WHERE user_id=? GROUP BY asset", (current_user.id,))
    borrowed_assets = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    # Calculate accrued interest for borrowed assets
    borrowed_interest = {asset: calculate_accrued_interest(asset, amount, current_user.id) for asset, amount in borrowed_assets.items()}

    # Calculate total, and available balance
    assets_details = {}
    for asset, borrowed in borrowed_assets.items():
        interest = borrowed_interest[asset]
        total = borrowed + interest
        available = current_user.assets.get(asset, 0)
        assets_details[asset] = {
            'borrowed': borrowed,
            'interest': interest,
            'total': total,
            'available': available
        }
    if form.validate_on_submit():
            selected_asset = form.asset_type.data
            payback_amount_input = float(form.amount.data)

            borrowed_amount = borrowed_assets[selected_asset]
            interest = borrowed_interest[selected_asset]
            total_payback_amount = borrowed_amount + interest

            # Check if the user has enough balance
            available_balance = current_user.assets.get(selected_asset, 0)

            # Determine the actual amount to pay back
            actual_payback_amount = min(payback_amount_input, total_payback_amount)

            if actual_payback_amount <= available_balance:
                # Deduct the balance from the supplied assets balance
                current_user.assets[selected_asset] -= actual_payback_amount

                # Update the borrowed assets table to zero
                conn, cursor = get_db_cursor()
                cursor.execute("UPDATE borrowed_assets SET amount = CASE WHEN amount - ? < 0 THEN 0 ELSE amount - ? END WHERE user_id = ? AND asset = ?",
                            (actual_payback_amount, actual_payback_amount, current_user.id, selected_asset))
                # Update the user assets table
                cursor.execute("UPDATE user_assets SET balance = balance - ? WHERE user_id = ? AND asset = ?",
                            (actual_payback_amount, current_user.id, selected_asset))
                conn.commit()
                conn.close()

                flash(f'Paid back {actual_payback_amount} {selected_asset}!', 'success')
                return redirect(mm_url_for('payback'))
            else:
                flash('Not enough balance!', 'danger')
                return redirect(mm_url_for('payback'))

    return render_template('payback.html', title='Payback', form=form, assets_details=assets_details.items())

@mm_blueprint.route('/deposit/<asset>', methods=['GET'])
@login_required
def deposit(asset):
    return render_template('deposit.html', asset=asset)

@mm_blueprint.route('/swap', methods=['GET', 'POST'])
@login_required
def swap():
    form = SwapForm()

    # Fetch user's current balances
    conn, cursor = get_db_cursor()
    cursor.execute("SELECT asset, balance FROM user_assets WHERE user_id=?", (current_user.id,))
    user_balances = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    xrp_balance = user_balances.get("XRP", 0)
    tst_balance = user_balances.get("TST", 0)

    # Define fixed rates
    buy_rate = 0.115  # TST per XRP
    sell_rate = 8.5   # XRP per TST

    if form.validate_on_submit():
        side = form.side.data
        amount = float(form.amount.data)
        
        conn, cursor = get_db_cursor()
        
        # Check user's current XRP and TST balances (although redundant since you fetched them earlier, it's good to check again before making any transactions)
        cursor.execute("SELECT asset, balance FROM user_assets WHERE user_id=?", (current_user.id,))
        user_balances = {row[0]: row[1] for row in cursor.fetchall()}

        xrp_balance = user_balances.get("XRP", 0)
        tst_balance = user_balances.get("TST", 0)

        if side == 'buy':
            xrp_cost = amount / buy_rate
            print(f'Calculated XRP cost: {xrp_cost}')
            if xrp_balance >= xrp_cost:
                # Deduct the XRP cost
                cursor.execute("UPDATE user_assets SET balance = balance - ? WHERE user_id = ? AND asset = ?", (xrp_cost, current_user.id, 'XRP'))

                # Check if the user already has TST
                cursor.execute("SELECT balance FROM user_assets WHERE user_id = ? AND asset = ?", (current_user.id, 'TST'))
                existing_tst_balance = cursor.fetchone()

                if existing_tst_balance:
                    # If the user already has TST, update the balance
                    cursor.execute("UPDATE user_assets SET balance = balance + ? WHERE user_id = ? AND asset = ?", (amount, current_user.id, 'TST'))
                else:
                    # If the user doesn't have TST, insert a new record
                    cursor.execute("INSERT INTO user_assets (user_id, asset, balance) VALUES (?, ?, ?)", (current_user.id, 'TST', amount))

                conn.commit()
                print('Buy operation executed')
            else:
                flash('Insufficient XRP to make the swap.', 'danger')
                return redirect(mm_url_for('swap'))

        elif side == 'sell':
            if tst_balance >= amount:
                # Deduct the TST
                cursor.execute("UPDATE user_assets SET balance = balance - ? WHERE user_id = ? AND asset = ?", (amount, current_user.id, 'TST'))
                
                # Check if the user already has XRP
                cursor.execute("SELECT balance FROM user_assets WHERE user_id = ? AND asset = ?", (current_user.id, 'XRP'))
                existing_xrp_balance = cursor.fetchone()

                xrp_gained = amount * sell_rate  # Calculate XRP to be gained

                if existing_xrp_balance:
                    # If the user already has XRP, update the balance
                    cursor.execute("UPDATE user_assets SET balance = balance + ? WHERE user_id = ? AND asset = ?", (xrp_gained, current_user.id, 'XRP'))
                else:
                    # If the user doesn't have XRP, insert a new record
                    cursor.execute("INSERT INTO user_assets (user_id, asset, balance) VALUES (?, ?, ?)", (current_user.id, 'XRP', xrp_gained))
                
                conn.commit()
            else:
                flash('Insufficient TST to make the swap.', 'danger')
                return redirect(mm_url_for('swap'))


        # Close connection
        conn.close()

        # Execute the swap
        result = trade_tst(side, amount)
        if result: 
            flash(f'Swap executed successfully!', 'success')
        else:
            flash('Swap failed. Please try again later.', 'danger')
        
        return redirect(mm_url_for('swap'))
    return render_template('swap.html', title='Swap', form=form, xrp_balance=xrp_balance, tst_balance=tst_balance, buy_rate=buy_rate, sell_rate=sell_rate)


@mm_blueprint.route('/liquidations', methods=['GET'])
@login_required
def liquidations():
    conn, cursor = get_db_cursor()
    cursor.execute("SELECT * FROM liquidations")
    liquidations = cursor.fetchall()
    conn.close()

    return render_template('liquidations.html', liquidations=liquidations)


@mm_blueprint.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('./login')


app.register_blueprint(mm_blueprint, url_prefix='/mm')
socketio = SocketIO(app, path='/mm/socket.io', logger=True, engineio_logger=True)

# Socket IO functions

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        join_room(current_user.id)  # Join the room with user's ID
    else:
        print("Unauthenticated user connected, but not joined to any room.")

@socketio.on('join_room')
def on_join_room(data):
    room = data['room']
    join_room(room)

@socketio.on('leave_room')
def on_leave_room(data):
    room = data['room']
    leave_room(room)

@socketio.on('disconnect')
def on_disconnect():
    if current_user.is_authenticated:
        leave_room(current_user.id)
        print(f"User {current_user.id} disconnected and left the room.")
    else:
        print("Unauthenticated user disconnected.")

@socketio.on_error_default  # Registers an error handler for all namespaces without an error event
def default_error_handler(e):
    logging.error(f"SocketIO Error: {str(e)}")

# Websocket functions

def on_message(ws, message):
    print(f"Received: {message}")
    transaction = json.loads(message)
    process_transaction(transaction)

def on_error(ws, error):
    print(error)

def on_close(ws, status, msg):
    print(f"### closed ###" )

def on_open(ws):
    print("WS OPEN")
    # Subscribe to ledger transaction events
    ws.send(json.dumps({
        "id": 1,
        "command": "subscribe",
        "accounts": [mm_wallet_address],
    }))

scheduler = BackgroundScheduler()
scheduler.add_job(save_interest_rates, 'interval', minutes=1)
scheduler.add_job(check_all_users_for_liquidation, 'interval', minutes=1)
scheduler.start()

if __name__ == "__main__":
    ws = websocket.WebSocketApp("wss://s.altnet.rippletest.net:51233/",
                                on_open = on_open,
                                on_message = on_message,
                                on_error = on_error,
                                on_close = on_close)

    wst = threading.Thread(target=ws.run_forever)
    wst.start()
    # Start the Flask server
    socketio.run(app, port=5005)
