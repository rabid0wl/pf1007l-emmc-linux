# FEL installer boot. U-Boot first proves it can read the eMMC (the same driver path it will
# boot from): CRC32 of the first 16MiB is handed to the installer, which refuses to write
# unless it matches the stock backup.
setenv ucrc none
setenv udev none
# After an interrupted write the eMMC can take >1s to come ready at power-up (U-Boot's CMD1
# window); retry init for up to ~10s before giving up.
for try in 1 2 3 4 5 6 7 8 9 10; do
	if test "${udev}" = none; then
		if mmc dev 1 && mmc read 0x48000000 0 0x8000; then
			crc32 0x48000000 0x1000000 0x47fffff0
			setexpr.l ucrc *0x47fffff0
			setenv udev 1
		else
			sleep 1
			mmc rescan
		fi
	fi
done
setenv bootargs console=tty0 console=ttyGS0,115200 rdinit=/init loglevel=5 fbcon=rotate:1 g_multi.removable=1 aeezo.install aeezo.ubootcrc=${ucrc} aeezo.ubootdev=${udev}
bootz 0x42000000 0x43400000 0x43000000
