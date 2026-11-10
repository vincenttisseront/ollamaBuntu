#!/bin/bash
T=/tmp/target
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); reset_users
rm -rf $T/etc/ollamabuntu/publication.json $T/etc/ollamabuntu/router-tls
printf '#!/bin/sh\nsleep 3\n' > $T/usr/local/bin/apt-get; chmod +x $T/usr/local/bin/apt-get
EXTRA_ENV="OB_OLLAMA_MAIN=127.0.0.1:11434" CLIENT="node /tmp/uitest/ui5.js" bash /tmp/bench/run.sh
rm -f $T/usr/local/bin/apt-get
