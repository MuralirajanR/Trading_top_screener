import os
import time
import requests
from datetime import datetime

import pytz


# =========================================================
# SETTINGS
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

IST = pytz.timezone("Asia/Kolkata")


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets missing!")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        response.raise_for_status()

        print("Telegram message sent successfully!")

        return True

    except Exception as e:

        print(f"Telegram error: {e}")

        return False


# =========================================================
# NSE FII / DII DATA
# =========================================================

def get_fii_dii():

    api_url = (
        "https://www.nseindia.com/"
        "api/fiidiiTradeReact"
    )

    headers = {

        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/124.0.0.0 "
            "Safari/537.36"
        ),

        "Accept": (
            "application/json, "
            "text/plain, */*"
        ),

        "Accept-Language": (
            "en-US,en;q=0.9"
        ),

        "Referer": (
            "https://www.nseindia.com/"
            "reports/fii-dii"
        ),
    }

    session = requests.Session()

    try:

        # First request gets NSE cookies
        home_response = session.get(
            "https://www.nseindia.com",
            headers=headers,
            timeout=15,
        )

        print(
            "NSE home status:",
            home_response.status_code
        )

        time.sleep(1)

        response = session.get(
            api_url,
            headers=headers,
            timeout=15,
        )

        print(
            "NSE API status:",
            response.status_code
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, list):
            print("Unexpected NSE response.")
            return None

        if len(data) == 0:
            print("NSE returned empty data.")
            return None

        return data

    except Exception as e:

        print(
            f"Error fetching FII/DII data: {e}"
        )

        return None


# =========================================================
# CONVERT NSE VALUE
# =========================================================

def to_float(value):

    try:

        return float(
            str(value)
            .replace(",", "")
            .replace("₹", "")
            .strip()
        )

    except Exception:

        return 0.0


# =========================================================
# FORMAT NET VALUE
# =========================================================

def format_net(value):

    if value >= 0:
        return f"+₹{value:,.2f} Cr"

    return f"-₹{abs(value):,.2f} Cr"


# =========================================================
# MAIN
# =========================================================

def main():

    now = datetime.now(IST)

    print(
        "FII/DII bot started:",
        now.strftime(
            "%d-%m-%Y %I:%M:%S %p IST"
        )
    )

    print(
        "Fetching NSE FII / DII data..."
    )

    data = get_fii_dii()


    # =====================================================
    # API FAILURE
    # =====================================================

    if not data:

        send_telegram(

            "⚠️ <b>FII / DII DATA UPDATE</b>\n\n"

            "NSE FII/DII data fetch panna mudiyala.\n"

            "NSE API temporary-aa unavailable-a "
            "irukkalam."
        )

        return


    # =====================================================
    # DATA DATE
    # =====================================================

    date_str = str(
        data[0].get(
            "date",
            "Latest available"
        )
    )


    # =====================================================
    # REPORT HEADER
    # =====================================================

    msg_lines = [

        "🏛️ <b>NSE FII / DII CASH ACTIVITY</b>",

        f"📅 <b>Data Date:</b> {date_str}",

        "",
    ]


    total_net = 0.0
    found_fii = False
    found_dii = False


    # =====================================================
    # PROCESS DATA
    # =====================================================

    for item in data:

        category = str(
            item.get(
                "category",
                ""
            )
        )

        buy_value = to_float(
            item.get(
                "buyValue",
                0
            )
        )

        sell_value = to_float(
            item.get(
                "sellValue",
                0
            )
        )

        net_value = to_float(
            item.get(
                "netValue",
                0
            )
        )


        # =================================================
        # DII
        # =================================================

        if "DII" in category.upper():

            found_dii = True

            name = (
                "DII "
                "(Domestic Institutions)"
            )

            emoji = (
                "🟢"
                if net_value >= 0
                else "🔴"
            )

            status = (
                "NET BUYER"
                if net_value >= 0
                else "NET SELLER"
            )


        # =================================================
        # FII / FPI
        # =================================================

        else:

            found_fii = True

            name = (
                "FII / FPI "
                "(Foreign Institutions)"
            )

            emoji = (
                "🟢"
                if net_value >= 0
                else "🔴"
            )

            status = (
                "NET BUYER"
                if net_value >= 0
                else "NET SELLER"
            )


        total_net += net_value


        msg_lines.append(

            f"{emoji} <b>{name}</b>\n"

            f"Buy: ₹{buy_value:,.2f} Cr\n"

            f"Sell: ₹{sell_value:,.2f} Cr\n"

            f"<b>Net: "
            f"{format_net(net_value)}</b>\n"

            f"Status: <b>{status}</b>\n"
        )


    # =====================================================
    # VALIDATION
    # =====================================================

    if not found_fii or not found_dii:

        print(
            "Warning: Expected FII/DII "
            "categories not found."
        )


    # =====================================================
    # COMBINED FLOW
    # =====================================================

    if total_net > 0:

        combined_status = (
            "🟢 NET INSTITUTIONAL INFLOW"
        )

    elif total_net < 0:

        combined_status = (
            "🔴 NET INSTITUTIONAL OUTFLOW"
        )

    else:

        combined_status = (
            "⚪ NEUTRAL FLOW"
        )


    msg_lines.extend([

        "━━━━━━━━━━━━━━━━━━━━",

        "📊 <b>COMBINED NET FLOW</b>",

        f"<b>{format_net(total_net)}</b>",

        combined_status,

        "",

        "ℹ️ <i>Cash-market institutional "
        "activity only.</i>",
    ])


    # =====================================================
    # SEND TELEGRAM
    # =====================================================

    full_message = "\n".join(
        msg_lines
    )

    print(
        f"NSE data date: {date_str}"
    )

    print(
        f"Combined net flow: "
        f"{total_net:,.2f} Cr"
    )

    send_telegram(
        full_message
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    main()