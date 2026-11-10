#!/bin/bash
source <(sed -n "/^reset_users()/,/^}/p" /tmp/bench/regression.sh); T=/tmp/target; reset_users
rm -rf $T/tmp/reqs; mkdir -p $T/tmp/reqs; chown $(chroot $T id -u ollama):$(chroot $T id -g ollama) $T/tmp/reqs
rm -f $T/etc/ollamabuntu/fleet.json $T/etc/ollamabuntu/fleet-routes.json $T/etc/ollamabuntu/balance.json $T/etc/ollamabuntu/request-log.json
EXTRA_ENV="OB_FLEET_INTERVAL=2 OB_ROUTER_ADDR=127.0.0.1:18434 OB_ROUTER_REQLOG=/tmp/reqs/requests.jsonl OB_METRICS_INTERVAL=1" CLIENT="node /tmp/uitest/ui13.js" bash /tmp/bench/run.sh
rm -f $T/etc/ollamabuntu/fleet.json $T/etc/ollamabuntu/fleet-routes.json $T/etc/ollamabuntu/balance.json $T/etc/ollamabuntu/request-log.json
