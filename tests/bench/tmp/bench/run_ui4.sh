#!/bin/bash
T=/tmp/target
rm -f $T/etc/ollamabuntu/pools.json $T/etc/ollamabuntu/placements.json $T/etc/ollamabuntu/ollama-main.env $T/var/lib/ollamabuntu/gpu-inventory.json $T/tmp/systemctl-calls.log
rm -rf $T/etc/ollamabuntu/pools
mkdir -p /tmp/gpufake/units; cp /tmp/gpufake/ollama.log.3gpu /tmp/gpufake/units/ollama.service.log; rm -f /tmp/gpufake/units/ollama-pool@*.log
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); reset_users
rm -f /tmp/gpufake/units/ollamabuntu-router.service.log
EXTRA_ENV="OB_OLLAMA_LOG_DIR=/tmp/gpufake/units OB_OLLAMA_MAIN=127.0.0.1:11434" CLIENT="node /tmp/uitest/ui4.js" bash /tmp/bench/run.sh
