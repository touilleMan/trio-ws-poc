import trio
import argparse
from wsproto.events import ConnectionEstablished, TextReceived, PongReceived
from wsproto.connection import WSConnection, ConnectionType

from cert import CA


RECEIVE_BYTES = 4096


def upgrade_stream_to_ssl(raw_stream, hostname):
    ssl_context = trio.ssl.create_default_context()
    CA.configure_trust(ssl_context)
    return trio.ssl.SSLStream(raw_stream, ssl_context, server_hostname=hostname)


async def wsproto_client_demo(host, port, use_ssl):
    '''
    Demonstrate wsproto:
    0) Open TCP connection
    1) Negotiate WebSocket opening handshake
    2) Send a message and display response
    3) Send ping and display pong
    4) Negotiate WebSocket closing handshake
    :param stream: a socket stream
    '''

    # 0) Open TCP connection
    print('[C] Connecting to {}:{}'.format(host, port))
    conn = await trio.open_tcp_stream(host, port)
    if use_ssl:
        conn = upgrade_stream_to_ssl(conn, host)

    # 1) Negotiate WebSocket opening handshake
    print('[C] Opening WebSocket')
    ws = WSConnection(ConnectionType.CLIENT, host=host, resource='server')

    events = ws.events()

    # Because this is a client WebSocket, wsproto has automatically queued up
    # a handshake, and we need to send it and wait for a response.
    await net_send_recv(ws, conn)
    event = next(events)
    if isinstance(event, ConnectionEstablished):
        print('[C] WebSocket negotiation complete')
    else:
        raise Exception(f'Expected ConnectionEstablished event! Got: {event}')

    # 2) Send a message and display response
    message = "wsproto is great" * 10
    print('[C] Sending message: {}'.format(message))
    ws.send_data(message)
    await net_send_recv(ws, conn)
    event = next(events)
    if isinstance(event, TextReceived):
        print('[C] Received message: {}'.format(event.data))
    else:
        raise Exception(f'Expected TextReceived event! Got: {event}')

    # 3) Send ping and display pong
    payload = b"table tennis"
    print('[C] Sending ping: {}'.format(payload))
    ws.ping(payload)
    await net_send_recv(ws, conn)
    event = next(events)
    if isinstance(event, PongReceived):
        print('[C] Received pong: {}'.format(event.payload))
    else:
        raise Exception(f'Expected PongReceived event! Got: {event}')

    # 4) Negotiate WebSocket closing handshake
    print('[C] Closing WebSocket')
    ws.close(code=1000, reason='sample reason')
    # After sending the closing frame, we won't get any more events. The server
    # should send a reply and then close the connection, so we need to receive
    # twice:
    await net_send_recv(ws, conn)
    await conn.aclose()
    # await net_recv(ws, conn)


async def net_send(ws, conn):
    ''' Write pending data from websocket to network. '''
    out_data = ws.bytes_to_send()
    print(f'[C] Sending {len(out_data)} bytes: {out_data!r}')
    await conn.send_all(out_data)


async def net_recv(ws, conn):
    ''' Read pending data from network into websocket. '''
    in_data = await conn.receive_some(RECEIVE_BYTES)
    if not in_data:
        # A receive of zero bytes indicates the TCP socket has been closed. We
        # need to pass None to wsproto to update its internal state.
        print('[C] Received 0 bytes (connection closed)')
        ws.receive_bytes(None)
    else:
        print('[C] Received {} bytes'.format(len(in_data)))
        ws.receive_bytes(in_data)


async def net_send_recv(ws, conn):
    ''' Send pending data and then wait for response. '''
    await net_send(ws, conn)
    await net_recv(ws, conn)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int, default=7777)
    parser.add_argument('--ssl', action='store_true')
    args = parser.parse_args()

    await wsproto_client_demo(args.host, args.port, args.ssl)


if __name__ == '__main__':
    trio.run(main)
