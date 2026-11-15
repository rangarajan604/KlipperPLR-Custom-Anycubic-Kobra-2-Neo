#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Remove this project's installed Klipper PLR files."""

import errno
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List


MANAGED_MARKER = "Managed by KlipperPLR-Custom-Anycubic-Kobra-2-Neo."
PROJECT_DIRECTORY = "KlipperPLR-Custom-Anycubic-Kobra-2-Neo"


class UninstallError(Exception):
    """Raised when uninstalling would remove an unowned configuration."""


def remove_include(path: Path, include_line: str) -> int:
    if path.is_symlink():
        raise UninstallError(f"Refusing to edit symlinked config: {path}")
    if not path.is_file():
        return 0
    original = path.read_bytes()
    text = original.decode("utf-8")
    lines = text.splitlines()
    remaining = [line for line in lines if line.strip() != include_line]
    removed = len(lines) - len(remaining)
    if not removed:
        return 0
    newline = "\r\n" if b"\r\n" in original else "\n"
    updated = newline.join(remaining)
    if original.endswith(b"\n"):
        updated += newline
    path.write_bytes(updated.encode("utf-8"))
    return removed


def remove_file(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_dir() and not path.is_symlink():
        raise UninstallError(f"Expected a file but found a directory: {path}")
    path.unlink()
    return True


def remove_generated_gcodes(directory: Path) -> int:
    if not directory.exists() and not directory.is_symlink():
        return 0
    if directory.is_symlink() or not directory.is_dir():
        raise UninstallError(
            f"Refusing to inspect a non-directory or symlink: {directory}"
        )
    removed = 0
    for path in directory.iterdir():
        if path.is_file() and path.suffix.lower() == ".gcode":
            path.unlink()
            removed += 1
    return removed


def remove_if_empty(directory: Path) -> bool:
    if directory.is_symlink():
        return False
    try:
        directory.rmdir()
    except FileNotFoundError:
        return False
    except OSError as exc:
        if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
            return False
        raise
    return True


def restore_shared_extra(extra: Path, project_extra: Path) -> str:
    backup = extra.with_name(extra.name + ".pre-custom-plr")
    if not backup.is_file():
        return "Shared gcode_shell_command.py left in place."
    if extra.is_symlink():
        return (
            "Shared helper is a symlink; it was left unchanged and the prior "
            f"copy remains at {backup}."
        )
    if extra.exists() and not extra.is_file():
        return (
            "Shared helper path is not a regular file; it was left unchanged "
            f"and the prior copy remains at {backup}."
        )
    if extra.is_file() and extra.read_bytes() != project_extra.read_bytes():
        return (
            "Shared helper differs from the project copy; it was left "
            f"unchanged and the prior copy remains at {backup}."
        )
    os.replace(str(backup), str(extra))
    return "Restored the shared gcode_shell_command.py backup."


def uninstall(home: Path, project_extra: Path) -> List[str]:
    if not home.is_dir():
        raise UninstallError(f"Printer user's home directory does not exist: {home}")
    if not project_extra.is_file():
        raise UninstallError(f"Project helper file does not exist: {project_extra}")

    printer_data = home / "printer_data"
    config_dir = printer_data / "config"
    active_config = config_dir / "plr_custom.cfg"
    if active_config.is_symlink():
        raise UninstallError(
            f"Refusing to remove symlinked configuration: {active_config}"
        )
    if active_config.is_file():
        if MANAGED_MARKER not in active_config.read_text(encoding="utf-8"):
            raise UninstallError(
                f"Refusing to remove unmarked configuration: {active_config}"
            )

    managed_files = (
        config_dir / "plr_custom.cfg",
        config_dir / "update_plr_custom.cfg",
        printer_data / "plr_custom/plr.py",
        printer_data / "plr_custom/plr.sh",
        printer_data / "plr_custom/clear_plr.sh",
    )
    for path in managed_files:
        if path.is_symlink():
            raise UninstallError(f"Refusing to remove symlink: {path}")
        if path.is_dir() and not path.is_symlink():
            raise UninstallError(f"Expected a file but found a directory: {path}")
    output_dir = printer_data / "gcodes/plr_custom"
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise UninstallError(
            f"Refusing to inspect a non-directory or symlink: {output_dir}"
        )

    removed_includes = 0
    removed_includes += remove_include(
        config_dir / "printer.cfg", "[include plr_custom.cfg]"
    )
    removed_includes += remove_include(
        config_dir / "moonraker.conf", "[include update_plr_custom.cfg]"
    )

    removed_files = 0
    for path in managed_files:
        removed_files += int(remove_file(path))

    removed_gcodes = remove_generated_gcodes(output_dir)

    empty_dirs = 0
    for directory in (
        printer_data / "plr_custom",
        output_dir,
    ):
        empty_dirs += int(remove_if_empty(directory))

    helper_message = restore_shared_extra(
        home / "klipper/klippy/extras/gcode_shell_command.py",
        project_extra,
    )
    messages = [
        f"Removed {removed_includes} custom config include(s).",
        f"Removed {removed_files} PLR file(s) and {removed_gcodes} recovery G-code file(s).",
        f"Removed {empty_dirs} empty PLR directory/directories.",
        helper_message,
        "Saved variables and unrelated files were left in place.",
    ]
    return messages


def move_clone_to_backup(home: Path, project_dir: Path) -> str:
    if project_dir.is_symlink() or not project_dir.is_dir():
        return "Project clone was not moved because it is not a regular directory."

    expected_dir = home.resolve() / PROJECT_DIRECTORY
    if project_dir.resolve() != expected_dir.resolve():
        return (
            "Project clone was left in place because it is not the standard "
            f"directory: {expected_dir}"
        )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = home / f"{PROJECT_DIRECTORY}.uninstalled-{timestamp}"
    suffix = 1
    while backup_dir.exists() or backup_dir.is_symlink():
        backup_dir = home / (
            f"{PROJECT_DIRECTORY}.uninstalled-{timestamp}-{suffix}"
        )
        suffix += 1

    project_dir.rename(backup_dir)
    return f"Moved the project clone to {backup_dir} (files preserved)."


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: uninstall.py PRINTER_HOME PROJECT_HELPER", file=sys.stderr)
        return 2
    try:
        home = Path(sys.argv[1])
        project_extra = Path(sys.argv[2])
        messages = uninstall(home, project_extra)
        messages.append(move_clone_to_backup(home, project_extra.parent))
    except (OSError, UnicodeError, UninstallError) as exc:
        print(f"Uninstall failed: {exc}", file=sys.stderr)
        return 1
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
