# Klipper PLR Custom - Anycubic Kobra 2 Neo

An independently written Klipper power-loss recovery helper for a Kobra 2 Neo
setup using Klipper, Moonraker, and Mainsail. It generates a recovery G-code
file from the interrupted print's original G-code and resumes at a later safe
travel move.

This project was written from the desired behavior and printer configuration.
It is not a copy of the KlipperPLR or YUMI_PLR recovery generator. The included
`gcode_shell_command.py` is a separate GPL-3.0-licensed helper; its copyright
and license notice are retained.

**License:** GPL-3.0-only. See [LICENSE](./LICENSE).

## AI-assisted development and disclaimer

This project was created with the assistance of AI tools and may contain
errors, unsafe assumptions, or incompatibilities. It is provided "AS IS",
without warranties of any kind, to the extent permitted by the applicable
license and law. The project authors and maintainers are not responsible for
damage, failed prints, data loss, or other consequences resulting from its
use. Review and test all code and configuration, back up printer settings,
and supervise the printer during operation. Nothing in this notice excludes
rights or liability that cannot legally be excluded.

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

This repository is public, so cloning and Moonraker updates do not require
GitHub credentials. If you make a fork private, configure secure Git access
for the Moonraker service account before using its update-manager entry. Never
put a GitHub token in this project or its install script.

The installer:

- installs files under `~/printer_data/plr_custom/`;
- creates its managed `plr_custom.cfg` or preserves this project's existing
  Mainsail-edited config;
- includes it from `printer.cfg`;
- preserves an existing `[save_variables]` section, or adds one if absent;
- ensures `[exclude_object]` and enabled `[force_move]` sections exist;
- backs up an existing shell-command helper before updating it; and
- adds a Moonraker update-manager entry for this custom GitHub repository.

If another PLR, an unmanaged `plr_custom.cfg`, or a conflicting macro is found,
the installer previews the affected file paths and exact include/macro headings
before asking whether to replace it. Answer `y` to back up the entire
config directory to a timestamped `config.backup-before-custom-plr-*` folder
(and any existing PLR runtime files to `plr_custom.backup-before-custom-plr-*`)
then disable detected legacy PLR includes/macros before installing. Answer `n`
or press Enter to cancel without changing the existing config. These backups
preserve the original files for manual restoration.

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
{% set dwell_s = 60 %}
{% set fan_off_layers = 2 %}
{% set enclosure_wait_s = 30 %}
```

What each setting does:

- `bed_preheat_factor = 1.05`: temporarily heats the bed to 105% of the
  interrupted print's normal bed target during recovery, then returns it to
  the normal target. The allowed range is 1.00-1.10.
- `nozzle_preheat_factor = 1.05`: temporarily heats the nozzle to 105% of its
  normal print target, then returns it to the normal target. The allowed
  range is 1.00-1.10.
- `z_lift = 2`: raises the nozzle 2 mm before XY homing to help avoid hitting
  the print. The allowed range is 0-20 mm.
- `dwell_s = 60`: waits 60 seconds after the bed and nozzle have reached
  their temporary preheat temperatures, before their targets are returned to
  normal. This can give the hotend extra time to stabilize; it is separate
  from the enclosure wait. Use `0` for no extra wait. The allowed range is
  0-60 seconds.
- `fan_off_layers = 2`: keeps the part-cooling fan off for the first 2 resumed
  layers, then restores the fan speed from the print file. Use `0` to disable
  this pause; allowed values are 0, 1, or 2.
- `enclosure_wait_s = 30`: waits 30 seconds after XY homing before continuing,
  allowing the enclosure to warm. Use `0` for no wait; the allowed range is
  0-60 seconds.

For an existing installation, the installer preserves your active config.
Update its `RESUME_INTERRUPTED` macro to use `dwell_s` and `enclosure_wait_s`
instead of the old millisecond names, set `enclosure_wait_s` to `30` for the
same 30-second delay, and pass `{fan_off_layers} {enclosure_wait_s}` after
`{dwell_s}` in its `RUN_SHELL_COMMAND` parameters. This keeps the settings
editable in Mainsail. The updated shell script defaults to 2 fan-off layers
and a 30-second enclosure wait if those parameters are not passed.

The script reads **normal** bed and nozzle targets from the interrupted
G-code's metadata (preferred) or heater commands before the resume position.
It does not use first-layer temperature metadata. It multiplies normal targets
by the configured factors, waits for both preheat targets, then restores the
normal targets before lifting and homing XY. After homing XY, it waits the
configured enclosure time. The part-cooling fan (`[fan]`, controlled by
`M106`) is kept off for the configured number of resumed layers, then the
G-code's fan setting is restored. The hotend heatsink fan
(`[heater_fan extruder_fan]`) is not disabled.

`fan_off_layers` may be 0, 1, or 2; 0 disables the fan pause. The layer count
uses upward absolute Z moves in the source G-code, so inspect the generated
recovery file if the slicer uses Z-hop. Enclosure wait and dwell are limited
to 0-60 seconds; lift is limited to 0-20 mm; preheat factors are limited to
1.00-1.10. Klipper still enforces the printer's configured heater maximums.
If a preheat exceeds a heater's maximum, recovery will fail; lower that
heater's factor in Mainsail.

## Uninstall

Run `bash ./uninstall.sh` from this project directory on the printer. It removes
only this project's config include, update-manager entry, and dedicated
`plr_custom` scripts/config and generated `.gcode` files. Empty PLR directories
are removed; directories containing other files are kept. Saved `variables.cfg`
data and unrelated files are always retained. The shared
`gcode_shell_command.py` extra is retained unless the installer saved a
`.pre-custom-plr` copy and the installed helper still matches this project; in
that case, the previous helper is restored. If the installed helper was
modified, both it and the backup are left in place. The uninstaller refuses to
remove an active `plr_custom.cfg` unless it has this project's managed-file
marker. After successful cleanup, if run from the standard clone at
`~/KlipperPLR-Custom-Anycubic-Kobra-2-Neo`, the uninstaller moves that folder
to a timestamped `.uninstalled-*` backup name. This removes it from the usual
clone path while preserving repository history, local edits, and other files.

## License and attribution

The independently written recovery code is licensed under GPL-3.0-only; the
full license text is in [LICENSE](./LICENSE). The included
`gcode_shell_command.py` retains its original copyright and GPLv3 notice.

The project is not affiliated with Anycubic, BIGTREETECH, Klipper, Moonraker,
or Mainsail.
