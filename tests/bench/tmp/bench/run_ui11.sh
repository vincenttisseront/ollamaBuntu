#!/bin/bash
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); T=/tmp/target; reset_users
rm -rf $T/tmp/reqs $T/tmp/rt-etc2; mkdir -p $T/tmp/reqs $T/tmp/rt-etc2; chown -R $(chroot $T id -u ollama):$(chroot $T id -g ollama) $T/tmp/reqs; chmod 755 $T/tmp/rt-etc2
rm -f $T/var/lib/ollamabuntu/metrics.json
EXTRA_ENV="OB_ROUTER_REQLOG=/tmp/reqs/requests.jsonl OB_METRICS_INTERVAL=1 OB_NVIDIA_SMI=/usr/local/bin/nvidia-smi-fake" CLIENT="node /tmp/uitest/ui11.js" bash /tmp/bench/run.sh
