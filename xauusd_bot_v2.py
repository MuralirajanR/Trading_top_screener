import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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
# MULTI-PAIR HOURLY REPORT + CHART
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


# =========================================================
# WATCHLIST
# =========================================================

WATCHLIST = [
    "XAUUSD",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "GBPJPY",
    "USDCHF",
    "AUDUSD",
    "NZDUSD",
    "USDCAD",
    "EURGBP",
]


EMOJIS = {
    "XAUUSD": "🥇",
    "EURUSD": "💶",
    "GBPUSD": "💷",
    "USDJPY": "🇯🇵",
    "GBPJPY": "💷",
    "USDCHF": "🇨🇭",
    "AUDUSD": "🇦🇺",
    "NZDUSD": "🇳🇿",
    "USDCAD": "🇨🇦",
    "EURGBP": "🇪🇺",
}


ACCOUNT_ID = None

SYMBOL_IDS = {}
REQUEST_QUEUE = []

CURRENT_SYMBOL = None

HOURLY_RESULTS = {}


print("==========================================")
print(" TRADING_TOP")
print(" MULTI-PAIR HOURLY MARKET REPORT")
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
# TELEGRAM TEXT
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
            timeout=20,
        )

        if response.ok:
            print("Telegram text: SENT")

        else:
            print(
                "Telegram text ERROR:",
                response.status_code,
                response.text,
            )

    except Exception as error:
        print("Telegram text exception:", error)


# =========================================================
# TELEGRAM PHOTO
# =========================================================

def send_telegram_photo(file_path, caption):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    )

    try:

        with open(file_path, "rb") as photo:

            response = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption,
                },
                files={
                    "photo": photo,
                },
                timeout=30,
            )

        if response.ok:
            print("Telegram chart: SENT")

        else:
            print(
                "Telegram chart ERROR:",
                response.status_code,
                response.text,
            )

    except Exception as error:
        print("Telegram chart exception:", error)


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
# SYMBOL NORMALIZER
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
# REQUEST NEXT M5
# =========================================================

def request_next_m5():

    global CURRENT_SYMBOL

    if not REQUEST_QUEUE:

        print("")
        print("==========================================")
        print(" ALL MARKET DATA COMPLETED")
        print("==========================================")

        if HOURLY_REPORT:
            send_hourly_report()

        else:
            print(
                "HOURLY_REPORT=false "
                "- report not sent."
            )

        stop_bot()
        return


    CURRENT_SYMBOL = REQUEST_QUEUE.pop(0)

    symbol_id = SYMBOL_IDS[CURRENT_SYMBOL]

    now_ms = int(time.time() * 1000)

    # 24 hours gives enough M5 candles
    # for previous-20 volume calculations.
    from_ms = (
        now_ms
        - (24 * 60 * 60 * 1000)
    )


    request = ProtoOAGetTrendbarsReq()

    request.ctidTraderAccountId = ACCOUNT_ID
    request.symbolId = symbol_id

    request.period = ProtoOATrendbarPeriod.M5

    request.fromTimestamp = from_ms
    request.toTimestamp = now_ms

    request.count = 300


    print("")
    print(
        f"Requesting {CURRENT_SYMBOL} M5 history..."
    )


    deferred = client.send(request)
    deferred.addErrback(request_error)


# =========================================================
# VOLUME X
# =========================================================

def calculate_volume_x(completed, index):

    if index < VOL_LENGTH:
        return None


    previous = completed[
        index - VOL_LENGTH:index
    ]


    average = (
        sum(
            bar.volume
            for bar in previous
        )
        / VOL_LENGTH
    )


    if average <= 0:
        return 0.0


    return (
        completed[index].volume
        / average
    )


# =========================================================
# PRICE + DIRECTION
# =========================================================

def get_prices(bar):

    low_raw = bar.low

    open_raw = (
        bar.low
        + bar.deltaOpen
    )

    high_raw = (
        bar.low
        + bar.deltaHigh
    )

    close_raw = (
        bar.low
        + bar.deltaClose
    )


    return (
        open_raw / 100000.0,
        high_raw / 100000.0,
        low_raw / 100000.0,
        close_raw / 100000.0,
    )


