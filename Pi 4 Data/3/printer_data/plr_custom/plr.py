#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Generate a Klipper power-loss recovery G-code file."""

import argparse
import ast
import configparser
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
MOTION_RE = re.compile(r"^G(?:0|00|1|01)(?:\s|$)", re.IGNORECASE)
PARAMETER_RE = re.compile(
    rf"(?:^|\s)([A-Z])\s*({NUMBER})(?=\s|$)", re.IGNORECASE
)
TEMPERATURE_RE = re.compile(
    rf"^\s*(M104|M109|M140|M190)\s+.*?\bS\s*({NUMBER})(?:\s|$)",
    re.IGNORECASE,
)


class RecoveryError(Exception):
    """Raised when a safe recovery file cannot be produced."""


def parse_saved_value(raw: str) -> str:
    value = raw.strip()
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        parsed = value
    if not isinstance(parsed, str):
        return str(parsed)
    while len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in "\"'":
        parsed = parsed[1:-1]
    return parsed


def load_variables(path: Path) -> Dict[str, str]:
    if not path.is_file():
        raise RecoveryError(f"Saved variables file does not exist: {path}")
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str.lower
    try:
        with path.open(encoding="utf-8") as stream:
            parser.read_file(stream)
    except (OSError, configparser.Error) as exc:
        raise RecoveryError(f"Cannot read saved variables file: {exc}") from exc
    if not parser.has_section("Variables"):
        raise RecoveryError("Saved variables file has no [Variables] section")
    return {
        key.lower(): parse_saved_value(value)
        for key, value in parser.items("Variables")
    }


def parse_motion(line: str) -> Tuple[Optional[str], Dict[str, float]]:
    command = line.split(";", 1)[0].strip().upper()
    if not MOTION_RE.match(command):
        return None, {}
    parameters = {
        key.upper(): float(value) for key, value in PARAMETER_RE.findall(command)
    }
    return command, parameters


def metadata_temperature(
    lines: List[str], names: Tuple[str, ...]
) -> Optional[float]:
    keys = "|".join(re.escape(name) for name in names)
    pattern = re.compile(
        rf"^\s*;\s*(?:{keys})\s*=\s*({NUMBER})(?:\s*,.*)?\s*$",
        re.IGNORECASE,
    )
    for line in lines:
        match = pattern.match(line)
        if match:
            return float(match.group(1))
    return None


def find_normal_temperatures(
    lines: List[str], resume_index: int
) -> Tuple[float, float]:
    bed_temp = None
    nozzle_temp = None
    for line in lines[:resume_index]:
        match = TEMPERATURE_RE.match(line.split(";", 1)[0])
        if not match:
            continue
        command, raw_value = match.groups()
        if command.upper() in ("M140", "M190"):
            bed_temp = float(raw_value)
        else:
            nozzle_temp = float(raw_value)

    # Slicer metadata contains explicit normal-layer values; prefer it over
    # startup heater commands, which may contain first-layer temperatures.
    bed_temp = metadata_temperature(
        lines, ("hot_plate_temp", "bed_temperature")
    ) or bed_temp
    nozzle_temp = metadata_temperature(lines, ("nozzle_temperature",)) or nozzle_temp
    if (
        bed_temp is None
        or nozzle_temp is None
        or not math.isfinite(bed_temp)
        or not math.isfinite(nozzle_temp)
        or bed_temp <= 0
        or nozzle_temp <= 0
    ):
        raise RecoveryError(
            "Normal bed/nozzle temperatures were not found in the print G-code"
        )
    return bed_temp, nozzle_temp


