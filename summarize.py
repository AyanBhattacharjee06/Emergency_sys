import argparse
import json
import math
from pathlib import Path


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def summarize(folder):
    folder = Path(folder)
    server = rows(folder/'server.jsonl')
    expected = {(r['id'], r['client']) for r in server if r['event'] == 'sent'}
    received = {}
    for path in folder.glob('client*.jsonl'):
        for r in rows(path):
            key = (r['id'], r['client'])
            if key in expected:
                received.setdefault(key, r['latency_ms'])
    latency = sorted(received.values())
    confirms = [r['confirmation_ms'] for r in server if r['event'] == 'confirmed']
    return dict(expected_deliveries=len(expected), received_deliveries=len(received),
                delivery_loss_percent=100*(len(expected)-len(received))/len(expected) if expected else None,
                mean_latency_ms=sum(latency)/len(latency) if latency else None,
                p95_latency_ms=latency[math.ceil(.95*len(latency))-1] if latency else None,
                mean_confirmation_ms=sum(confirms)/len(confirms) if confirms else None,
                retries=sum(r['event'] == 'retry' for r in server),
                unconfirmed=sum(r['event'] == 'unconfirmed' for r in server))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('folders', nargs='+')
    a = p.parse_args()
    for folder in a.folders:
        print(folder, json.dumps(summarize(folder), indent=2))