def get_direction(bar):

    open_price, _, _, close_price = (
        get_prices(bar)
    )


    if close_price > open_price:
        return "BULLISH"


    if close_price < open_price:
        return "BEARISH"


    return "DOJI"


# =========================================================
# PROCESS ONE SYMBOL
# =========================================================

def process_symbol(symbol, bars):

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
            f"{symbol}: Not enough "
            "completed M5 history."
        )

        return


    one_hour_ago = (
        now_minutes - 60
    )


    hourly_bars = []


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


        direction = get_direction(bar)


        hourly_bars.append({
            "bar": bar,
            "volume_x": volume_x,
            "direction": direction,
        })


    highest_x = 0.0

    total_5x = 0
    bullish_5x = 0
    bearish_5x = 0


    for item in hourly_bars:

        volume_x = item["volume_x"]
        direction = item["direction"]


        highest_x = max(
            highest_x,
            volume_x,
        )


        if volume_x >= INJECTION_X:

            total_5x += 1


            if direction == "BULLISH":
                bullish_5x += 1


            elif direction == "BEARISH":
                bearish_5x += 1


    # Latest completed M5 direction
    latest_direction = (
        get_direction(completed[-1])
    )


    HOURLY_RESULTS[symbol] = {
        "highest_x": highest_x,
        "total_5x": total_5x,
        "bullish_5x": bullish_5x,
        "bearish_5x": bearish_5x,
        "checked": len(hourly_bars),
        "latest_direction": latest_direction,
    }


    print(
        f"{symbol} | "
        f"Highest={highest_x:.2f}X | "
        f"5X+={total_5x} | "
        f"Checked={len(hourly_bars)}"
    )


# =========================================================
# TREND ICON
# =========================================================

def trend_icon(direction):

    if direction == "BULLISH":
        return "📈"

    if direction == "BEARISH":
        return "📉"

    return "🔃"


# =========================================================
# CHART
# =========================================================

def create_market_chart():

    available = [
        symbol
        for symbol in WATCHLIST
        if symbol in HOURLY_RESULTS
    ]


    if not available:
        return None


    values = [
        HOURLY_RESULTS[symbol]["highest_x"]
        for symbol in available
    ]


    labels = available


    fig, ax = plt.subplots(
        figsize=(11, 7)
    )


    bars = ax.bar(
        labels,
        values,
    )


    ax.axhline(
        y=INJECTION_X,
        linestyle="--",
        linewidth=2,
        label="5X Injection Level",
    )


    ax.set_title(
        "TRADING_TOP — HOURLY MARKET REPORT",
        fontsize=18,
        fontweight="bold",
        pad=20,
    )


    ax.set_ylabel(
        "Highest 5M Volume Ratio (X)"
    )


    ax.set_xlabel(
        "Market"
    )


    ax.grid(
        axis="y",
        alpha=0.25,
    )


    ax.legend()


    maximum = max(
        max(values),
        INJECTION_X,
    )


    ax.set_ylim(
        0,
        maximum * 1.25,
    )


    for bar, value in zip(
        bars,
        values,
    ):

        ax.text(
            bar.get_x()
            + bar.get_width() / 2,
            bar.get_height()
            + (maximum * 0.025),
            f"{value:.2f}X",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )


    plt.xticks(
        rotation=35,
        ha="right",
    )


    plt.tight_layout()


    path = "/tmp/trading_top_hourly.png"


    plt.savefig(
        path,
        dpi=160,
        bbox_inches="tight",
    )


    plt.close(fig)


    return path


# =========================================================
# HOURLY REPORT
# =========================================================

