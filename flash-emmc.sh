#!/bin/bash
# LEGACY PATH, kept for reference: on this board the musb gadget stalls under sustained bulk
# traffic, so exporting the eMMC as a USB disk was unreliable. The install that worked is
# `./fel-boot.sh install` (everything rides in RAM over FEL; see README).
#
# Install U-Boot + the Alpine rootfs onto the frame's eMMC, exported to this host as a USB disk
# by the FEL-booted kernel's g_multi gadget:
#   sudo ./frame-sh 'echo /dev/mmcblkN > /sys/devices/platform/soc/1c19000.usb/musb-hdrc.2.auto/gadget.0/lun0/file'
# DESTRUCTIVE: wipes the eMMC. Recovery = your own full eMMC backup (see README: take one first).
#
# STOCK_SHA256_64M = sha256 of the first 64MiB of YOUR frame's stock eMMC backup, e.g.
#   head -c 67108864 mmcblk0.img | sha256sum
# The script refuses to write unless the exported disk reads back exactly that (proves the USB
# data path before anything is destroyed). Already wiped? SKIP_READ_CHECK=1.
set -euo pipefail
cd "$(dirname "$0")"

EMMC_BYTES=${EMMC_BYTES:-15634268160}   # 16GB Samsung MAG2GC; check yours: blockdev --getsize64
DISK_ID=0xaee20000          # MBR id -> root PARTUUID=aee20000-01 (fstab, extlinux.conf)
PART_START=8192             # 4MiB; SPL + U-Boot live at 8KiB..~520KiB
MNT=/mnt/aeezo-root

# 1. find exactly one disk that is unmistakably the frame's exported eMMC
mapfile -t cands < <(lsblk -dbnpo NAME,SIZE,TRAN,VENDOR,MODEL |
	awk -v sz=$EMMC_BYTES '$2 == sz && $3 == "usb" && $4 == "Linux" && $5" "$6 == "File-Stor Gadget" {print $1}')
if [ "${#cands[@]}" -ne 1 ]; then
	echo "need exactly one ${EMMC_BYTES}-byte 'Linux File-Stor Gadget' USB disk, found ${#cands[@]}: ${cands[*]:-none}" >&2
	exit 1
fi
DEV=${cands[0]}
echo "target: $DEV ($(lsblk -dno SIZE,VENDOR,MODEL "$DEV"))"

if lsblk -nro MOUNTPOINT "$DEV" | grep -q .; then
	echo "$DEV has mounted partitions; refusing" >&2
	exit 1
fi

# 2. prove the data path before writing: stock image must read back exactly as backed up
if [ "${SKIP_READ_CHECK:-0}" != 1 ]; then
	: "${STOCK_SHA256_64M:?set STOCK_SHA256_64M to the sha256 of the first 64MiB of your stock backup (or SKIP_READ_CHECK=1)}"
	got=$(head -c $((64 * 1024 * 1024)) "$DEV" | sha256sum | cut -d' ' -f1)
	if [ "$got" != "$STOCK_SHA256_64M" ]; then
		echo "first 64MiB sha256 $got != backup $STOCK_SHA256_64M" >&2
		echo "(already wiped by an earlier run? re-run with SKIP_READ_CHECK=1)" >&2
		exit 1
	fi
	echo "read check: first 64MiB matches the backup"
fi

[ -f rootfs/boot/extlinux/extlinux.conf ] && [ -f rootfs/boot/zImage ] || { echo "rootfs/boot incomplete" >&2; exit 1; }
[ -f u-boot/u-boot-sunxi-with-spl.bin ] || { echo "u-boot not built" >&2; exit 1; }

# 3. partition: one bootable ext4 partition from 4MiB to the end
printf 'label: dos\nlabel-id: %s\n\nstart=%d, type=83, bootable\n' "$DISK_ID" "$PART_START" |
	sfdisk --wipe always --wipe-partitions always "$DEV"
partprobe "$DEV"
udevadm settle
PART=${DEV}1
[ -b "$PART" ] || { echo "$PART did not appear" >&2; exit 1; }

# 4. rootfs
mkfs.ext4 -q -F -L aeezo-root "$PART"
mkdir -p "$MNT"
mount "$PART" "$MNT"
trap 'umount "$MNT" 2>/dev/null || true' EXIT
cp -a rootfs/. "$MNT"/
sync
du -sh "$MNT"
umount "$MNT"
trap - EXIT

# 5. bootloader at the 8KiB offset the A33 boot ROM reads, then read it back
dd if=u-boot/u-boot-sunxi-with-spl.bin of="$DEV" bs=1024 seek=8 conv=fsync status=none
sz=$(stat -c %s u-boot/u-boot-sunxi-with-spl.bin)
cmp <(dd if="$DEV" bs=1024 skip=8 iflag=direct status=none | head -c "$sz") u-boot/u-boot-sunxi-with-spl.bin
echo "u-boot verified on disk ($sz bytes)"

sync
blkid "$PART"
sfdisk -l "$DEV"
echo "done. Unload the LUN on the frame, then power-cycle it."
