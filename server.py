import os
import trio
import argparse
from wsproto.events import ConnectionClosed, ConnectionRequested, PingReceived, TextReceived
from wsproto.connection import WSConnection, ConnectionType

from cert import CERT


RECEIVE_BYTES = 4096


next_conn_id = 0

def get_next_conn_id():
    global next_conn_id
    next_conn_id += 1
    return next_conn_id


async def handle_connection(stream):
    '''
    Handle a connection.
    The server operates a request/response cycle, so it performs a synchronous
    loop:
    1) Read data from network into wsproto
    2) Get next wsproto event
    3) Handle event
    4) Send data from wsproto to network
    :param stream: a socket stream
    '''
    conn_id = get_next_conn_id()
    ws = WSConnection(ConnectionType.SERVER)

    # events is a generator that yields websocket event objects. Usually you
    # would say `for event in ws.events()`, but the synchronous nature of this
    # server requires us to use next(event) instead so that we can interleave
    # the network I/O.
    events = ws.events()
    running = True

    while running:
        # 1) Read data from network
        in_data = await stream.receive_some(RECEIVE_BYTES)
        print(f'[{conn_id}] Received {len(in_data)} bytes')
        ws.receive_bytes(in_data)

        # 2) Get next wsproto event
        try:
            event = next(events)
        except StopIteration:
            print(f'[{conn_id}] Client connection dropped unexpectedly')
            return

        # 3) Handle event
        if isinstance(event, ConnectionRequested):
            # Negotiate new WebSocket connection
            print(f'[{conn_id}] Accepting WebSocket upgrade')
            ws.accept(event)
        elif isinstance(event, ConnectionClosed):
            # Print log message and break out
            print(f'[{conn_id}] Connection closed: code={event.code.value}/{event.code.name} reason={event.reason}')
            running = False
        elif isinstance(event, TextReceived):
            # Reverse text and send it back to wsproto
            print(f'[{conn_id}] Received request and sending response')
            ws.send_data(event.data[::-1])
        elif isinstance(event, PingReceived):
            # wsproto handles ping events for you by placing a pong frame in
            # the outgoing buffer. You should not call pong() unless you want to
            # send an unsolicited pong frame.
            print(f'[{conn_id}] Received ping and sending pong')
        else:
            print(f'[{conn_id}] Unknown event: {event!r}')

        # 4) Send data from wsproto to network
        out_data = ws.bytes_to_send()
        print(f'[{conn_id}] Sending {len(out_data)} bytes: {out_data!r}')
        await stream.send_all(out_data)


async def handle_connection_with_ssl(stream):
    ssl_context = trio.ssl.create_default_context(trio.ssl.Purpose.CLIENT_AUTH)
    CERT.configure_cert(ssl_context)
    ssl_stream = trio.ssl.SSLStream(stream, ssl_context, server_side=True)

    return await handle_connection(ssl_stream)


async def main():
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', 7777))
    SSL = 'USE_SSL' in os.environ
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default=HOST)
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--ssl', action='store_true', default=SSL)
    args = parser.parse_args()

    print(f'Starting server on {args.host}:{args.port}')
    if args.ssl:
        await trio.serve_tcp(handle_connection_with_ssl, args.port, host=args.host)
    else:
        await trio.serve_tcp(handle_connection, args.port, host=args.host)


if __name__ == '__main__':
    trio.run(main)
