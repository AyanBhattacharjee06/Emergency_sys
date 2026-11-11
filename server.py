import argparse
import json
import socket
import time
import uuid
from pathlib import Path
from .protocol import PORT, MAX_PACKET, encode, decode


class Server:
    def __init__(self, bind, port, token, log, retry=.25, attempts=4, ttl=15):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind, port))
        self.sock.settimeout(.05)
        self.token, self.retry, self.attempts, self.ttl = token, retry, attempts, ttl
        self.clients, self.pending = {}, {}
        self.running = True
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        self.log = open(log, 'a', buffering=1, encoding='utf-8')

    def record(self, event, **fields):
        self.log.write(json.dumps(dict(event=event, time_ns=time.time_ns(), **fields)) + '\n')

    def send(self, message, address):
        emergency = message.get('type') == 'notification' and message.get('level') == 'emergency'
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 184 if emergency else 0)
        self.sock.sendto(encode(message), address)

    def handle(self, message, addr):
        kind = message['type']
        now = time.monotonic()
        if kind == 'register':
            # IDs are endpoint-bound; registration cannot redirect another subscriber.
            client = message.get('client')
            if not isinstance(client, str) or not 0 < len(client) <= 64:
                raise ValueError('Invalid client ID')
            old = self.clients.get(client)
            if old and old[0] != addr and now - old[1] < self.ttl:
                self.send({'type': 'error', 'error': 'ID already registered'}, addr)
                return
            self.clients[client] = (addr, now)
            self.send({'type': 'registered', 'client': client}, addr)
            self.record('register', client=client, ip=addr[0], port=addr[1])
        elif kind == 'ack':
            key = (message.get('id'), message.get('client'))
            entry = self.pending.get(key)
            if entry and entry['addr'] == addr:
                self.record('confirmed', id=key[0], client=key[1],
                            confirmation_ms=(now-entry['start'])*1000,
                            attempts=entry['attempts'])
                del self.pending[key]
        elif kind == 'publish':
            if message.get('token') != self.token:
                self.record('unauthorized')
                self.send({'type': 'error', 'error': 'Unauthorized publisher'}, addr)
                return
            body = message.get('text')
            level = message.get('level', 'emergency')
            if not isinstance(body, str) or not 0 < len(body) <= 2000 or level not in ('normal', 'emergency'):
                raise ValueError('Invalid text or level')
            ident = uuid.uuid4().hex
            confirm = bool(message.get('confirm', True))
            event = dict(type='notification', id=ident, text=body, level=level,
                         confirm=confirm, sent_ns=time.time_ns())
            targets = [(c, a) for c, (a, seen) in self.clients.items() if now-seen < self.ttl]
            self.record('published', id=ident, level=level, targets=len(targets), confirm=confirm)
            for client, address in targets:
                self.send(event, address)
                self.record('sent', id=ident, client=client)
                if confirm:
                    self.pending[(ident, client)] = dict(addr=address, message=event,
                                                        start=now, due=now+self.retry, attempts=1)
            self.send(dict(type='published', id=ident, targets=len(targets)), addr)

    def tick(self):
        now = time.monotonic()
        for key, entry in list(self.pending.items()):
            if now < entry['due']:
                continue
            if entry['attempts'] >= self.attempts:
                self.record('unconfirmed', id=key[0], client=key[1])
                del self.pending[key]
            else:
                self.send(entry['message'], entry['addr'])
                entry['attempts'] += 1
                entry['due'] = now + self.retry
                self.record('retry', id=key[0], client=key[1])
        self.clients = {c: v for c, v in self.clients.items() if now-v[1] < self.ttl}

    def run(self):
        self.record('server_started', address=self.sock.getsockname())
        try:
            while self.running:
                try:
                    raw, addr = self.sock.recvfrom(MAX_PACKET+1)
                    self.handle(decode(raw), addr)
                except socket.timeout:
                    pass
                except (ValueError, TypeError, KeyError, OSError) as exc:
                    self.record('invalid', reason=str(exc))
                self.tick()
        finally:
            self.sock.close()
            self.log.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--bind', default='0.0.0.0')
    p.add_argument('--port', type=int, default=PORT)
    p.add_argument('--token', required=True)
    p.add_argument('--log', default='results/server.jsonl')
    a = p.parse_args()
    try:
        Server(a.bind, a.port, a.token, a.log).run()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
