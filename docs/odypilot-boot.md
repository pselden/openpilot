# OdyPilot boot theme

OdyPilot uses brikowski's Odyssey Sport artwork for three startup stages:

1. The firmware displays a matching static image immediately after power-on.
2. AGNOS animates the Odyssey while its compositor has no display client.
3. The application startup spinner animates the same scene with progress messages.

The application animation and OdyPilot interface branding arrive through a normal
`pselden/ody-test` update. The first two stages need a one-time installation on the
device; updating the Git branch alone does not change AGNOS or its splash partition.

The optional helper is included as source only. No launch hook automatically runs
it, and a normal branch update does not install an OS service or write a partition.

## Early-OS renderer

`openpilot/tools/odyssey_boot.py` is ported from brikowski's
`ody-op-test` boot-theme work through commit `434780d9e59b`. Copy it, the current
`openpilot/system/ui/lib/odyssey_scene.py`, and
`openpilot/selfdrive/assets/images/odyssey_sport.png` to a stable directory named
`/data/odyssey-boot`, using those three basenames.

The wrapper validates the original `/usr/comma/magic.py` against the recognized
AGNOS compositor hash before adding animation hooks in memory. It yields whenever
a display client takes over and falls back to the stock background when the
compositor version or rendering is unsupported. It does not modify `magic.py`.
A `magic.service` drop-in must run the wrapper with the original service's Python
interpreter. Save the original service configuration and any prior override before
installing a drop-in. An AGNOS update may require adapting or reinstalling this theme.

## Firmware still image

Before writing anything, confirm the device is offroad, identify its actual splash
partition, and save a complete original copy under `/data/odyssey-boot/backup` and
off the device. Inspect its dimensions and orientation to prepare a matching,
uncompressed, bottom-up 24-bit BMP frame.

The packer replaces only the pixel payload and rejects incompatible formats,
dimensions, extra images, or unexpected padding:

```sh
python3 openpilot/tools/odyssey_boot.py --pack-splash original-splash.bin odyssey-frame.bmp odyssey-splash.bin
```

Compare the candidate with the backup: its length, DDPH header, bitmap metadata,
and trailing padding must remain unchanged. Write only the identified splash
partition, then read it back and compare its SHA-256 with the validated candidate.
Do not write a boot, bootloader, or OS partition to install this cosmetic theme.

## Restore

Restore the saved splash bytes to the same verified partition, remove only the
OdyPilot `magic.service` drop-in (or restore the prior override), and reload systemd.
The original AGNOS compositor remains available. Reboot while parked to verify all
stages. Keep the backups after installation.
