import argparse
import json
import random
import socket
import time
from pathlib import Path
from .protocol import PORT, EMERGENCY_PORT, MAX_PACKET, encode, decode


def run(server, client, bind, port, log, duration, drop_ack=0):
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    rng = random.Random(client)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock, open(log, 'w', buffering=1) as out:
        sock.bind((bind, port))
        sock.settimeout(.1)
        end, refresh = time.monotonic()+duration, 0
        while time.monotonic() < end:
            if time.monotonic() >= refresh:
                sock.sendto(encode(dict(type='register', client=client)), server)
                refresh = time.monotonic()+2
            try:
                raw, source = sock.recvfrom(MAX_PACKET+1)
                if source != server:
                    continue
                msg = decode(raw)
                if msg['type'] != 'notification':
                    continue
                ident = msg['id']
                if ident not in seen:
                    seen.add(ident)
                    row = dict(event='received', id=ident, client=client, level=msg['level'],
                               latency_ms=(time.time_ns()-msg['sent_ns'])/1e6, text=msg['text'])
                    out.write(json.dumps(row)+'\n')
                    print(json.dumps(row), flush=True)
                if msg['confirm'] and rng.random() >= drop_ack:
                    sock.sendto(encode(dict(type='ack', id=ident, client=client)), server)
            except socket.timeout:
                pass
            except (ValueError, KeyError, TypeError):
                continue


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--server', default='127.0.0.1')
    p.add_argument('--server-port', type=int, default=PORT)
    p.add_argument('--client', required=True)
    p.add_argument('--bind', default='0.0.0.0')
    p.add_argument('--port', type=int, default=EMERGENCY_PORT)
    p.add_argument('--log', default='results/client.jsonl')
    p.add_argument('--duration', type=float, default=3600)
    p.add_argument('--drop-ack', type=float, default=0)
    a = p.parse_args()
    run((socket.gethostbyname(a.server), a.server_port), a.client, a.bind, a.port,
        a.log, a.duration, a.drop_ack)
