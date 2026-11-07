# FEL diagnostic boot (read-only). U-Boot's console is recorded in RAM (CONFIG_CONSOLE_RECORD);
# Linux boots with mem=896M so it never touches the top 128MiB where U-Boot lives, and the log is
# read back through /dev/mem. Exit codes also go on the cmdline (aeezo.ubdiag).
setenv fdt_high 0xffffffff
setenv initrd_high 0xffffffff
echo AEEZO-DIAG-BEGIN
mmc list
dm tree
setenv r ""
mmc dev 1;                              setenv r "${r}dev=$? "
mmc rescan;                             setenv r "${r}rescan=$? "
mmc info;                               setenv r "${r}info=$? "
mmc read 0x48000000 0 1;                setenv r "${r}read1=$? "
mmc read 0x48000000 0 0x8000;           setenv r "${r}read16m=$? "
crc32 0x48000000 0x1000000 0x47fffff0
setexpr.l c *0x47fffff0;                setenv r "${r}crc=${c} "
echo AEEZO-REGS PC_CFG0-3 at 0x01c20848
md.l 0x01c20848 4
echo AEEZO-REGS PC_DRV0-1 at 0x01c2085c, PC_PULL0-1 at 0x01c20864
md.l 0x01c2085c 4
echo AEEZO-REGS BUS_GATE0 0x01c20060, BUS_RST0 0x01c202c0, SDMMC2_CLK 0x01c20090
md.l 0x01c20060 1
md.l 0x01c202c0 1
md.l 0x01c20090 1
pinmux status -a
echo AEEZO-DIAG-END ${r}
setenv bootargs console=tty0 console=ttyGS0,115200 rdinit=/init loglevel=7 fbcon=rotate:1 g_multi.removable=1 mem=896M "aeezo.ubdiag=${r}"
bootz 0x42000000 0x43400000 0x43000000
