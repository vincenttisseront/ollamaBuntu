#!/bin/bash
set -e
PM="" bash /tmp/run-build.sh /tmp/fakeiso/ubuntu-24.04.3-live-server-amd64.iso 2>&1 | grep -E "rc=|ERREUR|fichiers$"
rm -f /tmp/obw/ollamabuntu-test.iso*
tar -xpf /tmp/obw/work/iso/ollamabuntu/rootfs.tar -C /tmp/target --numeric-owner --no-overwrite-dir ./usr/local/lib/ollamabuntu ./etc/ollamabuntu/build-info.json
