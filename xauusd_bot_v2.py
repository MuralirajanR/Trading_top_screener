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
# TRADING_TOP - XAUUSD STAGE 1
# 5M >= 5X VOLUME INJECTION + TELEGRAM
# =========================================================

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

VOL_LENGTH = 20
INJECTION_X = 5.0

ACCOUNT_ID = None
XAUUSD_SYMBOL_ID = None


# =========================================================
# START
# =========================================================

print("==========================================")
print(" TRADING_TOP - XAUUSD STAGE 1")
print(" 5M VOLUME INJECTION DETECTOR")
print("==========================================")


required = [
    CLIENT_ID,
    CLIENT_SECRET,
    ACCESS_TOKEN,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
]

if not all(required):
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

        print(
            "Telegram exception:",
            error,
        )


# =========================================================
# cTRADER CLIENT
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


# =========================================================
# CONNECT
# =========================================================

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
# SYMBOL LIST
# =========================================================

def request_symbols():

    request = ProtoOASymbolsListReq()

    request.ctidTraderAccountId = ACCOUNT_ID
    request.includeArchivedSymbols = False

    print("4. Requesting symbols...")

    deferred = client.send(request)
    deferred.addErrback(request_error)


# =========================================================
# REQUEST M5 DATA
# =========================================================

def request_m5():

    now_ms = int(
        time.time() * 1000
    )

    # Fetch enough history for 20 previous completed candles
    from_ms = (
        now_ms
        - (24 * 60 * 60 * 1000)
    )

    request = ProtoOAGetTrendbarsReq()

    request.ctidTraderAccountId = ACCOUNT_ID
    request.symbolId = XAUUSD_SYMBOL_ID

    request.period = (
        ProtoOATrendbarPeriod.M5
    )

    request.fromTimestamp = from_ms
    request.toTimestamp = now_ms

    request.count = 60

    print("6. Requesting XAUUSD M5 data...")

    deferred = client.send(request)
    deferred.addErrback(request_error)


# =========================================================
# MESSAGE HANDLER
# =========================================================

def on_message_received(client, message):

    global ACCOUNT_ID
    global XAUUSD_SYMBOL_ID

    payload_type = message.payloadType


    # =====================================================
    # APPLICATION AUTH
    # =====================================================

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


    # =====================================================
    # ACCOUNT LIST
    # =====================================================

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


    # =====================================================
    # ACCOUNT AUTH
    # =====================================================

    elif (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES
    ):

        print(
            "   Account authentication: SUCCESS"
        )

        request_symbols()


    # =====================================================
    # SYMBOL LIST
    # =====================================================

    elif (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_SYMBOLS_LIST_RES
    ):

        response = Protobuf.extract(message)

        found_symbol = None


        # Primary search
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


        # Gold fallback
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

            print(
                "ERROR: XAUUSD/GOLD symbol not found."
            )

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


    # =====================================================
    # M5 DATA
    # =====================================================

    elif (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_GET_TRENDBARS_RES
    ):

        response = Protobuf.extract(message)

        bars = list(
            response.trendbar
        )


        if len(bars) < VOL_LENGTH + 1:

            print(
                "ERROR: Not enough M5 bars:",
                len(bars),
            )

            stop_bot()
            return


        # Oldest -> newest
        bars.sort(
            key=lambda bar:
            bar.utcTimestampInMinutes
        )


        # =================================================
        # COMPLETED M5 CANDLES ONLY
        # =================================================

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
                "ERROR: Not enough completed M5 bars."
            )

            stop_bot()
            return


        # Latest completed M5 candle
        candidate = completed[-1]

        # Previous 20 COMPLETED M5 candles
        previous_20 = completed[
            -(VOL_LENGTH + 1):-1
        ]


        # =================================================
        # PRICE
        # =================================================

        low_raw = candidate.low

        open_raw = (
            candidate.low
            + candidate.deltaOpen
        )

        high_raw = (
            candidate.low
            + candidate.deltaHigh
        )

        close_raw = (
            candidate.low
            + candidate.deltaClose
        )


        open_price = (
            open_raw / 100000.0
        )

        high_price = (
            high_raw / 100000.0
        )

        low_price = (
            low_raw / 100000.0
        )

        close_price = (
            close_raw / 100000.0
        )


        # =================================================
        # VOLUME
        # =================================================

        candidate_volume = (
            candidate.volume
        )


        previous_volumes = [

            bar.volume
            for bar in previous_20

        ]


        average_volume = (
            sum(previous_volumes)
            / len(previous_volumes)
        )


        if average_volume > 0:

            volume_x = (
                candidate_volume
                / average_volume
            )

        else:

            volume_x = 0.0


        # =================================================
        # DIRECTION
        # =================================================

        if close_price > open_price:

            direction = "BULLISH"

        elif close_price < open_price:

            direction = "BEARISH"

        else:

            direction = "DOJI"


        # =================================================
        # TIME
        # =================================================

        candle_time = datetime.fromtimestamp(
            candidate.utcTimestampInMinutes * 60,
            tz=timezone.utc,
        )


        candle_time_text = (
            candle_time.strftime(
                "%Y-%m-%d %H:%M UTC"
            )
        )


        # =================================================
        # LOG
        # =================================================

        print("")
        print("==========================================")
        print("LATEST COMPLETED XAUUSD M5")
        print("==========================================")

        print(
            "Time:",
            candle_time_text,
        )

        print(
            "Direction:",
            direction,
        )

        print(
            "Open:",
            round(open_price, 5),
        )

        print(
            "High:",
            round(high_price, 5),
        )

        print(
            "Low:",
            round(low_price, 5),
        )

        print(
            "Close:",
            round(close_price, 5),
        )

        print(
            "Tick Volume:",
            candidate_volume,
        )

        print(
            "20 Candle Avg:",
            round(average_volume, 2),
        )

        print(
            "Volume Ratio:",
            f"{volume_x:.2f}X",
        )


        # =================================================
        # BUY 5X INJECTION
        # =================================================

        if (
            direction == "BULLISH"
            and volume_x >= INJECTION_X
        ):

            print(
                "🔥 BUY 5X INJECTION DETECTED"
            )


            telegram_message = (
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


            send_telegram(
                telegram_message
            )


        # =================================================
        # SELL 5X INJECTION
        # =================================================

        elif (
            direction == "BEARISH"
            and volume_x >= INJECTION_X
        ):

            print(
                "🔥 SELL 5X INJECTION DETECTED"
            )


            telegram_message = (
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


            send_telegram(
                telegram_message
            )


        # =================================================
        # NO INJECTION
        # =================================================

        else:

            print("")
            print(
                f"NO {INJECTION_X:.0f}X "
                "VOLUME INJECTION"
            )

            print(
                "Telegram trading alert: NOT SENT"
            )


        print("==========================================")


        stop_bot()


    # =====================================================
    # API ERROR
    # =====================================================

    elif (
        payload_type
        == ProtoOAPayloadType.PROTO_OA_ERROR_RES
    ):

        response = Protobuf.extract(message)

        print("cTrader API ERROR")

        if hasattr(
            response,
            "errorCode"
        ):

            print(
                "Error code:",
                response.errorCode,
            )

        if hasattr(
            response,
            "description"
        ):

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
# START SERVICE
# =========================================================

client.startService()


# =========================================================
# SAFETY TIMEOUT
# =========================================================

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
