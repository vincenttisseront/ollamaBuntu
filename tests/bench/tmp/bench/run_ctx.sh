#!/bin/bash
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); T=/tmp/target; reset_users
rm -f $T/etc/ollamabuntu/model-context.json; mkdir -p $T/tmp/reqs; chown $(chroot $T id -u ollama):$(chroot $T id -g ollama) $T/tmp/reqs
CLIENT="bash /tmp/bench/ctx_client.sh" bash /tmp/bench/run.sh
