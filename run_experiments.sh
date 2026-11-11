#!/usr/bin/env bash
# Run from Ubuntu: sudo bash run_experiments.sh
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run this script with sudo.' >&2
    exit 1
fi
mkdir -p results
exec > >(tee -a results/ubuntu-terminal.log) 2>&1
if ! python3 -c 'import mininet.net' 2>/dev/null || ! command -v ovs-ofctl >/dev/null; then
    apt-get update
    apt-get install -y mininet openvswitch-switch python3
fi
systemctl start openvswitch-switch
command -v ovs-ofctl >/dev/null
ovs-vsctl show >/dev/null
python3 -m unittest discover -s tests -v
batch="results/ubuntu-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$batch"
for mode in baseline priority; do
    python3 -m experiments.run --mode "$mode" --output "$batch/$mode-idle"
    python3 -m experiments.run --mode "$mode" --congested --output "$batch/$mode-busy"
done
python3 -m experiments.run --mode priority --congested --loss 5 --output "$batch/priority-loss"
python3 -m experiments.run --mode priority --drop-ack 1 --output "$batch/ack-failure"
python3 -m experiments.summarize "$batch"/* | tee "$batch/comparison.txt"
echo "Experiment evidence saved in $batch"
