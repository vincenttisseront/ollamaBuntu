#!/bin/bash
T=/tmp/target
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); reset_users
rm -f $T/etc/ollamabuntu/ai-policy.json $T/etc/ollamabuntu/open-webui-policy.env $T/etc/ollamabuntu/custom-models.json $T/etc/ollamabuntu/preload.json $T/etc/ollamabuntu/open-webui.env
CLIENT="python3 /tmp/bench/adv_test.py" bash /tmp/bench/run.sh
rm -f $T/etc/ollamabuntu/open-webui.env
