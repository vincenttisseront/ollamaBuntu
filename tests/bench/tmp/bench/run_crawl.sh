#!/bin/bash
exec 9>/tmp/bench/.lock; flock 9   # une seule exécution de test à la fois (ports et système de test partagés)
T=/tmp/target
source <(sed -n '/^reset_users()/,/^}/p' /tmp/bench/regression.sh); reset_users
mkdir -p $T/usr/local/lib/ollamabuntu/admin/web/i18n; cp /home/claude/ob/ollamabuntu/src/rootfs/usr/local/lib/ollamabuntu/admin/web/i18n/en.json $T/usr/local/lib/ollamabuntu/admin/web/i18n/en.json
for f in app.js app.css index.html; do cp /home/claude/ob/ollamabuntu/src/rootfs/usr/local/lib/ollamabuntu/admin/web/$f $T/usr/local/lib/ollamabuntu/admin/web/$f; done
sed "s/@@OB_VERSION@@/2026.11.05-1000/" /home/claude/ob/ollamabuntu/src/rootfs/usr/local/lib/ollamabuntu/admin/server.py > $T/usr/local/lib/ollamabuntu/admin/server.py
WEBUI=1 CLIENT="node /tmp/uitest/crawl.js" bash /tmp/bench/run.sh
