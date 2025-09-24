#!/usr/bin/env python3
"""Simple HTTP server that dumps raw request data.

Run with:
    python3 tests/raw_http_dump_server.py --port 8082

The server listens on the specified port, prints each raw HTTP request
(including headers and body) to stdout, and responds with a simple 200 OK.
"""

import argparse
import datetime
import socket
import sys
from typing import Tuple

BUFFER_SIZE = 4096
RECV_TIMEOUT = 1.0  # seconds


def read_request(conn: socket.socket) -> bytes:
    """Read raw data from the socket until the client closes or times out."""
    chunks = []
    conn.settimeout(RECV_TIMEOUT)
    while True:
        try:
            chunk = conn.recv(BUFFER_SIZE)
        except socket.timeout:
            break
        if not chunk:
            break
        chunks.append(chunk)
        # Heuristic: stop early if request appears complete and no body length declared.
        if b"\r\n\r\n" in chunk and len(chunk) < BUFFER_SIZE:
            break
    return b"".join(chunks)


def handle_connection(conn: socket.socket, addr: Tuple[str, int]) -> None:
    """Dump the raw request and send back a minimal HTTP response."""
    with conn:
        raw = read_request(conn)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = f"--- Request from {addr[0]}:{addr[1]} at {timestamp} ---"
        print(header)
        if raw:
            try:
                print(raw.decode("utf-8", errors="replace"))
            except Exception:
                print(raw)
        else:
            print("<no data received>")
        print("--- End of request ---\n", flush=True)

        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Length: 3\r\n"
            b"Connection: close\r\n"
            b"\r\n"
            b"ok\n"
        )
        try:
            conn.sendall(response)
        except OSError:
            pass


def serve(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", port))
        sock.listen()
        print(f"Listening on 0.0.0.0:{port} (Ctrl+C to stop)")
        try:
            while True:
                conn, addr = sock.accept()
                handle_connection(conn, addr)
        except KeyboardInterrupt:
            print("Stopping server.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dump raw HTTP requests")
    parser.add_argument("--port", type=int, default=8082, help="Port to listen on")
    return parser.parse_args(argv)


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    serve(args.port)


if __name__ == "__main__":
    main(sys.argv[1:])
