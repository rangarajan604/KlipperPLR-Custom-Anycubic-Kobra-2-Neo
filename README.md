# Klipper PLR Custom - Anycubic Kobra 2 Neo

An independently written Klipper power-loss recovery helper for a Kobra 2 Neo
setup using Klipper, Moonraker, and Mainsail. It generates a recovery G-code
file from the interrupted print's original G-code and resumes at a later safe
travel move.

This project was written from the desired behavior and printer configuration.
It is not a copy of the KlipperPLR or YUMI_PLR recovery generator. The included
`gcode_shell_command.py` is a separate GPL-3.0-licensed helper; its copyright
and license notice are retained.

## Important limitations

Power-loss recovery is inherently approximate. It cannot detect whether the
machine physically shifted during the outage, whether the part detached, or
whether the saved Z corresponds to a completed layer. Do not use recovery
without supervising the printer. Confirm the nozzle and bed preheat targets
are within your printer's configured limits and the filament's safe range.
The default 5% nozzle preheat can cause oozing and may exceed a configured
heater limit for some materials.

The generator supports G-code with absolute layer-Z moves and identifies a
non-extruding XY move at the next higher layer. It stops with an error if it
cannot find the source file, matching saved layer, later layer, or required
normal bed/nozzle temperatures.

## Requirements

- Klipper, Moonraker, and Mainsail installed on the printer.
- Python 3 on the printer.
- The `gcode_shell_command.py` Klipper extra installed by this installer.
- A saved-variable setup and slicer hooks as described below.

## Install

Run the local test suite before deploying changes:

```bash
python3 -m unittest discover -s tests -v
```

On a fresh printer install, clone the repository once:

```bash
cd ~
git clone https://github.com/rangarajan604/KlipperPLR-Custom-Anycubic-Kobra-2-Neo.git
cd ~/KlipperPLR-Custom-Anycubic-Kobra-2-Neo
bash ./install.sh
cd ~
```

`cd ~` returns to the home directory; `cd .` leaves you in the current
directory. If the repository directory already exists, do not clone it again.
To update an existing checkout, run:

```bash
cd ~/KlipperPLR-Custom-Anycubic-Kobra-2-Neo
git pull --ff-only
bash ./install.sh
cd ~
```

If the GitHub repository is private, configure Git access for the printer's
Moonraker service account before relying on its update-manager entry. Never put
a GitHub token in this project or its install script.

The installer:

- installs files under `~/printer_data/plr_custom/`;
- creates `plr_custom.cfg` only if it does not already exist;
- includes it from `printer.cfg`;
- preserves an existing `[save_variables]` section, or adds one if absent;
- ensures `[exclude_object]` and enabled `[force_move]` sections exist;
- backs up an existing shell-command helper before updating it; and
- adds a Moonraker update-manager entry for this custom GitHub repository.

If another PLR is already installed, disable its include and remove/disable its
duplicate `RESUME_INTERRUPTED` macro before installing this one. The installer
stops if it detects an existing PLR include or resume macro, to avoid duplicate
Klipper commands. Back up your printer configuration before installation.

After installation, run `RESTART` from the Mainsail console and wait for Klipper
to become ready.

### Moonraker and printer connection checks

Before restarting, check `printer_data/config/moonraker.conf` for a stale
`[include update_plr.cfg]` line left by an older PLR. If
`printer_data/config/update_plr.cfg` does not exist, back up `moonraker.conf`
and comment out only that stale include. Keep the custom
`[include update_plr_custom.cfg]` entry.

If Mainsail cannot connect to Moonraker, check the service and local API:

```bash
systemctl is-active moonraker
curl --max-time 5 -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:7125/server/info
```

Klipper also needs to detect the printer's USB serial device. If Klipper cannot
connect to the MCU, check the printer power and USB data cable, then run:

```bash
lsusb
ls -l /dev/serial/by-id/
```

Do not change the `[mcu]` serial path to a guessed value or run recovery until
the printer appears and Klipper reports ready.

## Slicer G-code hooks

Add these lines to the slicer's start G-code after the print file has been
selected:

```gcode
G31
save_last_file
SAVE_VARIABLE VARIABLE=was_interrupted VALUE=True
```

Add these lines to the slicer's end G-code:

```gcode
SAVE_VARIABLE VARIABLE=was_interrupted VALUE=False
clear_last_file
G31
```

Add this to the slicer's before-layer-change G-code so the last completed Z
position is periodically saved:

```gcode
LOG_Z
```

Use the same start/end hooks as the existing PLR convention. Check your slicer's
G-code preview and macros before printing; slicer start/end G-code varies.

## Recovery

After a power loss, do not move the printer or remove the part. In Mainsail,
run:

```gcode
RESUME_INTERRUPTED
```

The macro generates and starts `gcodes/plr_custom/<original-name>.gcode`.
Inspect the console output and generated file. Stop if generation reports an
error or the recovery path looks unsafe.

## Mainsail settings

Edit the constants near the top of `[gcode_macro RESUME_INTERRUPTED]` in
`printer_data/config/plr_custom.cfg`:

```ini
{% set bed_preheat_factor = 1.05 %}
{% set nozzle_preheat_factor = 1.05 %}
{% set z_lift = 2 %}
{% set dwell_ms = 0 %}
```

The script reads **normal** bed and nozzle targets from the interrupted
G-code's metadata (preferred) or heater commands before the resume position.
It does not use first-layer temperature metadata. It multiplies normal targets
by the configured factors, waits for both preheat targets, then restores the
normal targets before lifting and homing XY.

Factors are limited to 1.00-1.10; lift is limited to 0-20 mm; dwell is limited
to 0-60000 ms. Klipper still enforces the printer's configured heater
maximums. If a preheat exceeds a heater's maximum, the recovery will fail;
lower that heater's factor in Mainsail.

## Uninstall

Run `bash ./uninstall.sh` from this project directory on the printer. It removes
only this project's config include, update-manager entry, and dedicated
`plr_custom` files. It does not remove shared Klipper extras or saved
variable data.

## License and attribution

The independently written recovery code is licensed under GPL-3.0-only.
The included `gcode_shell_command.py` retains its original copyright and
GPLv3 notice. See `LICENSE`.

The project is not affiliated with Anycubic, BIGTREETECH, Klipper, Moonraker,
or Mainsail.
