#!/bin/bash
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); T=/tmp/target; reset_users
rm -f $T/etc/ollamabuntu/fleet.json
EXTRA_ENV="OB_FLEET_INTERVAL=2" CLIENT="node /tmp/uitest/ui9.js" bash /tmp/bench/run.sh
