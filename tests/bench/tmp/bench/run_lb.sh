#!/bin/bash
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); T=/tmp/target; reset_users
EXTRA_ENV="OB_FLEET_INTERVAL=2" CLIENT="python3 /tmp/bench/lb_test.py" bash /tmp/bench/run.sh
