import os
import time
from datetime import datetime, timezone

import requests

from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAAccountAuthReq,
    ProtoOASymbolsListReq,
    ProtoOAGetTrendbarsReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAPayloadType,
    ProtoOATrendbarPeriod,
)
from twisted.internet import reactor


# =========================================================
# TRADING_TOP - MULTI PAIR
# 5M >= 5X INJECTION + HOURLY REPORT
# =========================================================

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

VOL_LENGTH = 20
INJECTION_X = 5.0

HOURLY_REPORT = (
    os.getenv("HOURLY_REPORT", "false").lower() == "true"
)

WATCHLIST = [
    "XAUUSD",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "NZDUSD",
    "USDCAD",
    "EURGBP",
]

ACCOUNT_ID = None

# symbol name -> symbol id
SYMBOL_IDS = {}

# Request queue
REQUEST_QUEUE = []
CURRENT_SYMBOL = None

# Store hourly result for all instruments
HOURLY_RESULTS = {}


print("==========================================")
print(" TRADING_TOP - MULTI PAIR")
print(" 5M 5X INJECTION + HOURLY REPORT")
print("==========================================")

if not all([
    CLIENT_ID,
    CLIENT_SECRET,
    ACCESS_TOKEN,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
]):
    print("ERROR: Required environment variables missing.")
    raise SystemExit(1)


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )

        if response.ok:
            print("Telegram message: SENT")
        else:
            print(
                "Telegram ERROR:",
                response.status_code,
                response.text,
            )

    except Exception as error:
        print("Telegram exception:", error)


# =========================================================
# cTRADER
# =========================================================

client = Client(
    EndPoints.PROTOBUF_DEMO_HOST,
    EndPoints.PROTOBUF_PORT,
    TcpProtocol,
)


def stop_bot():

    if reactor.running:
        reactor.stop()


def request_error(failure):

    print("cTrader request ERROR:")
    print(failure)
    stop_bot()


def connected(client):

    print("1. Connected to cTrader DEMO server")

    request = ProtoOAApplicationAuthReq()
    request.clientId = CLIENT_ID
    request.clientSecret = CLIENT_SECRET

    deferred = client.send(request)
    deferred.addErrback(request_error)


def disconnected(client, reason):

    print("Disconnected from cTrader server")


# =========================================================
# SYMBOL NAME NORMALIZER
# =========================================================

def normalize_symbol(name):

    return (
        name.upper()
        .replace("/", "")
        .replace("\\", "")
        .replace("-", "")
        .replace("_", "")
        .replace(" ", "")
        .strip()
    )


# =========================================================
# SYMBOLS
# =========================================================

def request_symbols():

    request = ProtoOASymbolsListReq()
    request.ctidTraderAccountId = ACCOUNT_ID
    request.includeArchivedSymbols = False

    print("4. Requesting symbols...")

    deferred = client.send(request)
    deferred.addErrback(request_error)


# =========================================================
# REQUEST NEXT M5
# =========================================================

def request_next_m5():

    global CURRENT_SYMBOL

    if not REQUEST_QUEUE:

        print("")
        print("==========================================")
        print(" ALL INSTRUMENTS COMPLETED")
        print("==========================================")

        if HOURLY_REPORT:
            send_combined_hourly_report()

        stop_bot()
        return

    CURRENT_SYMBOL = REQUEST_QUEUE.pop(0)

    symbol_id = SYMBOL_IDS[CURRENT_SYMBOL]

    now_ms = int(time.time() * 1000)

    # 24 hours of M5 history
    from_ms = now_ms - (24 * 60 * 60 * 1000)

    request = ProtoOAGetTrendbarsReq()

    request.ctidTraderAccountId = ACCOUNT_ID
    request.symbolId = symbol_id
    request.period = ProtoOATrendbarPeriod.M5
    request.fromTimestamp = from_ms
    request.toTimestamp = now_ms
    request.count = 300

    print("")
    print(f"Requesting {CURRENT_SYMBOL} M5 history...")

    deferred = client.send(request)
    deferred.addErrback(request_error)


# =========================================================
# VOLUME RATIO
# =========================================================

def calculate_volume_x(completed_bars, index):

    if index < VOL_LENGTH:
        return None

    previous_20 = completed_bars[
        index - VOL_LENGTH:index
    ]

    avg_volume = (
        sum(bar.volume for bar in previous_20)
        / VOL_LENGTH
    )

    if avg_volume <= 0:
        return 0.0

    return (
        completed_bars[index].volume
        / avg_volume
    )


