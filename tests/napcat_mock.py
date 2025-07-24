#!/usr/bin/env python3
import argparse
import http.server
import json
import os
import threading
import time
from urllib.parse import urlparse
import requests

class CaptureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b''
        record = {
            'method': 'GET',
            'path': self.path,
            'body': body.decode('utf-8', errors='ignore')
        }
        self.server.records.append(record)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else b''
        record = {
            'method': 'POST',
            'path': self.path,
            'body': body.decode('utf-8', errors='ignore')
        }
        self.server.records.append(record)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, format, *args):
        return

class ThreadedHTTPServer(http.server.ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, records):
        super().__init__(server_address, RequestHandlerClass)
        self.records = records


def run_server(port, records):
    server = ThreadedHTTPServer(('0.0.0.0', port), CaptureHandler, records)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def read_fifo(path, stop_event):
    if not os.path.exists(path):
        return
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    while not stop_event.is_set():
        try:
            data = os.read(fd, 1024)
            if data:
                print('[fifo]', data.decode().strip())
            else:
                time.sleep(0.1)
        except BlockingIOError:
            time.sleep(0.1)
    os.close(fd)


def run_plan(plan_path, target_port):
    with open(plan_path, 'r', encoding='utf-8') as f:
        plan = json.load(f)
    for item in plan:
        time.sleep(item.get('delay', 0))
        inp = item.get('input', {})
        try:
            requests.post(f'http://127.0.0.1:{target_port}', json=inp)
        except Exception as e:
            print('failed to send', e)
    return [step.get('expect') for step in plan if 'expect' in step]


def check_expectations(expectations, records):
    success = True
    for exp in expectations:
        found = False
        for rec in records:
            if rec['path'].startswith(exp.get('path', '')) and exp.get('query', '') in rec['path']:
                found = True
                break
        if not found:
            success = False
            print('expectation failed:', exp)
    return success


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--in-port', type=int, required=True)
    parser.add_argument('--out-port', type=int, required=True)
    parser.add_argument('--plan', default='tests/test_plan.json')
    args = parser.parse_args()

    out_records = []
    in_records = []

    out_server = run_server(args.out_port, out_records)
    in_server = run_server(args.in_port, in_records)

    stop_event = threading.Event()
    fifo_thread = threading.Thread(target=read_fifo, args=('./qzone_out_fifo', stop_event), daemon=True)
    fifo_thread.start()

    expectations = run_plan(args.plan, args.in_port)
    time.sleep(1)  # wait responses

    stop_event.set()
    out_server.shutdown()
    in_server.shutdown()

    success = check_expectations(expectations, out_records)
    if success:
        print('ALL TESTS PASSED')
        exit(0)
    else:
        print('TESTS FAILED')
        exit(1)

if __name__ == '__main__':
    main()
