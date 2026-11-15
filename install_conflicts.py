#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Find and disable legacy PLR sections after the installer makes a backup."""

import glob
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


PLR_MACROS = {
    "RESUME_INTERRUPTED",
    "G31",
    "SAVE_LAST_FILE",
    "CLEAR_LAST_FILE",
    "LOG_Z",
    "EXCLUDE_OBJECT",
    "EXCLUDE_OBJECT_DEFINE",
}
SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]")
PLR_INCLUDE_RE = re.compile(r"^\s*\[include\s+plr\.cfg\]\s*$", re.IGNORECASE)
INCLUDE_RE = re.compile(r"^\s*\[include\s+([^\]]+)\]\s*$", re.IGNORECASE)


def is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def active_config_files(
    config_dir: Path, printer_config: Path, home: Path
) -> List[Path]:
    pending = [printer_config]
    visited = set()
    files = []
    while pending:
        path = pending.pop()
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in visited:
            continue
        visited.add(resolved)
        files.append(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            include = INCLUDE_RE.match(line)
            if not include:
                continue
            included_path = include.group(1).strip()
            if included_path == "~" or included_path.startswith("~/"):
                included_path = str(home) + included_path[1:]
            candidate = Path(included_path)
            if not candidate.is_absolute():
                candidate = config_dir / candidate
            pending.extend(Path(match) for match in glob.glob(str(candidate)))
    return files


def find_text_conflicts(path: Path, text: str) -> List[str]:
    conflicts = []
    for line in text.splitlines():
        if PLR_INCLUDE_RE.match(line):
            conflicts.append(f"{path}: disable [include plr.cfg]")
        section = SECTION_RE.match(line)
        if section:
            section_name = section.group(1).strip().split()
            if (
                len(section_name) == 2
                and section_name[0].lower() == "gcode_macro"
                and section_name[1].upper() in PLR_MACROS
            ):
                conflicts.append(
                    f"{path}: existing [gcode_macro {section_name[1]}]"
                )
    return conflicts


def find_conflicts(
    config_dir: Path,
    active_config: Path,
    printer_config: Optional[Path] = None,
    home: Optional[Path] = None,
) -> List[str]:
    conflicts = []
    printer_config = printer_config or config_dir / "printer.cfg"
    home = home or config_dir.parent.parent
    if active_config.is_symlink():
        raise ValueError(f"Refusing to inspect symlinked config: {active_config}")
    if active_config.is_file():
        active_text = active_config.read_text(encoding="utf-8", errors="replace")
        if "Managed by KlipperPLR-Custom-Anycubic-Kobra-2-Neo." not in active_text:
            conflicts.append(f"{active_config}: existing unmanaged PLR config")

    config_root = config_dir.resolve()
    for path in active_config_files(config_dir, printer_config, home):
        text = path.read_text(encoding="utf-8", errors="replace")
        file_conflicts = find_text_conflicts(path, text)
        if file_conflicts and (
            path.is_symlink() or not is_within(path.resolve(), config_root)
        ):
            raise ValueError(
                f"PLR conflict is in a linked or external config; resolve it "
                f"manually before installing: {path}"
            )
        conflicts.extend(file_conflicts)
    return conflicts


def disable_conflicts(
    config_dir: Path,
    printer_config: Optional[Path] = None,
    home: Optional[Path] = None,
) -> Tuple[int, int]:
    printer_config = printer_config or config_dir / "printer.cfg"
    home = home or config_dir.parent.parent
    config_root = config_dir.resolve()
    disabled_includes = 0
    disabled_macros = 0
    changes = []
    for path in active_config_files(config_dir, printer_config, home):
        if path.is_symlink() or not is_within(path.resolve(), config_root):
            if find_text_conflicts(
                path, path.read_text(encoding="utf-8", errors="replace")
            ):
                raise ValueError(
                    f"Refusing to edit linked or external PLR config: {path}"
                )
            continue
        original = path.read_bytes()
        text = original.decode("utf-8")
        lines = text.splitlines()
        output = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if PLR_INCLUDE_RE.match(line):
                output.append("# Disabled by custom PLR installer after backup: " + line)
                disabled_includes += 1
                index += 1
                continue

            section = SECTION_RE.match(line)
            section_name = section.group(1).strip().split() if section else []
            if (
                len(section_name) == 2
                and section_name[0].lower() == "gcode_macro"
                and section_name[1].upper() in PLR_MACROS
            ):
                output.append("# Disabled by custom PLR installer after backup: " + line)
                disabled_macros += 1
                index += 1
                while index < len(lines) and not SECTION_RE.match(lines[index]):
                    output.append("# " + lines[index] if lines[index] else "#")
                    index += 1
                continue

            output.append(line)
            index += 1

        updated = "\n".join(output)
        if original.endswith(b"\n"):
            updated += "\n"
        newline = "\r\n" if b"\r\n" in original else "\n"
        if newline != "\n":
            updated = updated.replace("\n", newline)
        encoded = updated.encode("utf-8")
        if encoded != original:
            changes.append((path, encoded))
    for path, content in changes:
        path.write_bytes(content)
    return disabled_includes, disabled_macros


def main() -> int:
    if len(sys.argv) not in (5, 6):
        print(
            "Usage: install_conflicts.py detect CONFIG_DIR ACTIVE_CONFIG "
            "PRINTER_CONFIG HOME | disable CONFIG_DIR PRINTER_CONFIG HOME",
            file=sys.stderr,
        )
        return 2
    try:
        if sys.argv[1] == "detect" and len(sys.argv) == 6:
            conflicts = find_conflicts(
                Path(sys.argv[2]),
                Path(sys.argv[3]),
                Path(sys.argv[4]),
                Path(sys.argv[5]),
            )
            print("\n".join(conflicts))
            return 0
        if sys.argv[1] == "disable" and len(sys.argv) == 5:
            includes, macros = disable_conflicts(
                Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
            )
            print(f"Disabled {includes} legacy include(s) and {macros} PLR macro(s).")
            return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Could not safely process existing PLR config: {exc}", file=sys.stderr)
        return 1
    print("Invalid command.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
