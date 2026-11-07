#!/bin/bash
# RAM-only boot of mainline Linux on the AEEZO frame over USB FEL.
# Get the frame into FEL first: `adb reboot efex` from stock Android.
#
#   ./fel-boot.sh          normal bring-up boot: g_multi kernel, root shell on /dev/ttyACM*
#   ./fel-boot.sh diag     U-Boot eMMC diagnostics, results in /proc/cmdline (aeezo.ubdiag=...)
#   ./fel-boot.sh install  DESTRUCTIVE: wipe the eMMC and install the OS from RAM (see STATUS.md)
#   ./fel-boot.sh ums      flasher boot: zImage-ums (mass storage only); /init self-tests the
#                          eMMC (verdict on the panel) and exports it to this host as a USB disk
#
# Only `install` writes to the frame's storage; the other modes are RAM-only, and a power cycle
# restores whatever is on the eMMC.
set -euo pipefail
cd "$(dirname "$0")"
K=linux-7.3.1/arch/arm/boot

RAMDISK=initramfs.uimg
if [ "${1:-}" = ums ]; then
	KERNEL=zImage-ums SCR=boot-ums.scr
elif [ "${1:-}" = wtest ]; then
	# eMMC WRITE test at 400kHz..52MHz (1MiB at the 4GiB mark); verdicts on the panel
	KERNEL=$K/zImage SCR=boot-wtest.scr
elif [ "${1:-}" = diag ]; then
	# read-only: U-Boot runs its eMMC steps one by one; exit codes land in /proc/cmdline (aeezo.ubdiag)
	KERNEL=$K/zImage SCR=boot-diag.scr
elif [ "${1:-}" = install ]; then
	# DESTRUCTIVE: U-Boot CRC-checks the eMMC, then /init wipes it and installs payload/
	# (rootfs + U-Boot) from RAM, verifies, and reboots into the eMMC. Watch the panel.
	KERNEL=$K/zImage SCR=boot-install.scr RAMDISK=initramfs-install.uimg
else
	KERNEL=$K/zImage SCR=boot.scr
fi

if ! lsusb -d 1f3a:efe8 >/dev/null; then
	echo "frame is not in FEL (1f3a:efe8); run: adb reboot efex" >&2
	exit 1
fi

# Addresses match U-Boot's sunxi defaults for >256MB RAM (kernel/fdt/script/ramdisk).
UBOOT=${UBOOT:-u-boot/u-boot-sunxi-with-spl.bin}
sudo sunxi-fel -v -p uboot "$UBOOT" \
	write 0x42000000 "$KERNEL" \
	write 0x43000000 "$K/dts/allwinner/sun8i-a33-aeezo-u708hc.dtb" \
	write 0x43100000 "$SCR" \
	write 0x43400000 "$RAMDISK"

if [ "${1:-}" = ums ]; then
	echo "handed off; waiting for the exported eMMC (watch the panel for the self-test verdict)..."
	for _ in $(seq 120); do
		lsblk -dbnpo NAME,SIZE,VENDOR | awk '$2 == 15634268160 && $3 == "Linux" {print; f=1} END {exit !f}' && exit 0
		sleep 1
	done
	echo "no 15634268160-byte Linux gadget disk after 120s" >&2
	exit 2
fi

echo "handed off; waiting for the USB serial gadget (/dev/ttyACM*)..."
for _ in $(seq 60); do
	ls /dev/ttyACM* 2>/dev/null && exit 0
	sleep 1
done
echo "no ttyACM after 60s" >&2
exit 2