def validate_options(
    bed_factor: float, nozzle_factor: float, z_lift: float, dwell_ms: int
) -> None:
    if not math.isfinite(bed_factor) or not 1.0 <= bed_factor <= 1.10:
        raise RecoveryError("Bed preheat factor must be between 1.00 and 1.10")
    if not math.isfinite(nozzle_factor) or not 1.0 <= nozzle_factor <= 1.10:
        raise RecoveryError("Nozzle preheat factor must be between 1.00 and 1.10")
    if not math.isfinite(z_lift) or not 0 <= z_lift <= 20:
        raise RecoveryError("Z lift must be between 0 and 20 mm")
    if not 0 <= dwell_ms <= 60000:
        raise RecoveryError("Dwell must be between 0 and 60000 ms")


def build_recovery(
    source_path: Path,
    saved_z: float,
    output_path: Path,
    excluded_names: str,
    bed_factor: float,
    nozzle_factor: float,
    z_lift: float,
    dwell_ms: int,
) -> Tuple[float, float, float]:
    validate_options(bed_factor, nozzle_factor, z_lift, dwell_ms)
    if not math.isfinite(saved_z) or saved_z <= 0:
        raise RecoveryError("Saved Z must be a positive finite number")
    if not source_path.is_file():
        raise RecoveryError(f"Original print G-code does not exist: {source_path}")

    try:
        lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise RecoveryError(f"Cannot read original print G-code: {exc}") from exc

    motions = []
    for index, line in enumerate(lines):
        command, parameters = parse_motion(line)
        if command is not None:
            motions.append((index, command, parameters))

    saved_matches = [
        item
        for item in motions
        if "Z" in item[2] and abs(item[2]["Z"] - saved_z) <= 0.005
    ]
    if not saved_matches:
        raise RecoveryError(
            f"No G-code move matches saved Z={saved_z:g}; refusing unsafe restart"
        )
    last_saved_index = saved_matches[-1][0]
    next_layer = next(
        (
            item
            for item in motions
            if item[0] > last_saved_index
            and item[2].get("Z", saved_z) > saved_z + 0.005
        ),
        None,
    )
    if next_layer is None:
        raise RecoveryError(f"No later layer exists after saved Z={saved_z:g}")
    resume_layer_z = next_layer[2]["Z"]
    resume_move = next(
        (
            item
            for item in motions
            if item[0] >= next_layer[0]
            and "X" in item[2]
            and "Y" in item[2]
            and "E" not in item[2]
        ),
        None,
    )
    if resume_move is None:
        raise RecoveryError("No non-extruding XY travel exists at the resume layer")
    resume_index, _, resume_parameters = resume_move
    bed_temp, nozzle_temp = find_normal_temperatures(lines, resume_index)

    object_definitions = [
        line.split(";", 1)[0].strip()
        for line in lines
        if re.match(r"^\s*EXCLUDE_OBJECT_DEFINE\s+NAME=", line, re.IGNORECASE)
    ]
    active_object = None
    start_pattern = re.compile(
        r"^\s*EXCLUDE_OBJECT_START\b.*?\bNAME=([^\s;]+)", re.IGNORECASE
    )
    end_pattern = re.compile(r"^\s*EXCLUDE_OBJECT_END\b", re.IGNORECASE)
    for line in lines[:resume_index]:
        code = line.split(";", 1)[0]
        start_match = start_pattern.match(code)
        if start_match:
            active_object = start_match.group(1)
        elif end_pattern.match(code):
            active_object = None

    extrusion_mode = "M83"
    last_e = 0.0
    fan_command = None
    for line in lines[:resume_index]:
        code = line.split(";", 1)[0].strip().upper()
        if re.match(r"^M(?:82|83)(?:\s|$)", code):
            extrusion_mode = code.split()[0]
        if code.startswith("M106"):
            fan_command = code
        _, parameters = parse_motion(line)
        if "E" in parameters:
            last_e = parameters["E"]

    generated = [
        "SET_GCODE_OFFSET Z=0 MOVE=0",
        f"SET_KINEMATIC_POSITION Z={saved_z:g} SET_HOMED=XYZ",
        f"M140 S{bed_temp * bed_factor:g}",
        f"M190 S{bed_temp * bed_factor:g}",
        f"M104 S{nozzle_temp * nozzle_factor:g}",
        f"M109 S{nozzle_temp * nozzle_factor:g}",
        f"G4 P{dwell_ms}",
        f"M140 S{bed_temp:g}",
        f"M104 S{nozzle_temp:g}",
        "G91",
        f"G1 Z{z_lift:g} F600",
        "G90",
        "G28 X Y",
        "EXCLUDE_OBJECT_DEFINE RESET=1",
    ]
    generated.extend(object_definitions)
    generated.extend(
        f"EXCLUDE_OBJECT NAME={name}"
        for name in excluded_names.split()
    )
    if active_object:
        generated.append(f"EXCLUDE_OBJECT_START NAME={active_object}")
    if fan_command:
        generated.append(fan_command)
    generated.extend(
        [
            f"G1 X{resume_parameters['X']:g} Y{resume_parameters['Y']:g} F6000",
            f"G1 Z{resume_layer_z:g} F600",
            f"G92 E{0 if extrusion_mode == 'M83' else last_e:g}",
            extrusion_mode,
            "M118 PLR resume position prepared",
        ]
    )
    generated.extend(lines[resume_index:])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.write_text("\n".join(generated) + "\n", encoding="utf-8")
    except OSError as exc:
        raise RecoveryError(f"Cannot write recovery G-code: {exc}") from exc
    print(
        f"Created {output_path}; saved Z={saved_z:g}, "
        f"resume Z={resume_layer_z:g}, bed={bed_temp:g}C, nozzle={nozzle_temp:g}C"
    )
    return bed_temp, nozzle_temp, resume_layer_z