def send_hourly_report():

    # India Standard Time
    ist_now = datetime.now(
        ZoneInfo("Asia/Kolkata")
    )

    total_5x = sum(
        data["total_5x"]
        for data in HOURLY_RESULTS.values()
    )

    total_bullish = sum(
        data["bullish_5x"]
        for data in HOURLY_RESULTS.values()
    )

    total_bearish = sum(
        data["bearish_5x"]
        for data in HOURLY_RESULTS.values()
    )

    lines = [
        "📊 TRADING_TOP — HOURLY MARKET REPORT",
        "",
        "⏱ Last 1 Hour",
        "",
    ]

    for symbol in WATCHLIST:

        emoji = EMOJIS.get(
            symbol,
            "💹",
        )

        if symbol not in HOURLY_RESULTS:

            lines.append(
                f"{emoji} {symbol}   ⚠️ No Data"
            )

            lines.append("")
            continue

        data = HOURLY_RESULTS[symbol]

        direction = trend_icon(
            data["latest_direction"]
        )

        # 5X+ = 0  → 👎
        # 5X+ >= 1 → 👍
        injection_icon = (
            "👍"
            if data["total_5x"] >= 1
            else "👎"
        )

        lines.append(
            f"{emoji} {symbol}   "
            f"🔝 Highest: "
            f"{data['highest_x']:.2f}X "
            f"| 🎯 5X+: "
            f"{data['total_5x']} "
            f"{injection_icon} {direction}"
        )

        # Space between every market
        lines.append("")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"🔥 Total 5X+ Injections: {total_5x}",
        "",
        f"📈 Bullish 5X+: {total_bullish}",
        "",
        f"📉 Bearish 5X+: {total_bearish}",
        "",
        f"📊 Markets Scanned: "
        f"{len(HOURLY_RESULTS)}/{len(WATCHLIST)}",
        "",
        "🔃 Scanner: RUNNING",
        "",
        "👍 Scanner Status: ACTIVE",
        "",
        "⏩ Next Update: 1 Hour",
        "",
        f"🇮🇳 IST Time: "
        f"{ist_now.strftime('%d-%m-%Y | %I:%M %p')}",
        "",
        "🔥 SPOT THE VOLUME | CATCH THE MOVE",
        "— TRADING_IN_THE_TOP 📈🎯⚡",
    ])

    message = "\n".join(lines)

    print("")
    print("==========================================")
    print(" HOURLY REPORT")
    print("==========================================")
    print(message)

    # Send Telegram text report
    send_telegram(message)

    # Create + send chart
    chart_path = create_market_chart()

    if chart_path:

        caption = (
            "📊 TRADING_TOP — HOURLY VOLUME CHART\n\n"
            "🔝 Highest 5M Volume Ratio by Market\n"
            "🎯 Dashed line = 5X Injection Level\n\n"
            f"🔥 Total 5X+: {total_5x}\n"
            "👍 Scanner Status: ACTIVE\n\n"
            "🔥 SPOT THE VOLUME | CATCH THE MOVE\n"
            "— TRADING_IN_THE_TOP 📈🎯⚡"
        )

        send_telegram_photo(
            chart_path,
            caption,
        )

# =========================================================
# MESSAGE HANDLER
# =========================================================

def on_message_received(client, message):

    global ACCOUNT_ID
    global CURRENT_SYMBOL


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


        all_symbols = list(
            response.symbol
        )


        for wanted in WATCHLIST:

            found = None


            # Exact normalized match
            for symbol in all_symbols:

                normalized = normalize_symbol(
                    symbol.symbolName
                )


                if normalized == wanted:

                    found = symbol
                    break


            # Gold fallback
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
                    "not available."
                )


        if not SYMBOL_IDS:

            print(
                "ERROR: No watchlist symbols found."
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
            "Markets ready:",
            ", ".join(REQUEST_QUEUE),
        )


        request_next_m5()


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


        symbol = CURRENT_SYMBOL


        print(
            f"{symbol}: "
            f"{len(bars)} M5 bars received"
        )


        process_symbol(
            symbol,
            bars,
        )


        request_next_m5()


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
            "errorCode",
        ):

            print(
                "Error code:",
                response.errorCode,
            )


        if hasattr(
            response,
            "description",
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
# START
# =========================================================

client.startService()


def timeout():

    print(
        "ERROR: Bot timed out after 120 seconds."
    )

    stop_bot()


# Multi-market requests need more time
reactor.callLater(
    120,
    timeout
)


reactor.run()