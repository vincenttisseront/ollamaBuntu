#!/bin/bash
T=/tmp/target
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); reset_users
rm -f $T/etc/ollamabuntu/firewall.json $T/tmp/nft-loaded $T/tmp/nft-calls.log
CLIENT="node /tmp/uitest/ui6.js" bash /tmp/bench/run.sh