# =========================================================
# PRICE
# =========================================================

def get_prices(bar):

    low_raw = bar.low

    open_raw = (
        bar.low + bar.deltaOpen
    )

    high_raw = (
        bar.low + bar.deltaHigh
    )

    close_raw = (
        bar.low + bar.deltaClose
    )

    # Current cTrader feed uses 1/100000 representation.
    return (
        open_raw / 100000.0,
        high_raw / 100000.0,
        low_raw / 100000.0,
        close_raw / 100000.0,
    )


def get_direction(bar):

    open_price, _, _, close_price = get_prices(bar)

    if close_price > open_price:
        return "BULLISH"

    if close_price < open_price:
        return "BEARISH"

    return "DOJI"


# =========================================================
# DISPLAY PRICE
# =========================================================

def format_price(symbol, price):

    if symbol in ["USDJPY"]:
        return f"{price:.3f}"

    if symbol == "XAUUSD":
        return f"{price:.2f}"

    return f"{price:.5f}"


# =========================================================
# LATEST 5M INJECTION
# =========================================================

def check_latest_injection(symbol, completed):

    if len(completed) < VOL_LENGTH + 1:
        print(f"{symbol}: Not enough completed M5 bars.")
        return

    candidate_index = len(completed) - 1
    candidate = completed[candidate_index]

    volume_x = calculate_volume_x(
        completed,
        candidate_index,
    )

    if volume_x is None:
        return

    (
        open_price,
        high_price,
        low_price,
        close_price,
    ) = get_prices(candidate)

    direction = get_direction(candidate)

    candle_time = datetime.fromtimestamp(
        candidate.utcTimestampInMinutes * 60,
        tz=timezone.utc,
    )

    candle_time_text = candle_time.strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    previous_20 = completed[
        candidate_index - VOL_LENGTH:
        candidate_index
    ]

    average_volume = (
        sum(bar.volume for bar in previous_20)
        / VOL_LENGTH
    )

    print("")
    print("------------------------------------------")
    print(f"LATEST COMPLETED {symbol} M5")
    print("------------------------------------------")

    print("Time:", candle_time_text)
    print("Direction:", direction)

    print(
        "Open:",
        format_price(symbol, open_price),
    )

    print(
        "High:",
        format_price(symbol, high_price),
    )

    print(
        "Low:",
        format_price(symbol, low_price),
    )

    print(
        "Close:",
        format_price(symbol, close_price),
    )

    print("Tick Volume:", candidate.volume)

    print(
        "20 Candle Avg:",
        round(average_volume, 2),
    )

    print(
        "Volume Ratio:",
        f"{volume_x:.2f}X",
    )

    # -----------------------------------------------------
    # 5X BULLISH
    # -----------------------------------------------------

    if (
        direction == "BULLISH"
        and volume_x >= INJECTION_X
    ):

        print(f"🔥 {symbol} BUY 5X+ INJECTION")

        message = (
            f"🚨 TRADING_TOP — {symbol}\n\n"
            "🟢 5M BULLISH VOLUME INJECTION\n\n"
            f"🔥 Volume: {volume_x:.2f}X\n"
            f"📍 Injection Open: "
            f"{format_price(symbol, open_price)}\n"
            f"📈 High: "
            f"{format_price(symbol, high_price)}\n"
            f"📉 Low: "
            f"{format_price(symbol, low_price)}\n"
            f"🔒 Close: "
            f"{format_price(symbol, close_price)}\n\n"
            f"🕐 {candle_time_text}\n\n"
            "⏳ Waiting for 1M retest + confirmation..."
        )

        send_telegram(message)

    # -----------------------------------------------------
    # 5X BEARISH
    # -----------------------------------------------------

    elif (
        direction == "BEARISH"
        and volume_x >= INJECTION_X
    ):

        print(f"🔥 {symbol} SELL 5X+ INJECTION")

        message = (
            f"🚨 TRADING_TOP — {symbol}\n\n"
            "🔴 5M BEARISH VOLUME INJECTION\n\n"
            f"🔥 Volume: {volume_x:.2f}X\n"
            f"📍 Injection Open: "
            f"{format_price(symbol, open_price)}\n"
            f"📈 High: "
            f"{format_price(symbol, high_price)}\n"
            f"📉 Low: "
            f"{format_price(symbol, low_price)}\n"
            f"🔒 Close: "
            f"{format_price(symbol, close_price)}\n\n"
            f"🕐 {candle_time_text}\n\n"
            "⏳ Waiting for 1M retest + confirmation..."
        )

        send_telegram(message)

    else:

        print(
            f"{symbol}: NO "
            f"{INJECTION_X:.0f}X INJECTION"
        )


