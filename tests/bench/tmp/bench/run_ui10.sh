#!/bin/bash
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); T=/tmp/target; reset_users
rm -f $T/etc/ollamabuntu/fleet.json $T/etc/ollamabuntu/fleet-routes.json $T/etc/ollamabuntu/custom-models.json $T/etc/ollamabuntu/ai-policy.json
EXTRA_ENV="OB_FLEET_INTERVAL=2" CLIENT="node /tmp/uitest/ui10.js" bash /tmp/bench/run.sh
find $T/usr/share/ollama/.ollama/models -type d -path "*library/assistant-parc" -exec rm -rf {} + 2>/dev/null || true
