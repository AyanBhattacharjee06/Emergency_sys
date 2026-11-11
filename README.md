# Emergency Notification Network

UDP socket programming mini project with a Python SDN controller, OpenFlow 1.3,
Open vSwitch QoS and reproducible Mininet experiments.

## What is implemented

- Multiple subscribers register and refresh endpoint-bound leases over UDP.
- Authorized publishers submit ordinary or emergency notifications.
- Server fans out individual UDP datagrams to registered subscribers.
- Optional application-level acknowledgements, bounded retries, unique message
  IDs and client duplicate suppression. Four attempts total, 250 ms apart.
- Emergency notifications carry DSCP EF (46). Normal messages carry DSCP 0.
- A central controller consumes registration events and installs per-subscriber
  emergency classification rules on both switches. Registrations refresh every
  two seconds; rules expire after six seconds without refresh.
- A real Linux HTB queue reserves 800 Kbps of the 1 Mbps trunk for emergency
  traffic. Flow-table priority selects a classifier; the queue provides the
  bandwidth treatment. These are separate mechanisms.
- Background UDP traffic saturates the same trunk used by notifications.
- JSONL logs and a summary report measure unique delivery loss, first-reception
  latency, confirmation latency, retry count and unconfirmed deliveries.

## Architecture

```text
srv 10.0.0.1 ---- s1 ===== 1 Mbps trunk ===== s2 ---- c1 10.0.0.2
bg  10.0.0.10 ---/                            |---- c2 10.0.0.3
                                             |---- c3 10.0.0.4
                                             \---- sink 10.0.0.11

server registration event log --> Python SDN controller
Python controller -- OpenFlow 1.3 via ovs-ofctl --> s1, s2
```

The controller runs in the root namespace. It programs the OVS local management
socket through `ovs-ofctl`, rather than using a remote controller TCP connection.
This is a centralized SDN control process, with OVS handling L2 learning via
NORMAL actions. It does not implement a remote OpenFlow wire-protocol server.
Application/control-plane integration uses a shared local JSONL event stream;
this is appropriate for a single-VM Mininet lab, not a distributed deployment.

The screenshot requires UDP, subscriber registration, emergency classification,
priority forwarding, confirmation, congestion, latency and loss measurement.
The supplied rubric additionally requires dynamic SDN, robustness, comparison,
reproducibility and final GitHub documentation. This repository supplies code and
instructions. All eight application tests and all six Mininet scenarios have now
passed in UbuntuVM. See [RESULTS.md](RESULTS.md) for measured results and evidence.
GitHub publication still needs a repository destination.

## Quick local demo (Windows or Linux, Python 3.10+)

No third-party Python packages are needed for the application. From this folder,
open separate terminals:

```powershell
python -m emergency.server --token lab-secret
python -m emergency.client --client alice --port 9001 --log results/alice.jsonl
python -m emergency.client --client bob --port 9002 --log results/bob.jsonl
python -m emergency.publish --token lab-secret --text "Evacuate building A"
```

Wait until clients have registered before publishing. Each client prints received
alerts. `--no-confirm` disables acknowledgement/retry for that notification.
`--level normal` sends an ordinary notification. `--drop-ack 1` on a client
simulates a silent acknowledgement path; the server will retry then record
`unconfirmed`. Registration refresh makes the service tolerate a lost initial
registration. A publish timeout is an uncertain outcome; publishing again creates
a new notification ID. Publisher requests are not automatically retried.

Run application tests:

```text
python -m unittest discover -s tests -v
```

## Ubuntu Mininet setup

Use an Ubuntu 22.04 VM with sudo and Internet connectivity, as described in the
provided installation guide. Copy this whole folder into the VM. In its terminal:

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3
sudo systemctl start openvswitch-switch
sudo mn
# At the mininet> prompt: pingall, then exit
```

If the default controller is unavailable on your installed Mininet version,
go directly to our experiment which explicitly installs forwarding rules.
Avoid running other Mininet projects
at the same time: this lab owns switches named s1 and s2.

## Reproducible experiments

Run from the project directory in Ubuntu. Every output directory must be new:

```bash
sudo python3 -m experiments.run --mode baseline --output results/baseline-idle
sudo python3 -m experiments.run --mode priority --output results/priority-idle
sudo python3 -m experiments.run --mode baseline --congested --output results/baseline-busy
sudo python3 -m experiments.run --mode priority --congested --output results/priority-busy
sudo python3 -m experiments.run --mode priority --congested --loss 5 --output results/priority-loss
sudo python3 -m experiments.run --mode priority --drop-ack 1 --output results/ack-failure
python3 -m experiments.summarize results/baseline-busy results/priority-busy
```

Alternatively, `sudo bash run_experiments.sh` checks and installs missing packages,
starts Open vSwitch, runs the application tests and all six scenarios, and saves
terminal output to `results/ubuntu-terminal.log`. Package installation needs Internet
access; individual experiments do not download anything.

The runner creates hosts and queues, starts the controller and application,
checks registrations and rule installation, publishes 60 alerts to three clients,
waits for retries, saves counters and stops its processes/topology. Both modes use
the same queue setup; baseline sends all packets to queue 0. Priority mode maps
registered emergency flows to queue 1. Background offered load is approximately
4.8 Mbps. The server access link adds 5 ms per direction; `--loss 5` injects
nominal 5% loss there in each direction, after the connectivity check. Keeping
impairment on the access link avoids replacing the trunk's HTB queue discipline.

Collect at least three runs per condition with different output folders. Compare
means and p95 values across runs; include the machine/VM configuration. Check
the `priority_installed` events, emergency flow matches and queue-1 counters to
demonstrate the network treatment. Under idle conditions the difference may be
small. CPU scheduling and retries can influence latency, so report actual results.

If interrupted, the runner attempts cleanup. `sudo mn -c` is the guide's recovery
command for a dedicated lab VM. It can affect other Mininet sessions.

## Protocol and metrics

JSON datagrams are limited to 8192 bytes. Server listens on UDP 9000; subscriber
notifications go to the registered source endpoint (9001 in each isolated Mininet
host). Types: `register`, `registered`, `publish`, `published`, `notification`,
`ack`, `error`. Publisher payload includes token, text, level and confirm flag.
Notification includes UUID, original send timestamp, text, level and confirm.
ACK includes notification UUID and client ID. ACK source must match its pending
endpoint. Retries retain the UUID and timestamp so latency includes recovery time.

Latency is first unique receipt time minus original server timestamp. Mininet
hosts share the same machine clock. Separate physical hosts require synchronized
clocks; confirmation timing uses the server's monotonic clock. Delivery loss is
missing unique (notification, subscriber) pairs divided by expected pairs, after
the retry window. It is application delivery loss, not raw link packet loss.
`unconfirmed` may mean a missing ACK even when delivery succeeded. Use packet
captures or switch statistics for raw datagram loss analysis.

## Scope and security

This is a trusted-lab prototype. Publisher token is a shared plaintext lab secret;
UDP is unencrypted. Subscriber registration has no cryptographic authentication.
Endpoint binding and ID ownership checks prevent simple accidental redirection,
but do not provide protection against source spoofing. No persistence of pending
deliveries across server restarts is provided. The subscriber deduplication set
is in memory for its process lifetime. Do not expose this service to the Internet
or treat it as a real public-safety service.


References: supplied SDN rubric and Mininet installation PDFs; official
[OVS QoS documentation](https://docs.openvswitch.org/en/stable/faq/qos/) and
[OVS database schema](https://www.openvswitch.org/support/dist-docs/ovs-vswitchd.conf.db.5.html).
