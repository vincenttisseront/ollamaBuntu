#!/bin/bash
T=/tmp/target
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); reset_users
python3 /tmp/chatt/mock.py & M=$!
EXTRA_ENV="OB_OLLAMA=127.0.0.1:11999" CLIENT="node /tmp/uitest/ui7.js" bash /tmp/bench/run.sh
kill $M
