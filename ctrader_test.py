import os

from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAAccountAuthReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAPayloadType,
)
from twisted.internet import reactor


# =========================================================
# TRADING_TOP - cTrader REAL API CONNECTION TEST
# =========================================================

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
REFRESH_TOKEN = os.getenv("CTRADER_REFRESH_TOKEN")

print("=== TRADING_TOP cTrader REAL API TEST ===")


# =========================================================
# CHECK ENVIRONMENT VARIABLES
# =========================================================

if not all([
    CLIENT_ID,
    CLIENT_SECRET,
    ACCESS_TOKEN,
    REFRESH_TOKEN
]):
    print("ERROR: One or more cTrader credentials are missing.")
    raise SystemExit(1)

print("Credentials loaded from Google Secret Manager: OK")


# =========================================================
# CONNECT TO cTRADER DEMO SERVER
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
# SERVER CONNECTED
# =========================================================

def connected(client):

    print("1. Connected to cTrader DEMO server")

    request = ProtoOAApplicationAuthReq()

    request.clientId = CLIENT_ID
    request.clientSecret = CLIENT_SECRET

    deferred = client.send(request)
    deferred.addErrback(on_error)


# =========================================================
# SERVER DISCONNECTED
# =========================================================

def disconnected(client, reason):

    print("Disconnected from cTrader server")

    if reason:
        print("Reason:", reason)


# =========================================================
# RECEIVE cTRADER MESSAGES
# =========================================================

def on_message_received(client, message):

    payload_type = message.payloadType

    # -----------------------------------------------------
    # APPLICATION AUTH SUCCESS
    # -----------------------------------------------------

    if payload_type == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:

        print("2. Application authentication: SUCCESS")

        request = ProtoOAGetAccountListByAccessTokenReq()

        request.accessToken = ACCESS_TOKEN

        deferred = client.send(request)
        deferred.addErrback(on_error)


    # -----------------------------------------------------
    # ACCOUNT LIST RECEIVED
    # -----------------------------------------------------

    elif payload_type == ProtoOAPayloadType.PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_RES:

        response = Protobuf.extract(message)

        accounts = response.ctidTraderAccount

        print(
            "3. Authorized accounts found:",
            len(accounts)
        )

        if len(accounts) == 0:

            print(
                "ERROR: No cTrader accounts are authorized "
                "for this access token."
            )

            stop_test()
            return


        # Display only safe information.
        # Do NOT print account IDs or tokens.

        for index, account in enumerate(accounts, start=1):

            if account.isLive:
                account_type = "LIVE"
            else:
                account_type = "DEMO"

            print(
                f"   Account {index}: {account_type}"
            )


        # -------------------------------------------------
        # USE FIRST AUTHORIZED DEMO ACCOUNT
        # -------------------------------------------------

        selected_account = None

        for account in accounts:

            if not account.isLive:

                selected_account = account
                break


        if selected_account is None:

            print(
                "ERROR: No DEMO account found."
            )

            stop_test()
            return


        print(
            "4. Authenticating authorized DEMO account..."
        )


        request = ProtoOAAccountAuthReq()

        request.ctidTraderAccountId = int(
            selected_account.ctidTraderAccountId
        )

        request.accessToken = ACCESS_TOKEN


        deferred = client.send(request)
        deferred.addErrback(on_error)


    # -----------------------------------------------------
    # ACCOUNT AUTH SUCCESS
    # -----------------------------------------------------

    elif payload_type == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:

        print(
            "5. Account authentication: SUCCESS"
        )

        print(
            "========================================"
        )

        print(
            "SUCCESS: cTrader REAL API connection works!"
        )

        print(
            "========================================"
        )

        stop_test()


    # -----------------------------------------------------
    # cTRADER API ERROR
    # -----------------------------------------------------

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

client.setDisconnectedCallback(disconnected)

client.setMessageReceivedCallback(
    on_message_received
)


# =========================================================
# START CONNECTION
# =========================================================

client.startService()


# =========================================================
# SAFETY TIMEOUT - 30 SECONDS
# =========================================================

def timeout():

    print(
        "ERROR: cTrader connection test timed out "
        "after 30 seconds."
    )

    stop_test()


reactor.callLater(
    30,
    timeout
)


reactor.run()
