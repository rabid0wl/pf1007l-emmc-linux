# AGENTS.md: the full technical writeup

This file is for you, the coding agent helping someone with a PF1007L / AEEZO A33 frame (and for
humans who want every detail). `README.md` is the short version for people. Everything here comes
from one unit's bring-up. Treat it as a record of what worked on that unit, not a universal guide.

## Rules before you touch a frame

1. **Ask the owner before every write.** Reads are fine. Writing the eMMC (user area *or* the
   `boot0`/`boot1` hardware partitions), running `./fel-boot.sh install`, or running
   `flash-emmc.sh` needs the owner's explicit OK for that specific action.
2. **No writes before a verified full backup** of `mmcblk0`, `mmcblk0boot0` and `mmcblk0boot1`
   (exact byte count + sha256; see "Getting in" below). Without it there is no way back to Android.
3. **Confirm the unit matches before running anything** (see "Is my frame the same board?"):
   - FEL SoC id `1667`.
   - eMMC **exact size**: two sizes exist, 30,535,680 and 30,777,344 sectors. The scripts hard-code
     the first and refuse anything else. Change the constant only after the owner confirms.
   - Wi-Fi chip: AIC8800DC (SDIO `c8a1:c08d`) vs RTL8723DS. The Wi-Fi parts here only cover the AIC.
   - Panel: if the decoded `lcd.ko` table differs from `vendor/sq9365_init.txt`, stop and report.
4. **Stop at the first mismatch** in a hash, size, chip name or gate on the panel. Report it; don't
   work around it. The installer's 8 gates are there to be believed.
5. **Keep dumps private.** Android images and `sys_config` dumps hold Wi-Fi passwords, serials and
   the MAC address. Never commit them, and never commit vendor `.ko`/firmware files.
