import requests

def get_last_price_from_bitso(ticker):
    try:
        url = f"https://api.bitso.com/v3/ticker/?book={ticker}"
        response = requests.get(url)
        if response.status_code == 200:
            return float(response.json()["payload"]["last"])
        else:
            raise Exception
    except:
        if ticker == "usd_mxn":
            return 1/0.05882352941
        return None

def get_last_price_from_binance(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        response = requests.get(url)
        if response.status_code == 200:
            return float(response.json()["price"])
        else:
            raise Exception
    except:
        return None  # No default value provided for Binance. Return None or adjust as necessary.

def get_last_price_from_bitstamp(currency_pair):
    try:
        url = f"https://www.bitstamp.net/api/v2/ticker/{currency_pair}/"
        response = requests.get(url)
        if response.status_code == 200:
            return float(response.json()["last"])
        else:
            raise Exception
    except:
        if currency_pair == "xrpusd":
            return 0.5
        elif currency_pair == "eurusd":
            return 1.07
        return None

def get_exchange_rates():
    rates = {
        "MXN": 1/get_last_price_from_bitso("usd_mxn"),
        "XRP": get_last_price_from_bitstamp("xrpusd"), 
        "EUR": get_last_price_from_bitstamp("eurusd"),
        "USD" : 1,
        "TST" : 8.5
    }
    return rates

if __name__ == "__main__":
    rates = get_exchange_rates()
    print(rates)
