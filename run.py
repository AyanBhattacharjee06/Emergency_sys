"""Run in an Ubuntu VM: sudo python3 -m experiments.run --mode priority --congested."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def qos(port):
    # Configure only project-owned ports; never destroy unrelated OVS QoS records.
    subprocess.run(['ovs-vsctl', 'set', 'port', port, 'qos=@qos', '--',
                    '--id=@qos', 'create', 'qos', 'type=linux-htb',
                    'other-config:max-rate=1000000', 'queues:0=@low', 'queues:1=@high', '--',
                    '--id=@low', 'create', 'queue', 'other-config:min-rate=100000',
                    'other-config:max-rate=1000000', 'other-config:priority=1', '--',
                    '--id=@high', 'create', 'queue', 'other-config:min-rate=800000',
                    'other-config:max-rate=1000000', 'other-config:priority=0'], check=True,
                   stdout=subprocess.DEVNULL)


def wait_for(path, predicate, processes, timeout=10):
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        if any(p.poll() is not None for p in processes):
            raise RuntimeError('A component exited; inspect component logs')
        if path.exists() and predicate(path.read_text()):
            return
        time.sleep(.1)
    raise RuntimeError('Startup timeout; inspect component logs')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=['baseline', 'priority'], required=True)
    p.add_argument('--congested', action='store_true')
    p.add_argument('--loss', type=float, default=0)
    p.add_argument('--count', type=int, default=60)
    p.add_argument('--interval', type=float, default=.1)
    p.add_argument('--drop-ack', type=float, default=0)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    if os.geteuid() != 0:
        p.error('Run with sudo in Ubuntu')
    from mininet.net import Mininet
    from mininet.node import OVSSwitch
    from mininet.link import TCLink
    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out/'config.json').write_text(json.dumps(vars(a), indent=2))
    os.chdir(ROOT)
    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink, autoSetMacs=True)
    processes, handles, qos_ids = [], [], []

    def start(host, module, *args):
        handle = open(out/(module.replace('.', '_')+f'-{len(processes)}.log'), 'w')
        handles.append(handle)
        cmd = [sys.executable, '-u', '-m', module, *map(str, args)]
        proc = host.popen(cmd, cwd=str(ROOT), stdout=handle, stderr=subprocess.STDOUT) if host else subprocess.Popen(cmd, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
        processes.append(proc)
        return proc

    try:
        s1 = net.addSwitch('s1', protocols='OpenFlow13', failMode='secure')
        s2 = net.addSwitch('s2', protocols='OpenFlow13', failMode='secure')
        server = net.addHost('srv', ip='10.0.0.1/24')
        clients = [net.addHost('c'+str(i), ip=f'10.0.0.{i+1}/24') for i in range(1, 4)]
        bg = net.addHost('bg', ip='10.0.0.10/24')
        sink = net.addHost('sink', ip='10.0.0.11/24')
        # Access-link impairment stays separate from the trunk's OVS HTB qdisc.
        access = net.addLink(server, s1)
        net.addLink(bg, s1)
        link = net.addLink(s1, s2)
        for host in [*clients, sink]:
            net.addLink(host, s2)
        net.start()
        for intf in [link.intf1, link.intf2]:
            qos(str(intf))
            qid = subprocess.check_output(['ovs-vsctl', 'get', 'port', str(intf), 'qos'], text=True).strip()
            queues = subprocess.check_output(['ovs-vsctl', 'get', 'qos', qid, 'queues'], text=True)
            import re
            qos_ids.append((str(intf), qid, re.findall(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', queues)))
        eventlog = out/'server.jsonl'
        start(None, 'sdn.controller', '--events', eventlog, '--log', out/'controller.jsonl', '--mode', a.mode)
        wait_for(out/'controller.jsonl', lambda t: 'controller_ready' in t, processes)
        if net.pingAll() != 0:
            raise RuntimeError('Connectivity test failed')
        for intf in [access.intf1, access.intf2]:
            intf.config(delay='5ms', loss=a.loss)
        start(server, 'emergency.server', '--token', 'lab-secret', '--log', eventlog)
        for i, client in enumerate(clients):
            start(client, 'emergency.client', '--server', '10.0.0.1', '--client', client.name,
                  '--duration', a.count*a.interval+30, '--log', out/f'client{i}.jsonl', '--drop-ack', a.drop_ack)
        wait_for(eventlog, lambda t: all(f'"client": "{c.name}"' in t for c in clients), processes)
        if a.mode == 'priority':
            wait_for(out/'controller.jsonl', lambda t: all(f'"client": "{c.name}"' in t for c in clients), processes)
        if a.congested:
            start(sink, 'experiments.traffic', 'sink')
            start(bg, 'experiments.traffic', 'send', '--target', '10.0.0.11')
            time.sleep(2)
        # Publisher runs inside srv namespace. Acceptance failures abort the experiment.
        for i in range(a.count):
            result = server.cmd(sys.executable, '-m emergency.publish --server 10.0.0.1 --token lab-secret --text', f'alert-{i}')
            if "'type': 'published'" not in result:
                raise RuntimeError('Publish failed: '+result)
            time.sleep(a.interval)
        time.sleep(3)
        for bridge in ['s1', 's2']:
            for command in ['dump-flows', 'queue-stats']:
                result = subprocess.check_output(['ovs-ofctl', '-O', 'OpenFlow13', command, bridge], text=True)
                (out/f'{bridge}-{command}.txt').write_text(result)
    finally:
        for proc in processes:
            proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        for handle in handles:
            handle.close()
        for port, qid, queues in qos_ids:
            subprocess.run(['ovs-vsctl', 'clear', 'port', port, 'qos'], check=False)
            subprocess.run(['ovs-vsctl', 'destroy', 'qos', qid], check=False)
            for queue in queues:
                subprocess.run(['ovs-vsctl', 'destroy', 'queue', queue], check=False)
        net.stop()
    from experiments.summarize import summarize
    summary = summarize(out)
    (out/'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
