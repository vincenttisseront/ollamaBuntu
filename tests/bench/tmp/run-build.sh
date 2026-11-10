#!/bin/bash
export PM
cd /tmp/obw
start=$(date +%s)
PRELOAD_MODELS="${PM-}" GRUB_TIMEOUT=8 WORKDIR=/tmp/obw OUTPUT=/tmp/obw/ollamabuntu-test.iso OB_VERSION=${OBV:-2026.11.05-1000} OB_LANG=${OBL:-fr} \
  bash /home/claude/ob/ollamabuntu/build.sh "$@"
rc=$?
echo "rc=$rc  durée=$(( $(date +%s) - start ))s"
