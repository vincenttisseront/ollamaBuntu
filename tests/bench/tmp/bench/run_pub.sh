#!/bin/bash
T=/tmp/target
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); reset_users
rm -rf $T/etc/ollamabuntu/publication.json $T/etc/ollamabuntu/router-tls $T/tmp/router-usage.json
EXTRA_ENV="OB_OLLAMA_MAIN=127.0.0.1:11434" CLIENT="python3 /tmp/bench/pub_test.py" bash /tmp/bench/run.sh
