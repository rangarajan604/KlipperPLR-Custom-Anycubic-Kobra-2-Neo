#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Find and disable legacy PLR sections after the installer makes a backup."""

import re
import sys
from pathlib import Path
from typing import List, Tuple


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


def find_conflicts(config_dir: Path, active_config: Path) -> List[str]:
    conflicts = []
    if active_config.is_symlink():
        raise ValueError(f"Refusing to inspect symlinked config: {active_config}")
    if active_config.is_file():
        active_text = active_config.read_text(encoding="utf-8", errors="replace")
        if "Managed by KlipperPLR-Custom-Anycubic-Kobra-2-Neo." not in active_text:
            conflicts.append(f"{active_config}: existing unmanaged PLR config")

    for path in sorted(config_dir.rglob("*.cfg")):
        if path.is_symlink():
            raise ValueError(f"Refusing to inspect symlinked config: {path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if PLR_INCLUDE_RE.match(line):
                conflicts.append(f"{path}: existing PLR include")
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


def disable_conflicts(config_dir: Path) -> Tuple[int, int]:
    disabled_includes = 0
    disabled_macros = 0
    changes = []
    for path in sorted(config_dir.rglob("*.cfg")):
        if path.is_symlink():
            raise ValueError(f"Refusing to edit symlinked config: {path}")
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
    if len(sys.argv) not in (3, 4):
        print(
            "Usage: install_conflicts.py detect CONFIG_DIR ACTIVE_CONFIG "
            "| disable CONFIG_DIR",
            file=sys.stderr,
        )
        return 2
    try:
        if sys.argv[1] == "detect" and len(sys.argv) == 4:
            conflicts = find_conflicts(Path(sys.argv[2]), Path(sys.argv[3]))
            print("\n".join(conflicts))
            return 0
        if sys.argv[1] == "disable" and len(sys.argv) == 3:
            includes, macros = disable_conflicts(Path(sys.argv[2]))
            print(f"Disabled {includes} legacy include(s) and {macros} PLR macro(s).")
            return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Could not safely process existing PLR config: {exc}", file=sys.stderr)
        return 1
    print("Invalid command.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
