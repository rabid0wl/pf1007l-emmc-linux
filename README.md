# Real Linux on a $60 photo frame, with Android wiped

I bought a cheap 10.1" Wi-Fi photo frame off Amazon. The community calls it the **PF1007L**; mine
says AEEZO on the box, and the same hardware ships under a lot of brand names. Inside it's a
small Android 6 tablet. This repo replaces that Android with ordinary, current Linux (the same
kernel and bootloader everyone else uses, not a vendor fork), installed on the frame's own
internal storage. No SD card, no Android, no vendor cloud app.

<!-- TODO: photo of the frame booting / showing the install screen (NOT the chore board) -->

## How this got built

I'm a civil engineer, not a programmer. I built this over four days in November 2026 with Claude
(Anthropic's AI) as the engineer at the keyboard: it read the vendor files, wrote the patches and
scripts, and worked out why things broke. My jobs were the hardware, the decisions, and checking
every result on the actual frame. The detailed writeup in [AGENTS.md](AGENTS.md) is Claude's, and
it's accurate to what we did and saw.

## What works

- The screen and backlight, at full resolution
- Touch
- Wi-Fi, SSH, time sync
- Booting on its own from the internal storage, about 7 seconds to a login
- A photo slideshow (pulls from a self-hosted [Immich](https://immich.app) server, tap for the next photo)

Not done: Bluetooth, audio, the motion sensor. There's no camera on this board, even though there's
a spot for one.

## What's new here

Plenty of people already run Linux on this frame, all from a microSD card, and every one of them
leaves the internal storage alone (links in [AGENTS.md](AGENTS.md#prior-art)). The hard part was
the internal storage, and it fought back four different ways:

1. The USB connection choked on big transfers, so the installer had to carry the whole system in
   memory and write it from there.
2. The bootloader lost contact with the storage chip because of a timing quirk and some leftover
   state from the factory bootloader.
3. Linux could read the chip at full speed but only *write* reliably at a quarter of it.
4. The chip has a hidden boot area that still held the factory bootloader, and the processor
   kept running that instead of ours.

Each of those has a fix in this repo, and they may help other cheap Allwinner devices too.

## Want to try it?

**This wipes Android off the frame.** Back up the whole thing first, or you can't go back. You need
a Linux computer, a USB *data* cable (the one in the box only charges), and some patience.

The easiest way in is what I did: point an AI coding agent at this repo and start with
[AGENTS.md](AGENTS.md). It has the full technical story, a hardware checklist to make sure your
frame really is the same board (they vary), the build steps, and rules for the agent (back up
first, ask before writing anything, stop at the first mismatch).

The [PF1007L community](https://github.com/wesbos/photo-frame-dashboard) is the place for rooting,
backups and everything Android-side.

## What's not in here

No vendor files. You pull the couple you need from your own frame's backup, and the scripts to do
that are included. My frame's everyday screen is a household chore board. That's a separate
project and may get its own repo someday.

## Credits

Standing on a lot of shoulders: the PF1007L community around
[wesbos/photo-frame-dashboard](https://github.com/wesbos/photo-frame-dashboard) and the SD-card
Linux ports, [linux-sunxi](https://linux-sunxi.org), mainline U-Boot and Linux,
[radxa-pkg/aic8800](https://github.com/radxa-pkg/aic8800) for the Wi-Fi driver,
[Alpine Linux](https://alpinelinux.org), and [Immich](https://immich.app).

## License

The kernel and bootloader patches are GPL-2.0 (they have to be, since they change GPL code); see
`LICENSE`. The device trees are `GPL-2.0+ OR MIT`. Everything else is MIT (`LICENSES/MIT.txt`).
