# Ubuntu Mininet validation

Executed on 3 November 2026 in UbuntuVM with 4 GB RAM and 2 virtual CPUs.
The installed packages reported Mininet 2.3.0 and Open vSwitch 3.7.1.
All 8 application tests passed in Ubuntu, including endpoint ownership, multiple
subscribers, acknowledgements, bounded retries, expiry, malformed input and
duplicate suppression. All six scenarios completed. Each topology passed its
initial connectivity check: 30 of 30 pings received.

## Measured results

Each scenario published 60 alerts to three subscribers: 180 expected deliveries.
Latency measures the first unique reception relative to the original server send
timestamp. Retransmission recovery time is included.

| Scenario | Received / expected | Delivery loss | Mean latency (ms) | p95 latency (ms) | Retries | Unconfirmed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline, idle | 180 / 180 | 0% | 7.47 | 10.57 | 0 | 0 |
| Priority, idle | 180 / 180 | 0% | 8.08 | 10.50 | 0 | 0 |
| Baseline, congested | 180 / 180 | 0% | 756.56 | 978.81 | 432 | 0 |
| Priority, congested | 180 / 180 | 0% | 6.95 | 8.95 | 0 | 0 |
| Priority, congestion + nominal 5% access-link loss | 180 / 180 | 0% | 28.57 | 262.38 | 24 | 0 |
| Priority, all notification ACKs suppressed | 180 / 180 | 0% | 7.22 | 9.60 | 540 | 180 |

In this run, priority forwarding reduced mean congestion latency by approximately
99.08%. Under nominal 5% configured link loss, bounded retries recovered all
expected application deliveries. This does not mean zero raw datagram loss.
When ACKs were intentionally suppressed, every alert was still received once by
the application, but the server correctly exhausted its retry budget and marked
every delivery unconfirmed.

## SDN evidence

The priority-congested `s1-queue-stats.txt` records 180 packets and 33,810 bytes in
queue 1 on trunk port 3. Background traffic used queue 0 (1,705 packets).
The `s1-dump-flows.txt` snapshot contains three per-subscriber emergency rules
with cookie `0xe911`, priority 200, a six-second hard timeout, source 10.0.0.1,
UDP source port 9000, subscriber port 9001, and TOS 184 (DSCP 46).
Their actions select queue 1 before NORMAL forwarding.
Controller JSONL events record dynamic rule installation as registrations arrive.

## Reproduction and evidence

Run `sudo bash run_experiments.sh` from the project folder in Ubuntu. The recorded
batch is `results/ubuntu-20261103-163549/`. Each scenario contains config.json,
summary.json, server and subscriber JSONL logs, controller events, component logs,
and switch flow/queue counters. The shared terminal log is
`results/ubuntu-terminal.log`.

These are measurements from one batch on one VM, rather than repeated trials or
production guarantees. Repeat each condition at least three times before making
statistical claims in a final report. The test uses a shared 1 Mbps trunk, about
4.8 Mbps of offered background UDP traffic, and a 5 ms delay in each direction
on the server access link. Baseline and priority use the same queue configuration;
only emergency queue selection changes. Source code and results are ready locally;
publishing to GitHub needs a repository destination from the project owner.
