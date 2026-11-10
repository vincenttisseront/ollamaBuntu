#!/bin/bash
T=/tmp/target; rm -rf $T/tmp/crypt; mkdir -p $T/tmp/crypt; truncate -s 32M $T/tmp/crypt/disk.img
printf '%s' "TEMP-installation-ISO-9fK2" | cryptsetup luksFormat --type luks2 --pbkdf pbkdf2 --pbkdf-force-iterations 1000 --batch-mode --key-file=- $T/tmp/crypt/disk.img
printf '%s\n' "TEMP-installation-ISO-9fK2" | OB_CRYPT_DEV=$T/tmp/crypt/disk.img OB_CRYPT_STATE=$T/tmp/crypt/state OB_CRYPT_LOG=$T/tmp/crypt/c.log OB_CRYPT_NO_INITRAMFS=1 OB_CRYPT_PBKDF_ARGS="--pbkdf pbkdf2 --pbkdf-force-iterations 1000" $T/usr/local/sbin/ollamabuntu-crypt setup
