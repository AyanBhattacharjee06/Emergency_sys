import argparse
import socket
from .protocol import PORT, encode, decode


def publish(server, token, text, confirm=True, level='emergency'):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(3)
        sock.sendto(encode(dict(type='publish', token=token, text=text,
                               confirm=confirm, level=level)), server)
        raw, source = sock.recvfrom(8192)
        if source != server:
            raise ValueError('Unexpected reply source')
        reply = decode(raw)
        if reply['type'] == 'error':
            raise ValueError(reply['error'])
        return reply


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--server', default='127.0.0.1')
    p.add_argument('--port', type=int, default=PORT)
    p.add_argument('--token', required=True)
    p.add_argument('--text', required=True)
    p.add_argument('--no-confirm', action='store_true')
    p.add_argument('--level', choices=['normal', 'emergency'], default='emergency')
    a = p.parse_args()
    print(publish((socket.gethostbyname(a.server), a.port), a.token, a.text, not a.no_confirm, a.level))
