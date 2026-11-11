import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from emergency.protocol import encode, decode
from emergency.server import Server
from emergency.publish import publish
from emergency.client import run as run_client
from sdn.controller import registration_flow
from experiments.summarize import summarize


class SystemTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1]/'results'/'tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.log = Path(self.temp.name)/'server.jsonl'
        self.server = Server('127.0.0.1', 0, 'secret', self.log, retry=.06, attempts=3, ttl=.8)
        self.address = self.server.sock.getsockname()
        self.thread = threading.Thread(target=self.server.run)
        self.thread.start()
        self.sockets = []

    def tearDown(self):
        self.server.running = False
        self.thread.join(2)
        for sock in self.sockets:
            sock.close()
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(Path(__file__).resolve().parents[1]/'results'))
        self.temp.cleanup()

    def client(self, name):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 0))
        sock.settimeout(1)
        self.sockets.append(sock)
        sock.sendto(encode(dict(type='register', client=name)), self.address)
        self.assertEqual(decode(sock.recv(8192))['type'], 'registered')
        return sock

    def test_multiple_subscribers_ack_and_retry(self):
        first, second = self.client('first'), self.client('second')
        result = publish(self.address, 'secret', 'Evacuate building')
        self.assertEqual(result['targets'], 2)
        msg = decode(first.recv(8192))
        first.sendto(encode(dict(type='ack', id=msg['id'], client='first')), self.address)
        original = decode(second.recv(8192))
        retry = decode(second.recv(8192))
        self.assertEqual(original['id'], retry['id'])
        second.sendto(encode(dict(type='ack', id=retry['id'], client='second')), self.address)
        time.sleep(.1)
        events = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(sum(e['event'] == 'confirmed' for e in events), 2)
        self.assertTrue(any(e['event'] == 'retry' for e in events))

    def test_unauthorized_and_malformed_survive(self):
        sock = self.client('first')
        sock.sendto(b'{invalid', self.address)
        with self.assertRaisesRegex(ValueError, 'Unauthorized'):
            publish(self.address, 'wrong', 'test')
        self.assertEqual(publish(self.address, 'secret', 'valid')['targets'], 1)

    def test_missing_ack_bounded_and_expired_subscriber(self):
        self.client('silent')
        publish(self.address, 'secret', 'test')
        time.sleep(.4)
        self.assertIn('unconfirmed', self.log.read_text())
        self.assertEqual(len(self.server.pending), 0)
        time.sleep(.5)
        self.assertEqual(publish(self.address, 'secret', 'later')['targets'], 0)

    def test_no_confirm(self):
        sock = self.client('first')
        publish(self.address, 'secret', 'ordinary', False, 'normal')
        self.assertFalse(decode(sock.recv(8192))['confirm'])
        time.sleep(.1)
        self.assertEqual(len(self.server.pending), 0)

    def test_duplicate_id_cannot_redirect(self):
        self.client('first')
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sockets.append(sock)
        sock.settimeout(1)
        sock.sendto(encode(dict(type='register', client='first')), self.address)
        self.assertEqual(decode(sock.recv(8192))['type'], 'error')

    def test_flow_validation(self):
        flow = registration_flow(dict(ip='10.0.0.2', port=9001))
        self.assertIn('ip_dscp=46', flow)
        self.assertIn('set_queue:1', flow)
        with self.assertRaises(ValueError):
            registration_flow(dict(ip='bad,actions=drop', port=9001))

    def test_real_client_deduplicates_retries(self):
        log = Path(self.temp.name)/'client.jsonl'
        client = threading.Thread(target=run_client, args=(self.address, 'real', '127.0.0.1', 0, log, .6, 1))
        client.start()
        try:
            deadline = time.monotonic()+1
            while 'real' not in self.server.clients and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertIn('real', self.server.clients)
            publish(self.address, 'secret', 'Deduplicate this')
        finally:
            client.join(2)
        self.assertFalse(client.is_alive())
        self.assertEqual(len(log.read_text().splitlines()), 1)
        self.assertIn('unconfirmed', self.log.read_text())

    def test_metrics_use_unique_deliveries(self):
        folder = Path(self.temp.name)/'metrics'
        folder.mkdir()
        (folder/'server.jsonl').write_text('\n'.join(json.dumps(r) for r in [
            dict(event='sent', id='a', client='c1'), dict(event='sent', id='a', client='c2')]))
        record = json.dumps(dict(id='a', client='c1', latency_ms=10))+'\n'
        (folder/'client0.jsonl').write_text(record*2)
        result = summarize(folder)
        self.assertEqual(result['delivery_loss_percent'], 50)
        self.assertEqual(result['mean_latency_ms'], 10)


if __name__ == '__main__':
    unittest.main()
