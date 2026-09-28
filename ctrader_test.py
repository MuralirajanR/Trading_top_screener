import os

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
REFRESH_TOKEN = os.getenv("CTRADER_REFRESH_TOKEN")

print("=== TRADING_TOP cTrader Test ===")

print("Client ID:", "OK" if CLIENT_ID else "MISSING")
print("Client Secret:", "OK" if CLIENT_SECRET else "MISSING")
print("Access Token:", "OK" if ACCESS_TOKEN else "MISSING")
print("Refresh Token:", "OK" if REFRESH_TOKEN else "MISSING")

if all([
    CLIENT_ID,
    CLIENT_SECRET,
    ACCESS_TOKEN,
    REFRESH_TOKEN
]):
    print("SUCCESS: All cTrader credentials loaded.")
else:
    print("ERROR: One or more cTrader credentials are missing.")