# =========================================================
# CALCULATE HOURLY DATA FOR ONE SYMBOL
# =========================================================

def calculate_hourly_data(symbol, completed):

    now_minutes = int(time.time() // 60)
    one_hour_ago = now_minutes - 60

    results = []

    for index in range(
        VOL_LENGTH,
        len(completed),
    ):

        bar = completed[index]

        if (
            bar.utcTimestampInMinutes
            < one_hour_ago
        ):
            continue

        volume_x = calculate_volume_x(
            completed,
            index,
        )

        if volume_x is None:
            continue

        results.append(
            {
                "volume_x": volume_x,
                "direction": get_direction(bar),
            }
        )

    total_5x = 0
    bullish_5x = 0
    bearish_5x = 0
    highest_x = 0.0

    for item in results:

        volume_x = item["volume_x"]
        direction = item["direction"]

        highest_x = max(
            highest_x,
            volume_x,
        )

        if volume_x >= INJECTION_X:

            if direction == "BULLISH":
                bullish_5x += 1
                total_5x += 1

            elif direction == "BEARISH":
                bearish_5x += 1
                total_5x += 1

    HOURLY_RESULTS[symbol] = {
        "total_5x": total_5x,
        "bullish_5x": bullish_5x,
        "bearish_5x": bearish_5x,
        "highest_x": highest_x,
        "checked": len(results),
    }


# =========================================================
# COMBINED HOURLY REPORT
# =========================================================

def send_combined_hourly_report():

    utc_now = datetime.now(
        timezone.utc
    )

    total_injections = sum(
        item["total_5x"]
        for item in HOURLY_RESULTS.values()
    )

    total_bullish = sum(
        item["bullish_5x"]
        for item in HOURLY_RESULTS.values()
    )

    total_bearish = sum(
        item["bearish_5x"]
        for item in HOURLY_RESULTS.values()
    )

    lines = [
        "📊 TRADING_TOP — HOURLY REPORT",
        "",
        "⏱ Last 1 Hour",
        "",
    ]

    emojis = {
        "XAUUSD": "🥇",
        "EURUSD": "💶",
        "GBPUSD": "💷",
        "USDJPY": "🇯🇵",
        "USDCHF": "🇨🇭",
        "AUDUSD": "🇦🇺",
        "NZDUSD": "🇳🇿",
        "USDCAD": "🇨🇦",
        "EURGBP": "🇪🇺",
    }

    for symbol in WATCHLIST:

        if symbol not in HOURLY_RESULTS:
            lines.append(
                f"⚠️ {symbol}: No data"
            )
            continue

        data = HOURLY_RESULTS[symbol]

        fire = (
            " 🔥"
            if data["total_5x"] > 0
            else ""
        )

        lines.append(
            f"{emojis.get(symbol, '📈')} "
            f"{symbol}: "
            f"{data['highest_x']:.2f}X"
            f"{fire}"
        )

    lines.extend([
        "",
        f"🔥 5X+ Injections: {total_injections}",
        f"🟢 Bullish: {total_bullish}",
        f"🔴 Bearish: {total_bearish}",
        "",
        f"📡 Instruments: "
        f"{len(HOURLY_RESULTS)}/{len(WATCHLIST)}",
        "✅ Bot Status: ACTIVE",
        f"🕐 {utc_now.strftime('%Y-%m-%d %H:%M UTC')}",
    ])

    message = "\n".join(lines)

    print("")
    print("==========================================")
    print("COMBINED HOURLY REPORT")
    print("==========================================")
    print(message)

    send_telegram(message)


# =========================================================
# PROCESS M5 RESPONSE
# =========================================================

def process_m5_response(symbol, bars):

    bars.sort(
        key=lambda bar:
        bar.utcTimestampInMinutes
    )

    now_minutes = int(
        time.time() // 60
    )

    current_m5_open = (
        now_minutes // 5
    ) * 5

    completed = [
        bar
        for bar in bars
        if (
            bar.utcTimestampInMinutes
            < current_m5_open
        )
    ]

    if len(completed) < VOL_LENGTH + 1:

        print(
            f"ERROR: {symbol} does not have "
            "enough completed M5 history."
        )

        return

    # Latest 5M 5X detector
    check_latest_injection(
        symbol,
        completed,
    )

    # Hourly statistics
    if HOURLY_REPORT:

        calculate_hourly_data(
            symbol,
            completed,
        )


# =========================================================
# MESSAGE HANDLER
# =========================================================

def on_message_received(client, message):

    global ACCOUNT_ID

    payload_type = message.payloadType

    # -----------------------------------------------------
    # APPLICATION AUTH
    # -----------------------------------------------------

    if (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES
    ):

        print(
            "2. Application authentication: SUCCESS"
        )

        request = (
            ProtoOAGetAccountListByAccessTokenReq()
        )

        request.accessToken = ACCESS_TOKEN

        deferred = client.send(request)
        deferred.addErrback(request_error)

    # -----------------------------------------------------
    # ACCOUNT LIST
    # -----------------------------------------------------

    elif (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_RES
    ):

        response = Protobuf.extract(message)

        demo_account = None

        for account in response.ctidTraderAccount:

            if not account.isLive:
                demo_account = account
                break

        if demo_account is None:

            print("ERROR: No DEMO account found.")
            stop_bot()
            return

        ACCOUNT_ID = int(
            demo_account.ctidTraderAccountId
        )

        print("3. DEMO account found")

        request = ProtoOAAccountAuthReq()

        request.ctidTraderAccountId = ACCOUNT_ID
        request.accessToken = ACCESS_TOKEN

        deferred = client.send(request)
        deferred.addErrback(request_error)

    # -----------------------------------------------------
    # ACCOUNT AUTH
    # -----------------------------------------------------

    elif (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES
    ):

        print(
            "   Account authentication: SUCCESS"
        )

        request_symbols()

    # -----------------------------------------------------
    # SYMBOL LIST
    # -----------------------------------------------------

    elif (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_SYMBOLS_LIST_RES
    ):

        response = Protobuf.extract(message)

        all_symbols = list(response.symbol)

        for wanted in WATCHLIST:

            found = None

            # Exact normalized match first
            for symbol in all_symbols:

                normalized = normalize_symbol(
                    symbol.symbolName
                )

                if normalized == wanted:
                    found = symbol
                    break

            # XAUUSD fallback
            if (
                found is None
                and wanted == "XAUUSD"
            ):

                for symbol in all_symbols:

                    normalized = normalize_symbol(
                        symbol.symbolName
                    )

                    if (
                        "XAUUSD" in normalized
                        or "GOLD" in normalized
                    ):
                        found = symbol
                        break

            if found is not None:

                SYMBOL_IDS[wanted] = int(
                    found.symbolId
                )

                print(
                    f"5. {wanted} found:",
                    found.symbolName,
                )

            else:

                print(
                    f"WARNING: {wanted} "
                    "not available on this account."
                )

        if not SYMBOL_IDS:

            print(
                "ERROR: None of the watchlist "
                "symbols were found."
            )

            stop_bot()
            return

        REQUEST_QUEUE.extend([
            symbol
            for symbol in WATCHLIST
            if symbol in SYMBOL_IDS
        ])

        print("")
        print(
            "Symbols ready:",
            ", ".join(REQUEST_QUEUE),
        )

        request_next_m5()

    # -----------------------------------------------------
    # M5 DATA
    # -----------------------------------------------------

    elif (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_GET_TRENDBARS_RES
    ):

        response = Protobuf.extract(message)

        bars = list(
            response.trendbar
        )

        symbol = CURRENT_SYMBOL

        print(
            f"{symbol}: Received "
            f"{len(bars)} M5 bars"
        )

        process_m5_response(
            symbol,
            bars,
        )

        # Move to next instrument
        request_next_m5()

    # -----------------------------------------------------
    # API ERROR
    # -----------------------------------------------------

    elif (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_ERROR_RES
    ):

        response = Protobuf.extract(message)

        print("cTrader API ERROR")

        if hasattr(response, "errorCode"):
            print(
                "Error code:",
                response.errorCode,
            )

        if hasattr(response, "description"):
            print(
                "Description:",
                response.description,
            )

        stop_bot()


# =========================================================
# CALLBACKS
# =========================================================

client.setConnectedCallback(
    connected
)

client.setDisconnectedCallback(
    disconnected
)

client.setMessageReceivedCallback(
    on_message_received
)


# =========================================================
# START
# =========================================================

client.startService()


def timeout():

    print(
        "ERROR: Bot timed out after 90 seconds."
    )

    stop_bot()


# More time because 9 instruments are scanned sequentially.
reactor.callLater(
    90,
    timeout
)

reactor.run()