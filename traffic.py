import argparse
import socket
import time

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['sink', 'send'])
    p.add_argument('--target', default='10.0.0.11')
    a = p.parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        if a.mode == 'sink':
            sock.bind(('0.0.0.0', 5001))
            while True:
                sock.recvfrom(65535)
        else:
            # 1200 bytes every 2ms ~= 4.8Mbps, saturating the 1Mbps trunk.
            payload = b'x'*1200
            while True:
                sock.sendto(payload, (a.target, 5001))
                time.sleep(.002)
