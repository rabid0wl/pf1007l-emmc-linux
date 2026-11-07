# FEL bring-up: everything already sits in RAM, nothing touches eMMC or SD.
setenv bootargs console=tty0 console=ttyGS0,115200 rdinit=/init loglevel=7 fbcon=rotate:1 aeezo.wtest
bootz 0x42000000 0x43400000 0x43000000
