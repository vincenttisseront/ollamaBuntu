#!/bin/bash
T=/tmp/target
cat > $T/usr/local/bin/docker <<'D'
#!/bin/sh
echo "docker $*" >> /tmp/docker-calls.log
case "$1" in
  inspect) [ -f /tmp/docker-state ] && cat /tmp/docker-state || exit 1 ;;
  run) echo "running|ghcr.io/open-webui/open-webui:main|2026-11-04T10:00:00.123Z" > /tmp/docker-state; echo 0123456789ab ;;
  rm) rm -f /tmp/docker-state ;;
  stop) sed -i 's/^running/exited/' /tmp/docker-state ;;
  start|restart) sed -i 's/^exited/running/' /tmp/docker-state ;;
esac
exit 0
D
printf '#!/bin/sh\necho "systemctl $*" >> /tmp/systemctl-calls.log\ncase "$1" in is-active) echo active;; esac\nexit 0\n' > $T/usr/local/bin/systemctl
chmod +x $T/usr/local/bin/docker $T/usr/local/bin/systemctl
rm -f $T/tmp/docker-state $T/tmp/docker-calls.log $T/etc/ollamabuntu/open-webui.env
