"""Central SDN control process; OpenFlow 1.3 via the OVS management socket.

Registration events dynamically install short-lived per-subscriber classifiers.
No Ryu dependency or remote OpenFlow listener is required.
"""
import argparse
import ipaddress
import json
import subprocess
import time
from pathlib import Path


def ofctl(bridge, *args):
    return subprocess.check_output(['ovs-ofctl', '-O', 'OpenFlow13', *args[:1], bridge, *args[1:]], text=True)


def registration_flow(event):
    ip = str(ipaddress.IPv4Address(event['ip']))
    port = int(event['port'])
    if not 1 <= port <= 65535:
        raise ValueError('Invalid port')
    return (f'cookie=0xe911,priority=200,hard_timeout=6,udp,nw_src=10.0.0.1,'
            f'nw_dst={ip},tp_src=9000,tp_dst={port},ip_dscp=46,'
            'actions=set_queue:1,NORMAL')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--bridges', nargs='+', default=['s1', 's2'])
    p.add_argument('--events', required=True)
    p.add_argument('--log', required=True)
    p.add_argument('--mode', choices=['baseline', 'priority'], required=True)
    a = p.parse_args()
    for bridge in a.bridges:
        ofctl(bridge, 'del-flows')
        ofctl(bridge, 'add-flow', 'priority=0,actions=set_queue:0,NORMAL')
    Path(a.events).touch(exist_ok=True)
    with open(a.events) as events, open(a.log, 'w', buffering=1) as log:
        log.write(json.dumps(dict(event='controller_ready', mode=a.mode))+'\n')
        while True:
            line = events.readline()
            if not line:
                time.sleep(.02)
                continue
            try:
                event = json.loads(line)
                if a.mode == 'priority' and event['event'] == 'register':
                    flow = registration_flow(event)
                    for bridge in a.bridges:
                        ofctl(bridge, 'add-flow', flow)
                    log.write(json.dumps(dict(event='priority_installed', client=event['client'],
                                              time_ns=time.time_ns(), flow=flow))+'\n')
            except (ValueError, KeyError) as exc:
                log.write(json.dumps(dict(event='invalid_event', error=str(exc)))+'\n')


if __name__ == '__main__':
    main()