6. **Before Android is gone, keep the frame offline.** The PF1007L community found that the stock
   vendor app accepts root shell commands from the vendor's server (see the PF1007L docs in
   [wesbos/photo-frame-dashboard](https://github.com/wesbos/photo-frame-dashboard)).
7. **Check upstream community news first.** Many people work on this frame family at once. Skim
   recent issues and PRs in wesbos/photo-frame-dashboard and in this repo before a write.

## The hardware

| Part | What it is | Mainline status |
|---|---|---|
| Board | YHK "A33-Tablet", Android `sys_config` machine name **U708HC**, build name `astar_m86_8723cs` | new DT here (`sun8i-a33-aeezo-u708hc.dts`) |
| SoC | Allwinner **A33** (sun8i, 4x Cortex-A7), `sunxi-fel ver` reports SoC id `1667` | mainline |
| RAM | 1 GB | U-Boot SPL inits all of it (DRAM_CLK 456, ZQ 15291) |
| PMIC | X-Powers AXP223 | mainline |
| eMMC | Samsung **MAG2GC**, 16 GB (30,535,680 sectors = 15,634,268,160 bytes), wired **4-bit** on mmc2 | works with two quirks, see below |
| Panel | 10.1" 800x1280 (native portrait) **MIPI-DSI, 4 lanes**, JD9365-family controller (vendor driver `yhk_zr789_sq9365_101`) | new entry in `panel-jadard-jd9365da-h3.c` (patch 0001) |
| Touch | Silead **gslX680** on i2c-0 @0x40 (reports chip id 0xB4820000) | mainline `silead` driver, vendor firmware |
| Wi-Fi/BT | **AIC8800DC** on SDIO (mmc1), SDIO id `c8a1:c08d` | out of tree: [radxa-pkg/aic8800](https://github.com/radxa-pkg/aic8800) |
| Accelerometer | Silan SC7A20 on i2c-1 @0x19 | not wired up yet |
| Camera | footprint only: vendor config has `vip_used = 0`, i2c probe NACKs everywhere | not populated |
| RTC battery | none (boots in 1970 until NTP) | |

The listing says "32GB" and "light sensor". This unit has a 16 GB eMMC, and there's no I2C light
sensor: the only thing on the sensor bus is the accelerometer. An analog sensor on the ADC wasn't
checked.

Units vary. Other owners report a larger 30,777,344-sector eMMC, and some units ship with Realtek
RTL8723DS Wi-Fi instead of the AIC8800DC (the vendor build name, `..._8723cs`, is no guide). The
install scripts check the eMMC's exact size before writing anything. For the larger part, change
`15634268160` in `initramfs/initramfs-install-init`, `tools/aeezo-uboot-restore` and
`flash-emmc.sh` (`EMMC_BYTES`) to your `blockdev --getsize64` value.

### Is my frame the same board?

The brand on the box tells you nothing. The unit here came from this listing:
<https://www.amazon.com/dp/B0GJ5D2XP6> ("AEEZO", AiMOR app, 10.1" 1280x800 touch). Look for this
fingerprint instead:

- Stock firmware is Android 6.0.1 with a 3.4.39 kernel, an `-eng` build with test-keys, and (on
  this unit) **`adbd` running as root with no authorization prompt**. If
  yours is locked down, the PF1007L docs in
  [wesbos/photo-frame-dashboard](https://github.com/wesbos/photo-frame-dashboard) cover other ways in. Plug it into a PC with a *data* cable
  (the included cable is charge-only). It shows up as `1f3a:1002`.
- `adb shell getprop` shows `astar_m86`-style build names. `/proc/cmdline` carries
  `androidboot.mac=...`.
- The vendor `sys_config` (in the Android image) names the machine `U708HC`. It describes the
  panel as `lcd_if = 4` (DSI), 4 lanes, 800x1280, 67 MHz dclk, and touch as `gsl_m86_hd`.
- `adb reboot efex` → the frame enumerates as `1f3a:efe8` (Allwinner FEL), and `sunxi-fel ver`
  says `soc=00001667` (A33).

Other A33 frames will be close, but pins, regulators and the panel init table come from *this*
board's vendor config. Check yours against the comments in the DT, which cite the `sys_config`
key for every value.

---

## How it went: stock Android → standalone eMMC boot

### 0. Getting in, and the safety net

Root adb with no auth means you can image the whole eMMC before changing anything. **Do that
first**, and check the byte count (the first attempt here "succeeded" with 36 bytes):

```sh
adb exec-out "dd if=/dev/block/mmcblk0 bs=4194304 2>/dev/null" > mmcblk0.img   # 15634268160 bytes
adb exec-out "dd if=/dev/block/mmcblk0boot0 2>/dev/null" > mmcblk0boot0.img
adb exec-out "dd if=/dev/block/mmcblk0boot1 2>/dev/null" > mmcblk0boot1.img
```

Two gotchas. `adb exec-out` merges the device's stderr into the stream, so the `2>/dev/null`
has to go *inside* the quoted command. Android 6's toolbox `dd` rejects `bs=4M`, so spell it in
bytes. Device names can differ on your unit, so check `/dev/block/` first.

The A33's FEL mode lives in mask ROM. Whenever the ROM finds nothing bootable it drops to FEL, so
a wiped eMMC can't brick the board. You can always write the backup back.

### 1. RAM-only boot over FEL

`adb reboot efex` puts the frame in FEL. From there, [sunxi-tools](https://github.com/linux-sunxi/sunxi-tools)
`sunxi-fel` loads U-Boot's SPL, U-Boot, a kernel, a DTB, a boot script and an initramfs straight
into RAM (`fel-boot.sh`). Nothing touches the eMMC. A power cycle returns to whatever is installed.

U-Boot starts from `q8_a33_tablet_800x480_defconfig` with video off. Its SPL brings up all
1 GB (aliasing read-back test passed at 0x40000000, 0x60000000 and 0x7fff0000). The bring-up
kernel uses `g_multi`, so the frame shows up on the host as `/dev/ttyACM*` with a root shell, and
`frame-sh` runs one command over that link and returns its output.

### 2. The panel: lit, but black, until the vendor table and non-burst DSI

The vendor driver name suggested a JD9365, and mainline's `panel-jadard-jd9365da-h3` already
has a 10.1" 800x1280 entry (`chongzhou,cz101b4001`). Using it gave a lit, black screen. What
fixed it:

- **The vendor init table, decoded from `lcd.ko`.** The vendor panel module stores its init
  sequence as 72-byte records `{u32 cmd; u32 count; u8 data[64]}`. `0xFF0` means a delay and
  `0xFF1` ends the table. `tools/extract_init.py` decodes it. The result is
  `vendor/sq9365_init.txt`, and as C it's `vendor/aeezo_init.c.inc`. `tools/compare_init.py` scores it
  against every table in the mainline driver: it's 97% the CZ101B4001 sequence (201 writes vs 197),
  and the few writes that differ matter.
- **Vendor timings.** Allwinner's `lcd_hbp`/`lcd_vbp` *include* the sync width, so subtract it
  when converting to a `drm_display_mode`: 67 MHz, h 800+18+18+18, v 1280+20+4+10.
- **Non-burst video mode.** The vendor config has `lcd_dsi_if = 0`. The mainline entry asks for
  burst mode. Also, the sun6i DSI host only reads `MIPI_DSI_MODE_VIDEO_BURST`. It ignores
  `SYNC_PULSE`, `NO_EOT` and `LPM`, so burst on or off is the only knob that matters.
- PH7 is the panel reset (active-low). Supplies are `dc1sw` + `eldo3` (3.3 V).

Patch 0001 adds an `aeezo,u708hc-panel` entry. It also has a bring-up-only `aeezo_burst` module
parameter for toggling burst mode live. Drop that before sending the patch upstream.

### 3. Touch

The touch controller works with mainline `silead` (`compatible = "silead,gsl1680"`). Its firmware is
the `GSLX680_FW_M86HD` array inside the vendor `gslX680new.ko`. `tools/extract_symbol.py` dumps it
straight out of the ELF, and the raw bytes are already in the `{u32 addr, u32 val}` format the
mainline driver loads. The firmware reports a 960x640 coordinate space. Inverting both axes and
swapping them maps that onto the panel's native portrait frame. The bootloader leaves `ldo_io1`
at 3.8 V, so the DT pins it at 3.3 V.

### 4. The four eMMC walls

Getting Linux to *run* from RAM took a day. Getting it to *install itself and boot from the eMMC*
took longer. Four separate problems, in the order they showed up:

1. **The musb gadget stalls under sustained bulk traffic.** Exporting the eMMC to the host as a
   USB disk (U-Boot `ums`, Linux `g_mass_storage`/`g_multi`) hung every time. So the install
   rides in RAM instead. `fel-boot.sh install` loads an installer initramfs that carries
   `rootfs.tar.gz` and U-Boot. Its `/init` runs 8 gates (eMMC identity and size, U-Boot's CRC of
   the first 16 MiB matches Linux's CRC of the same bytes, payload checksums, a write/read-back
   test, partition, rootfs, kernel read back and hash-checked, U-Boot written last and read back)
   and shows each verdict on the panel. A failed gate prints a red FAILED and writes nothing
   further. Short serial commands over `g_serial` are fine.
2. **U-Boot couldn't talk to the eMMC.** Two bugs stacked:
   - After the `HS_TIMING` switch, U-Boot's MMC core polls CMD13 *before* the host has re-timed
     its sampling, and this card stops answering. (The PF1007L community found the same thing
     independently. [wesbos/photo-frame-dashboard](https://github.com/wesbos/photo-frame-dashboard)
     has a no-HS U-Boot patch for FEL/UMS backups.) Patch `u-boot-0001` adds
     `MMC_SUNXI_EXTRA_4BIT_LEGACY`, which keeps that slot at 4-bit legacy timing (~25 MHz). It also
     stops the SPL from forcing 8-bit on this 4-bit-wired eMMC.
   - The vendor boot0 had left the MMC controller configured, and U-Boot only *de-asserts* the
     reset, so the stale state survived and CMD1 got no response. The same patch **pulses** the
     reset (assert, 10 µs, de-assert), as Linux does. This one was found by recording U-Boot's
     console in RAM (`CONFIG_CONSOLE_RECORD`), booting Linux with `mem=896M` so it never touches
     the top 128 MiB, and reading the log back with `tools/memdump` (a freestanding
     `mmap(/dev/mem)` dumper; the cross compiler has no libc).
3. **Linux eMMC: DDR reads hang, fast writes fail.** Mainline `sunxi-mmc` picks DDR52 and every
   read hangs right after the switch. Patch 0002 adds an `allwinner,no-ddr` DT property that masks
   the DDR caps. Writes then still failed at 25 MHz and up with the generic delay-chain phases
   (`boot-wtest.cmd` writes 1 MiB at 400 kHz, 12.5, 25 and 52 MHz and checks each one), so the DT caps
   the slot at `max-frequency = <12500000>`. The cap is plenty for a photo frame. Tuning the phases is
   an open item.
4. **The ROM was booting the eMMC's hardware boot partition.** EXT_CSD `PARTITION_CONFIG` is `0x48`
   (boot0 enabled, BOOT_ACK), and boot0 held the vendor `eGON.BT0` boot0. The ROM ran that,
   which looked for a vendor U-Boot that was gone, and fell back to FEL. Fix: zero the first
   64 KiB of `mmcblkXboot0` (after `echo 0 > /sys/block/mmcblkXboot0/force_ro`). Your backup has
   the original. The ROM then falls through to the user area at 8 KiB, where our SPL lives.
   `PARTITION_CONFIG` itself stays untouched.

The eMMC shows up as `mmcblk0` or `mmcblk1` depending on probe order, so every script finds it
by chip name (`/sys/block/mmcblk*/device/name == MAG2GC`) and exact size.

### 5. Wi-Fi: AIC8800DC

The chip isn't in mainline. [radxa-pkg/aic8800](https://github.com/radxa-pkg/aic8800) (commit in
`config/aic8800-radxa.commit`, with its `debian/patches` applied, including the 7.3 build fix) built
first try for the SDIO variant. The firmware comes from the same repo
(`src/SDIO/driver_fw/fw/aic8800DC`), so the Wi-Fi needs no Android blob. The DT gives it
`&mmc1` plus `mmc-pwrseq-simple` on PL6. The driver forces the SDIO clock to 50 MHz regardless
of the DT cap, and it's stable there at about 45 Mbit/s TCP.

**MAC pinning:** the chip has no MAC of its own, and the driver randomizes the tail on every boot,
so the router sees a new device (and gives out a new IP) each time. The OpenRC service
`rootfs-overlay/etc/init.d/aic8800` sets `WLAN_MAC` from `/etc/conf.d/aic8800` before
`wpa_supplicant` starts. A natural choice is the address stock Android used: it's on the vendor
kernel command line as `androidboot.mac=`, so note it before you wipe Android.

`CFG80211`/`RFKILL` are built in. OpenRC order: `aic8800` (modprobe, wait for `wlan0`, power save
off) → `wpa_supplicant` → `networking` (DHCP). `wifi-setup.sh` hashes the passphrase on the host
with `wpa_passphrase`, so the frame only ever stores the derived PSK.

### 6. Output without a GPU stack

`slideshow/kms.py` drives two libdrm dumb buffers through `ctypes`, so no Mesa or SDL is needed. SDL
was the first plan: Alpine's sdl2-compat runs on SDL3, and its KMSDRM backend segfaulted on this
armv7/musl setup. The 2 s crossfade is an int16 `a + ((b - a) * w >> 7)` blend striped across all
four cores (numpy releases the GIL), about 13 fps against about 5 single-threaded. Photo decoding
runs in a separate `nice 19` process, because a thread starved the fade through the GIL.

---

## Gotchas worth knowing before you start

- **`console=ttyGS0` hangs boot when no USB host is attached.** The *last* `console=` on the
  command line becomes `/dev/console`. With `console=tty0 console=ttyGS0`, init's console is
  the USB gadget serial port, and on a plain charger nothing reads it, so boot freezes right after the
  kernel messages. Every bring-up boot had a PC attached, which hid this until the first boot on
  the wall. The installed `extlinux.conf` (`rootfs-overlay/boot/`) has `console=tty0` only. The
  FEL boot scripts keep ttyGS0 because a host is always there. A getty on ttyGS0 (in
  `/etc/inittab`) still gives you a root shell over USB when you want one.
- **ModemManager types AT commands into the frame's root shell.** On the host, the gadget's ACM
  port looks like a modem. NetworkManager also grabs the gadget's USB ethernet and runs DHCP on
  it. `config/90-aeezo-frame-no-modemmanager.rules` (copy it to `/etc/udev/rules.d/` on the
  **host**) tells both to leave the gadget IDs alone.
- **Don't hang up the ACM tty with output pending.** Dropping DTR (`HUPCL`) with data queued
  wedged the musb IN endpoint (`request not queued to ep3in`). `frame-sh` clears `HUPCL`.
- **DDR on sunxi-mmc**: see wall 3. If your eMMC reads hang right after the speed switch, try
  `allwinner,no-ddr` first.
- One SPL run per power cycle over FEL. Running SPL again wedges USB.
- The built-in `silead_ts` probes at ~0.5 s, before the rootfs (and `/lib/firmware`) is mounted, and
  gives up. `rootfs-overlay/etc/local.d/silead-touch.start` re-binds it once filesystems are up
  (~6 s). `CONFIG_EXTRA_FIRMWARE` would remove the delay.
- Restoring sources with `mv` can leave them older than their objects, so `touch` them before rebuilding.
- The frame has one USB port for power and data and no working battery, so unplugging is a hard
  power cut. Run `poweroff` first.

### Getting back into FEL from the installed system

```sh
dd if=/dev/zero of=/dev/mmcblkX bs=1024 seek=8 count=1 conv=fsync; reboot -f
```

That blanks the SPL header, so the ROM drops to FEL. The RAM boot images carry
`tools/aeezo-uboot-restore` (expects U-Boot at `/usr/share/aeezo/u-boot-sunxi-with-spl.bin`) to put
it back, verified by read-back.

---

## Reproducing it

There's no one-shot build script yet. These are the steps. Host used: Fedora with the
`arm-linux-gnu-` cross binutils/gcc (no libc, which is fine for kernel and U-Boot; F44 needs
`openssl-devel-engine` for U-Boot), `sunxi-tools`, `uboot-tools` (`mkimage`), `android-tools`.

**Blobs from your own frame** (mount the partitions of your `mmcblk0.img` and look in the system
partition, e.g. `find <mnt> -name gslX680new.ko -o -name lcd.ko`):

```sh
python3 -I tools/extract_symbol.py gslX680new.ko GSLX680_FW_M86HD gsl1680-aeezo-u708hc.fw
# -> rootfs /lib/firmware/silead/gsl1680-aeezo-u708hc.fw
```

`lcd.ko` is only needed if your panel differs. The decoded table for this one is already in
`vendor/` and patch 0001. For a different unit, find the run of 72-byte records in `lcd.ko`'s
`.data` (it ends with cmd `0xFF1`) and run `tools/extract_init.py lcd.ko <hex offset> <size>`, then
`tools/compare_init.py <linux>/drivers/gpu/drm/panel/panel-jadard-jd9365da-h3.c <table.txt>`.

**U-Boot v2026.10**

```sh
cd u-boot && git checkout v2026.10
patch -p1 < ../patches/u-boot-0001-sunxi-mmc-extra-slot-4bit-legacy.patch
cp ../patches/u-boot-sun8i-a33-aeezo-u708hc.dts arch/arm/dts/sun8i-a33-aeezo-u708hc.dts
# add sun8i-a33-aeezo-u708hc.dtb to the sun8i list in arch/arm/dts/Makefile
cp ../config/u-boot-2026.10.config .config && make olddefconfig
make CROSS_COMPILE=arm-linux-gnu- -j"$(nproc)"     # -> u-boot-sunxi-with-spl.bin
```

The config has `MMC_SUNXI_SLOT_EXTRA=2`, `MMC_SUNXI_EXTRA_4BIT_LEGACY=y`, `CONSOLE_RECORD`, and a
bootcmd that falls back to FEL (`go 0xffff0020`) when distro boot finds nothing.

**Linux 7.3.1**

```sh
cd linux-7.3.1
patch -p1 < ../patches/0001-drm-panel-jd9365da-add-aeezo-u708hc.patch
patch -p1 < ../patches/0002-mmc-sunxi-allow-disabling-ddr-from-dt.patch
cp ../patches/sun8i-a33-aeezo-u708hc*.dts arch/arm/boot/dts/allwinner/
# add sun8i-a33-aeezo-u708hc.dtb to arch/arm/boot/dts/allwinner/Makefile
cp ../config/kernel-7.3.1-aeezo.config .config && make ARCH=arm olddefconfig
make ARCH=arm CROSS_COMPILE=arm-linux-gnu- -j"$(nproc)" zImage dtbs modules
```

(`config/aeezo_defconfig` is the same config as a savedefconfig. `kernel-7.3.1-aeezo-ums.config` is
the mass-storage-only flasher kernel from wall 1, kept for reference.)

**Wi-Fi driver**: clone radxa-pkg/aic8800 at the pinned commit, apply `debian/patches` (quilt order
in `series`), then in `src/SDIO/driver_fw/driver/aic8800` run
`make KDIR=<linux> ARCH=arm CROSS_COMPILE=arm-linux-gnu-`. Install the modules into the rootfs under
`/lib/modules/7.3.1-aeezo/extra` (`depmod -b <rootfs> 7.3.1-aeezo`) and the firmware under
`/lib/firmware/aic8800_fw/SDIO/aic8800DC/`.

**Root filesystem**: an Alpine 3.24 armhf minirootfs with `alpine-base openssh chrony iw
wpa_supplicant` (plus `python3 py3-numpy py3-pillow py3-evdev libdrm font-dejavu tzdata` for the
slideshow), `rootfs-overlay/` copied on top, the kernel + DTB in `/boot`, the touch firmware and
Wi-Fi bits above. Enable `aic8800` (boot), `wpa_supplicant`, `networking`, `sshd`, `chronyd`,
`local` and `aeezo-frame` (default) in OpenRC. For the USB root shell add
`ttyGS0::respawn:/sbin/getty -n -l /bin/sh 115200 ttyGS0 vt100` to `/etc/inittab` (and comment out
the tty1 getty if the slideshow owns the panel). Add your SSH public key to `/root/.ssh/authorized_keys`
(sshd is key-only). A minirootfs is armhf userland, so install packages with
`apk --root <rootfs> --arch armhf` from an x86 host, or under qemu-user in a chroot.

**Initramfs images** (busybox userland, `/init` from `initramfs/`):

```sh
# bring-up/diag image: initramfs/initramfs-init as /init, plus tools/memdump and aeezo-uboot-restore
# installer image:     initramfs/initramfs-install-init as /init, plus e2fsprogs/sfdisk and
#                      /payload/{rootfs.tar.gz,u-boot-sunxi-with-spl.bin,SHA256SUMS,zImage.sha256}
# optional:            /etc/aeezo/stock-64m.sha256, /etc/aeezo/stock-16m.crc32 from YOUR backup
(cd build/initramfs && find . | cpio -o -H newc | gzip -9) > initramfs.cpio.gz
mkimage -A arm -T ramdisk -C none -n aeezo-initramfs -d initramfs.cpio.gz initramfs.uimg
for c in boot boot-diag boot-install boot-wtest boot-ums; do
  mkimage -A arm -T script -C none -n aeezo-fel -d boot/$c.cmd $c.scr
done
```

`payload/zImage.sha256` is the sha256 of the `boot/zImage` inside `rootfs.tar.gz`. The installer
reads the kernel back off the eMMC and refuses to continue on a mismatch.

**Install**: frame in FEL (`adb reboot efex` the first time; later it lands there by itself whenever
the eMMC has nothing bootable), then `./fel-boot.sh install`. Watch the panel: 8 numbered gates, then a green
`INSTALL OK`, and it reboots into the eMMC. Then `./wifi-setup.sh` over USB, and for the slideshow
`FRAME=root@<frame-ip> IMMICH_URL=http://<server-ip>:2283 ./immich-setup.sh`.

The other FEL modes: `./fel-boot.sh` (RAM-only shell), `diag` (U-Boot runs its eMMC steps one at a
time and passes the exit codes to Linux in `/proc/cmdline`), `wtest` (the write-speed ladder),
`ums` (legacy USB mass-storage flasher, which hits wall 1).

## Risks and recovery

`fel-boot.sh install` **wipes the eMMC**, and zeroing boot0 destroys the vendor bootloader copy
there. Both come back from the backup in step 0 (write `mmcblk0.img` back from a RAM-booted Linux,
or over FEL). If you skip the backup, Android is gone for good: don't count on finding a stock image
anywhere else. The `ttyGS0` getty is a passwordless root shell for anyone with physical USB access.
That is handy for debugging and a liability in shared spaces, so remove it from `/etc/inittab` if
that matters to you.

## Repo layout

```
patches/         kernel patches 0001 (panel) + 0002 (mmc no-ddr), U-Boot patch, DTs (Linux, U-Boot, camera probe)
config/          kernel + U-Boot configs, aic8800 commit pin, host udev rule
boot/            U-Boot FEL boot scripts (.cmd -> mkimage -> .scr)
initramfs/       /init for the bring-up and installer RAM images
rootfs-overlay/  files laid over the Alpine rootfs (extlinux, OpenRC services, conf.d)
slideshow/       kms.py (libdrm dumb buffers via ctypes), frame.py (Immich slideshow), testcard.py
tools/           extract_symbol.py, extract_init.py, compare_init.py, memdump.c, camprobe.py, aeezo-uboot-restore
vendor/          the decoded panel init table (data only; no vendor binaries)
fel-boot.sh      RAM boot over FEL (normal | diag | wtest | install | ums)
flash-emmc.sh    legacy USB-disk install path (see wall 1)
frame-sh         run one command over the USB serial gadget
wifi-setup.sh    push a wpa_supplicant config (PSK only) over USB serial
immich-setup.sh  push an Immich API key over SSH and test it from the frame
```

## Open items

- Upstream: the panel entry (drop the burst knob; decide whether it's a new compatible or a
  CZ101B4001 variant), `allwinner,no-ddr` (or real delay-chain tuning for this card), the U-Boot
  reset pulse (useful well beyond this board), and a proper board DT.
- Tune the eMMC phases for 25/52 MHz writes.
- Build the touch firmware in (`CONFIG_EXTRA_FIRMWARE`) for touch at 0.5 s instead of 6 s.
- Bluetooth (AIC8800 BT over UART), the SC7A20 accelerometer, audio: not tried.
- A one-shot build script.

The frame in daily use runs a household chore board as its main screen, served from a home server.
That's a separate project and may become its own repo. This one is just the hardware bring-up and
a plain slideshow.

## Prior art

Checked 2026-11-07. Corrections welcome.

- **[wesbos/photo-frame-dashboard](https://github.com/wesbos/photo-frame-dashboard)** is the hub for
  this frame family: ADB/root, backups, a mainline U-Boot (v2025.10, Q8 A33 base) for FEL/UMS
  backups, eMMC no-HS workarounds, and a [community builds](https://github.com/wesbos/photo-frame-dashboard/blob/main/docs/community-builds.md)
  page. Its [Linux report](https://github.com/wesbos/photo-frame-dashboard/blob/main/docs/pf1007l-20260519-linux-report.md)
  shows the same `AEEZO/astar_m86_8723cs` fingerprint, so AEEZO = PF1007L.
- **Linux from microSD, eMMC untouched:**
  [pangoleen/ormarch-picture-frame](https://github.com/pangoleen/ormarch-picture-frame) (Arch/Omarchy;
  its DT also names `U708HC`; it has its own jd9365da panel entry and the same CZ101B4001 observation),
  [MikeO7/thinframe](https://github.com/MikeO7/thinframe) (Buildroot kiosk),
  [BumpyClock/pf1007l-archlinux-arm](https://github.com/BumpyClock/pf1007l-archlinux-arm),
  [chgeuer/nerves_pf1007l_pictureframe](https://github.com/chgeuer/nerves_pf1007l_pictureframe)
  (Nerves), [jkingston/fascia](https://github.com/jkingston/fascia). Each one says in its README that
  it boots from SD and doesn't write the eMMC.
- **Not found anywhere:** a standalone install to the eMMC, a fix for Linux-side eMMC writes, or the
  ROM-boots-boot0 trap. One X post from @sevenmaison (linked from the community page) mentions custom
  U-Boot and eMMC reads at 12 MHz on an A33 frame; I couldn't read it.
- **Upstream:** as of 7.4-rc1, `panel-jadard-jd9365da-h3` has no entry for this panel, and no
  mainline A33/R16 board DT enables `&dsi` (the A64 PinePhone/PineTab are the upstream sun6i-dsi
  users). The AIC8800 has an [RFC SDIO driver](https://lwn.net/Articles/1084468/) on the wireless
  list (July 2026), not merged. `"U708HC"` is a generic YHK/astar machine string; linux-sunxi's
  sunxi-boards has a 2015 A33 tablet fex with the same name and a different (RGB) panel.

So the honest headline: *mainline Linux installed to the internal eMMC (Android replaced) on the
PF1007L/AEEZO A33 frame*, with the eMMC fixes as the contribution. It isn't "first Linux on this
frame".

