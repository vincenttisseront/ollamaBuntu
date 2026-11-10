#!/bin/bash
T=/tmp/target
for d in dev proc sys run; do mountpoint -q $T/$d || mount --bind /$d $T/$d; done
mkdir -p $T/mnt/ob; mountpoint -q $T/mnt/ob || mount --bind /tmp/upsrc $T/mnt/ob
chroot $T /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin OB_PROGRESS_INTERVAL=0.5 OB_HEARTBEAT=2 bash /mnt/ob/update.sh --target / --source /mnt/ob > /tmp/upd2.out 2>&1
echo "code de sortie : $?" >> /tmp/upd2.out
umount $T/mnt/ob
