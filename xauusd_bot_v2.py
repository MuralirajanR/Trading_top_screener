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
# TRADING_TOP - XAUUSD
# 5M >= 5X INJECTION + HOURLY TELEGRAM REPORT
# =========================================================

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

VOL_LENGTH = 20
INJECTION_X = 5.0

# Set this TRUE only for the separate hourly scheduler/job run.
HOURLY_REPORT = (
    os.getenv("HOURLY_REPORT", "false").lower() == "true"
)

ACCOUNT_ID = None
XAUUSD_SYMBOL_ID = None


print("==========================================")
print(" TRADING_TOP - XAUUSD")
print(" 5M INJECTION + HOURLY REPORT")
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
# M5 HISTORY
# =========================================================

def request_m5():

    now_ms = int(time.time() * 1000)

    # 24 hours gives plenty of history for
    # previous-20 calculations.
    from_ms = now_ms - (24 * 60 * 60 * 1000)

    request = ProtoOAGetTrendbarsReq()

    request.ctidTraderAccountId = ACCOUNT_ID
    request.symbolId = XAUUSD_SYMBOL_ID
    request.period = ProtoOATrendbarPeriod.M5

    request.fromTimestamp = from_ms
    request.toTimestamp = now_ms
    request.count = 300

    print("6. Requesting XAUUSD M5 history...")

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
# HOURLY REPORT
# =========================================================

