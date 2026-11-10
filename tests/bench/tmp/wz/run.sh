#!/bin/bash
T=/tmp/target
for d in dev dev/pts proc sys run; do mountpoint -q $T/$d || mount --bind /$d $T/$d; done
rm -f $T/var/lib/ollamabuntu/configured
python3 ${DRIVER:-/tmp/wz/drive.py} /usr/local/sbin/ollamabuntu-setup --firstboot tty1
for d in run sys proc dev/pts dev; do umount -l $T/$d; done
