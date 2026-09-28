import os

from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import (
    ProtoOAApplicationAuthReq,
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAAccountAuthReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAPayloadType,
)
from twisted.internet import reactor


CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")

print("=== TRADING_TOP cTrader REAL API TEST ===")


if not all([CLIENT_ID, CLIENT_SECRET, ACCESS_TOKEN]):
    print("ERROR: Required cTrader credentials are missing.")
    raise SystemExit(1)


# We are testing the DEMO environment
client = Client(
    EndPoints.PROTOBUF_DEMO_HOST,
    EndPoints.PROTOBUF_PORT,
    TcpProtocol
)


def stop_test():
    if reactor.running:
        reactor.stop()


def on_error(failure):
    print("ERROR:", failure)
    stop_test()


def connected(client):
    print("1. Connected to cTrader DEMO server")

    request = ProtoOAApplicationAuthReq()
    request.clientId = CLIENT_ID
    request.clientSecret = CLIENT_SECRET

    deferred = client.send(request)
    deferred.addErrback(on_error)


def disconnected(client, reason):
    print("Disconnected:", reason)


def on_message_received(client, message):

    payload_type = message.payloadType

    # -------------------------------------------------
    # STEP 1 - Application authenticated
    # -------------------------------------------------
    if payload_type == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:

        print("2. Application authentication: SUCCESS")

        request = ProtoOAGetAccountListByAccessTokenReq()
        request.accessToken = ACCESS_TOKEN

        deferred = client.send(request)
        deferred.addErrback(on_error)

    # -------------------------------------------------
    # STEP 2 - Get authorized accounts
    # -------------------------------------------------
    elif payload_type == ProtoOAPayloadType.PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_RES:

        response = Protobuf.extract(message)

        accounts = response.ctidTraderAccount

        print(f"3. Authorized accounts found: {len(accounts)}")

        if len(accounts) == 0:
            print("ERROR: No authorized cTrader accounts found.")
            stop_test()
            return

        # Do NOT print full account details.
        # Just show safe index + account type.
        for i, account in enumerate(accounts, start=1):
            account_type = "LIVE" if account.isLive else "DEMO"
            print(f"   Account {i}: {account_type}")

        account_id = int(accounts[0].ctidTraderAccountId)

        print("4. Authenticating first authorized DEMO account...")

        request = ProtoOAAccountAuthReq()
        request.ctidTraderAccountId = account_id
        request.accessToken = ACCESS_TOKEN

        deferred = client.send(request)
        deferred.addErrback(on_error)

    # -------------------------------------------------
    # STEP 3 - Account authenticated
    # -------------------------------------------------
    elif payload_type == ProtoOAPayloadType.PROTO_OA_ACCOUNT_AUTH_RES:

        print("5. Account authentication: SUCCESS")
        print("========================================")
        print("SUCCESS: cTrader REAL API connection works!")
        print("========================================")

        stop_test()

    # -------------------------------------------------
    # API ERROR
    # -------------------------------------------------
    elif payload_type == ProtoOAPayloadType.PROTO_OA_ERROR_RES:

        response = Protobuf.extract(message)

        print("cTrader API ERROR")
        print("Error code:", response.errorCode)
        print("Description:", response.description)

        stop_test()


client.setConnectedCallback(connected)
client.setDisconnectedCallback(disconnected)
client.setMessageReceivedCallback(on_message_received)

client.startService()

# Safety timeout
reactor.callLater(30, lambda: (
    print("ERROR: Test timed out after 30 seconds."),
    stop_test()
))

reactor.run()
