import os
import time
from datetime import datetime, timezone

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
# TRADING_TOP
# cTrader XAUUSD 5M DATA + VOLUME TEST
# =========================================================

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")

ACCOUNT_ID = None
XAUUSD_SYMBOL_ID = None

VOL_LENGTH = 20
INJECTION_X = 5.0


print("==========================================")
print(" TRADING_TOP - XAUUSD 5M DATA TEST")
print("==========================================")


# =========================================================
# CHECK CREDENTIALS
# =========================================================

if not all([
    CLIENT_ID,
    CLIENT_SECRET,
    ACCESS_TOKEN
]):
    print("ERROR: cTrader credentials missing.")
    raise SystemExit(1)


# =========================================================
# CLIENT
# =========================================================

client = Client(
    EndPoints.PROTOBUF_DEMO_HOST,
    EndPoints.PROTOBUF_PORT,
    TcpProtocol
)


def stop_test():
    if reactor.running:
        reactor.stop()


def on_error(failure):
    print("ERROR:")
    print(failure)
    stop_test()


# =========================================================
# CONNECTED
# =========================================================

def connected(client):

    print("1. Connected to cTrader DEMO server")

    req = ProtoOAApplicationAuthReq()
    req.clientId = CLIENT_ID
    req.clientSecret = CLIENT_SECRET

    d = client.send(req)
    d.addErrback(on_error)


def disconnected(client, reason):
    print("Disconnected from cTrader server")


# =========================================================
# REQUEST SYMBOL LIST
# =========================================================

def request_symbols():

    req = ProtoOASymbolsListReq()

    req.ctidTraderAccountId = ACCOUNT_ID
    req.includeArchivedSymbols = False

    print("4. Requesting symbol list...")

    d = client.send(req)
    d.addErrback(on_error)


# =========================================================
# REQUEST 5M BARS
# =========================================================

def request_5m_bars():

    # Ask for enough historical time so we have
    # more than 20 completed M5 bars.
    now_ms = int(time.time() * 1000)

    # Previous 24 hours
    from_ms = now_ms - (24 * 60 * 60 * 1000)

    req = ProtoOAGetTrendbarsReq()

    req.ctidTraderAccountId = ACCOUNT_ID
    req.symbolId = XAUUSD_SYMBOL_ID

    req.period = ProtoOATrendbarPeriod.M5

    req.fromTimestamp = from_ms
    req.toTimestamp = now_ms

    # Need 20 previous bars + current candidate.
    # Fetch extra bars for safety.
    req.count = 50

    print("6. Requesting XAUUSD completed 5M candles...")

    d = client.send(req)
    d.addErrback(on_error)


# =========================================================
# PROCESS MESSAGES
# =========================================================

