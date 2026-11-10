#!/bin/bash
T=/tmp/target
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); reset_users
rm -f $T/tmp/smi-n
EXTRA_ENV="OB_NVIDIA_SMI=/usr/local/bin/nvidia-smi-fake" CLIENT="node /tmp/uitest/ui8.js" bash /tmp/bench/run.sh