def send_hourly_report(completed):

    now_minutes = int(time.time() // 60)

    # Last 60 minutes of completed bars.
    one_hour_ago = now_minutes - 60

    hourly_results = []

    for index in range(VOL_LENGTH, len(completed)):

        bar = completed[index]

        if bar.utcTimestampInMinutes < one_hour_ago:
            continue

        volume_x = calculate_volume_x(
            completed,
            index,
        )

        if volume_x is None:
            continue

        direction = get_direction(bar)

        hourly_results.append(
            {
                "bar": bar,
                "volume_x": volume_x,
                "direction": direction,
            }
        )


    bullish_5x = 0
    bearish_5x = 0
    total_5x = 0

    highest_x = 0.0

    for item in hourly_results:

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


    utc_now = datetime.now(
        timezone.utc
    )

    message = (
        "📊 TRADING_TOP — XAUUSD HOURLY REPORT\n\n"
        "⏱ Last 1 Hour\n"
        f"🔥 5X+ Injections: {total_5x}\n"
        f"🟢 Bullish: {bullish_5x}\n"
        f"🔴 Bearish: {bearish_5x}\n\n"
        f"📈 Highest Volume: {highest_x:.2f}X\n"
        f"📊 Completed 5M Candles Checked: "
        f"{len(hourly_results)}\n\n"
        "✅ Bot Status: ACTIVE\n"
        f"🕐 {utc_now.strftime('%Y-%m-%d %H:%M UTC')}"
    )

    print("")
    print("HOURLY REPORT")
    print(message)

    send_telegram(message)


# =========================================================
# LATEST 5M INJECTION CHECK
# =========================================================

def check_latest_injection(completed):

    if len(completed) < VOL_LENGTH + 1:
        print("ERROR: Not enough completed M5 bars.")
        return


    candidate_index = len(completed) - 1
    candidate = completed[candidate_index]

    volume_x = calculate_volume_x(
        completed,
        candidate_index,
    )

    if volume_x is None:
        print("ERROR: Cannot calculate volume ratio.")
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
    print("==========================================")
    print("LATEST COMPLETED XAUUSD M5")
    print("==========================================")

    print("Time:", candle_time_text)
    print("Direction:", direction)

    print("Open:", round(open_price, 5))
    print("High:", round(high_price, 5))
    print("Low:", round(low_price, 5))
    print("Close:", round(close_price, 5))

    print("Tick Volume:", candidate.volume)

    print(
        "20 Candle Avg:",
        round(average_volume, 2),
    )

    print(
        "Volume Ratio:",
        f"{volume_x:.2f}X",
    )


    # =====================================================
    # BUY INJECTION
    # =====================================================

    if (
        direction == "BULLISH"
        and volume_x >= INJECTION_X
    ):

        print("🔥 BUY 5X+ INJECTION DETECTED")

        message = (
            "🚨 TRADING_TOP — XAUUSD\n\n"
            "🟢 5M BULLISH VOLUME INJECTION\n\n"
            f"🔥 Volume: {volume_x:.2f}X\n"
            f"📍 Injection Open: {open_price:.2f}\n"
            f"📈 High: {high_price:.2f}\n"
            f"📉 Low: {low_price:.2f}\n"
            f"🔒 Close: {close_price:.2f}\n\n"
            f"🕐 {candle_time_text}\n\n"
            "⏳ Waiting for 1M retest + confirmation..."
        )

        send_telegram(message)


    # =====================================================
    # SELL INJECTION
    # =====================================================

    elif (
        direction == "BEARISH"
        and volume_x >= INJECTION_X
    ):

        print("🔥 SELL 5X+ INJECTION DETECTED")

        message = (
            "🚨 TRADING_TOP — XAUUSD\n\n"
            "🔴 5M BEARISH VOLUME INJECTION\n\n"
            f"🔥 Volume: {volume_x:.2f}X\n"
            f"📍 Injection Open: {open_price:.2f}\n"
            f"📈 High: {high_price:.2f}\n"
            f"📉 Low: {low_price:.2f}\n"
            f"🔒 Close: {close_price:.2f}\n\n"
            f"🕐 {candle_time_text}\n\n"
            "⏳ Waiting for 1M retest + confirmation..."
        )

        send_telegram(message)


    else:

        print(
            f"NO {INJECTION_X:.0f}X "
            "VOLUME INJECTION"
        )

        print(
            "Telegram trading alert: NOT SENT"
        )


# =========================================================
# MESSAGE HANDLER
# =========================================================

def on_message_received(client, message):

    global ACCOUNT_ID
    global XAUUSD_SYMBOL_ID

    payload_type = message.payloadType


    # APPLICATION AUTH
    if (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES
    ):

        print("2. Application authentication: SUCCESS")

        request = (
            ProtoOAGetAccountListByAccessTokenReq()
        )

        request.accessToken = ACCESS_TOKEN

        deferred = client.send(request)
        deferred.addErrback(request_error)


    # ACCOUNT LIST
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


    # ACCOUNT AUTH
    elif (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES
    ):

        print("   Account authentication: SUCCESS")

        request_symbols()


    # SYMBOL LIST
    elif (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_SYMBOLS_LIST_RES
    ):

        response = Protobuf.extract(message)

        found_symbol = None


        for symbol in response.symbol:

            name = (
                symbol.symbolName
                .upper()
                .replace("/", "")
                .strip()
            )

            if name == "XAUUSD":

                found_symbol = symbol
                break


        if found_symbol is None:

            for symbol in response.symbol:

                name = symbol.symbolName.upper()

                if (
                    "XAU" in name
                    or "GOLD" in name
                ):

                    found_symbol = symbol
                    break


        if found_symbol is None:

            print("ERROR: XAUUSD/GOLD symbol not found.")
            stop_bot()
            return


        XAUUSD_SYMBOL_ID = int(
            found_symbol.symbolId
        )

        print(
            "5. XAUUSD symbol found:",
            found_symbol.symbolName,
        )

        request_m5()


    # M5 DATA
    elif (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_GET_TRENDBARS_RES
    ):

        response = Protobuf.extract(message)

        bars = list(
            response.trendbar
        )

        bars.sort(
            key=lambda bar:
            bar.utcTimestampInMinutes
        )


        # -----------------------------------------------
        # COMPLETED M5 CANDLES ONLY
        # -----------------------------------------------

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
                "ERROR: Not enough completed M5 history."
            )

            stop_bot()
            return


        # -----------------------------------------------
        # NORMAL 5M DETECTOR
        # -----------------------------------------------

        check_latest_injection(
            completed
        )


        # -----------------------------------------------
        # HOURLY REPORT MODE
        # -----------------------------------------------

        if HOURLY_REPORT:

            send_hourly_report(
                completed
            )


        stop_bot()


    # API ERROR
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
        "ERROR: Bot timed out after 45 seconds."
    )

    stop_bot()


reactor.callLater(
    45,
    timeout
)

reactor.run()
