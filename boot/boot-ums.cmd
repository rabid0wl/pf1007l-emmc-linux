# FEL flasher boot: flasher kernel (zImage-ums, mass storage only). /init self-tests the eMMC,
# shows the result on the panel, and exports the eMMC to the host. No serial console.
setenv bootargs console=tty0 rdinit=/init loglevel=5 fbcon=rotate:1 g_mass_storage.removable=1 aeezo.ums
bootz 0x42000000 0x43400000 0x43000000