def on_message_received(client, message):

    global ACCOUNT_ID
    global XAUUSD_SYMBOL_ID

    payload_type = message.payloadType


    # =====================================================
    # APPLICATION AUTH
    # =====================================================

    if payload_type == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:

        print("2. Application authentication: SUCCESS")

        req = ProtoOAGetAccountListByAccessTokenReq()
        req.accessToken = ACCESS_TOKEN

        d = client.send(req)
        d.addErrback(on_error)


    # =====================================================
    # ACCOUNT LIST
    # =====================================================

    elif payload_type == ProtoOAPayloadType.PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_RES:

        response = Protobuf.extract(message)

        demo_account = None

        for account in response.ctidTraderAccount:

            if not account.isLive:
                demo_account = account
                break

        if demo_account is None:

            print("ERROR: No DEMO account found.")
            stop_test()
            return

        ACCOUNT_ID = int(
            demo_account.ctidTraderAccountId
        )

        print("3. DEMO account found")

        req = ProtoOAAccountAuthReq()

        req.ctidTraderAccountId = ACCOUNT_ID
        req.accessToken = ACCESS_TOKEN

        d = client.send(req)
        d.addErrback(on_error)


    # =====================================================
    # ACCOUNT AUTH
    # =====================================================

    elif payload_type == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:

        print("   Account authentication: SUCCESS")

        request_symbols()


    # =====================================================
    # SYMBOL LIST
    # =====================================================

    elif payload_type == ProtoOAPayloadType.PROTO_OA_SYMBOLS_LIST_RES:

        response = Protobuf.extract(message)

        print(
            "5. Symbols received:",
            len(response.symbol)
        )

        found_symbol = None

        # Different brokers may name gold differently.
        possible_names = {
            "XAUUSD",
            "GOLD",
            "XAU/USD",
        }

        for symbol in response.symbol:

            symbol_name = symbol.symbolName.upper().strip()

            if symbol_name in possible_names:

                found_symbol = symbol
                break


        # Fallback:
        # Find any symbol containing XAUUSD.
        if found_symbol is None:

            for symbol in response.symbol:

                symbol_name = symbol.symbolName.upper()

                if "XAUUSD" in symbol_name:

                    found_symbol = symbol
                    break


        if found_symbol is None:

            print("ERROR: XAUUSD/GOLD symbol not found.")

            print("Gold-like symbols available:")

            for symbol in response.symbol:

                name = symbol.symbolName.upper()

                if (
                    "XAU" in name
                    or "GOLD" in name
                ):
                    print(" -", symbol.symbolName)

            stop_test()
            return


        XAUUSD_SYMBOL_ID = int(
            found_symbol.symbolId
        )

        print(
            "   XAUUSD symbol found:",
            found_symbol.symbolName
        )

        print(
            "   Symbol ID: FOUND"
        )

        request_5m_bars()


    # =====================================================
    # 5M TREND BARS
    # =====================================================

    elif payload_type == ProtoOAPayloadType.PROTO_OA_GET_TRENDBARS_RES:

        response = Protobuf.extract(message)

        bars = list(response.trendbar)

        if len(bars) < VOL_LENGTH + 1:

            print(
                "ERROR: Not enough 5M candles."
            )

            print(
                "Candles received:",
                len(bars)
            )

            stop_test()
            return


        # Sort oldest -> newest
        bars.sort(
            key=lambda x: x.utcTimestampInMinutes
        )


        # -------------------------------------------------
        # Remove still-forming 5M candle if present
        # -------------------------------------------------

        now_minutes = int(time.time() // 60)

        current_5m_open = (
            now_minutes // 5
        ) * 5

        completed_bars = [
            bar
            for bar in bars
            if bar.utcTimestampInMinutes < current_5m_open
        ]


        if len(completed_bars) < VOL_LENGTH + 1:

            print(
                "ERROR: Not enough completed 5M candles."
            )

            stop_test()
            return


        # Latest COMPLETED M5 candle = candidate injection
        injection_bar = completed_bars[-1]

        # Previous 20 completed M5 candles
        previous_20 = completed_bars[
            -(VOL_LENGTH + 1):-1
        ]


        # =================================================
        # PRICE CONVERSION
        # =================================================

        low_raw = injection_bar.low

        open_raw = (
            injection_bar.low
            + injection_bar.deltaOpen
        )

        close_raw = (
            injection_bar.low
            + injection_bar.deltaClose
        )

        high_raw = (
            injection_bar.low
            + injection_bar.deltaHigh
        )


        low_price = low_raw / 100000.0
        open_price = open_raw / 100000.0
        close_price = close_raw / 100000.0
        high_price = high_raw / 100000.0


        # =================================================
        # VOLUME CALCULATION
        # =================================================

        injection_volume = injection_bar.volume

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
                injection_volume
                / average_volume
            )

        else:

            volume_x = 0


        # =================================================
        # CANDLE DIRECTION
        # =================================================

        if close_price > open_price:

            direction = "BULLISH"

        elif close_price < open_price:

            direction = "BEARISH"

        else:

            direction = "DOJI"


        # =================================================
        # CANDLE TIME
        # =================================================

        candle_time = datetime.fromtimestamp(
            injection_bar.utcTimestampInMinutes * 60,
            tz=timezone.utc
        )


        # =================================================
        # OUTPUT
        # =================================================

        print("")
        print("==========================================")
        print(" XAUUSD LATEST COMPLETED 5M CANDLE")
        print("==========================================")

        print(
            "UTC Time:",
            candle_time.strftime(
                "%Y-%m-%d %H:%M"
            )
        )

        print(
            "Direction:",
            direction
        )

        print(
            "Open:",
            round(open_price, 5)
        )

        print(
            "High:",
            round(high_price, 5)
        )

        print(
            "Low:",
            round(low_price, 5)
        )

        print(
            "Close:",
            round(close_price, 5)
        )

        print(
            "Tick Volume:",
            injection_volume
        )

        print(
            "Previous 20 Avg Volume:",
            round(average_volume, 2)
        )

        print(
            "Volume Ratio:",
            f"{volume_x:.2f}X"
        )


        # =================================================
        # 5X INJECTION CHECK
        # =================================================

        print("")
        print("==========================================")


        if (
            direction == "BULLISH"
            and volume_x >= INJECTION_X
        ):

            print("🔥 5M BUY VOLUME INJECTION DETECTED")
            print(
                f"Volume: {volume_x:.2f}X"
            )


        elif (
            direction == "BEARISH"
            and volume_x >= INJECTION_X
        ):

            print("🔥 5M SELL VOLUME INJECTION DETECTED")
            print(
                f"Volume: {volume_x:.2f}X"
            )


        else:

            print(
                "NO 5X VOLUME INJECTION"
            )

            print(
                "No trading alert should be sent."
            )


        print("==========================================")

        stop_test()


    # =====================================================
    # API ERROR
    # =====================================================

    elif payload_type == ProtoOAPayloadType.PROTO_OA_ERROR_RES:

        response = Protobuf.extract(message)

        print("cTrader API ERROR")

        if hasattr(response, "errorCode"):
            print(
                "Error code:",
                response.errorCode
            )

        if hasattr(response, "description"):
            print(
                "Description:",
                response.description
            )

        stop_test()


# =========================================================
# CALLBACKS
# =========================================================

client.setConnectedCallback(connected)

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


# =========================================================
# TIMEOUT
# =========================================================

def timeout():

    print(
        "ERROR: Test timed out after 45 seconds."
    )

    stop_test()


reactor.callLater(
    45,
    timeout
)

reactor.run()