def run_generate(args: argparse.Namespace) -> None:
    variables = load_variables(args.variables)
    filepath = variables.get("filepath", "")
    filename = args.file or variables.get("last_file", "")
    saved_z = args.z
    if saved_z is None:
        try:
            saved_z = float(variables.get("power_resume_z", ""))
        except ValueError as exc:
            raise RecoveryError("Saved Z is missing or invalid") from exc
    if not filepath or not filename:
        raise RecoveryError("Saved filepath or filename is missing")
    basename = Path(filename).name
    if basename in ("", ".", ".."):
        raise RecoveryError("Saved print filename is invalid")
    output_path = args.output_dir / basename
    build_recovery(
        Path(filepath),
        saved_z,
        output_path,
        variables.get("plr_excluded_objects", ""),
        args.bed_factor,
        args.nozzle_factor,
        args.z_lift,
        args.dwell_ms,
    )


def run_clear(args: argparse.Namespace) -> None:
    if not args.output_dir.exists():
        print(f"No recovery directory to clear at {args.output_dir}")
        return
    removed = 0
    for target in args.output_dir.iterdir():
        if target.is_file() and target.suffix.lower() == ".gcode":
            target.unlink()
            removed += 1
    print(f"Removed {removed} generated recovery G-code file(s)")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    generate = subparsers.add_parser("generate", help="generate recovery G-code")
    generate.add_argument("--variables", type=Path, required=True)
    generate.add_argument("--output-dir", type=Path, default=None)
    generate.add_argument("--z", type=float)
    generate.add_argument("--file")
    generate.add_argument("--bed-factor", type=float, default=1.05)
    generate.add_argument("--nozzle-factor", type=float, default=1.05)
    generate.add_argument("--z-lift", type=float, default=2)
    generate.add_argument("--dwell-ms", type=int, default=0)
    clear = subparsers.add_parser("clear", help="remove the saved recovery G-code")
    clear.add_argument("--variables", type=Path, required=True)
    clear.add_argument("--output-dir", type=Path, default=None)
    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.error("a command is required")
    script_dir = Path(__file__).resolve().parent
    if args.output_dir is None:
        args.output_dir = script_dir.parent / "gcodes" / "plr_custom"
    try:
        if args.command == "generate":
            run_generate(args)
        else:
            run_clear(args)
    except (RecoveryError, OSError, ValueError) as exc:
        print(f"PLR stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
