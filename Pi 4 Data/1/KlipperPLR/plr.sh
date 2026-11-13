#!/bin/bash
set -euo pipefail

VARIABLES_FILE={USER_HOME}/printer_data/config/variables.cfg
PLR_PATH={USER_HOME}/printer_data/gcodes/plr
filepath=$(sed -n "s/.*filepath *= *'\([^']*\)'.*/\1/p" "$VARIABLES_FILE")
saved_file=$(sed -n "s/.*last_file *= *'\([^']*\)'.*/\1/p" "$VARIABLES_FILE")
resume_z=${1:-$(sed -n 's/.*power_resume_z *= *\([0-9.]*\).*/\1/p' "$VARIABLES_FILE")}
last_file=${2:-$saved_file}
bed_preheat_factor=${3:-1.05}
nozzle_preheat_factor=${4:-1.05}
z_lift=${5:-2}
dwell_ms=${6:-0}
excluded_names=$(sed -n "s/.*plr_excluded_objects *= *'\([^']*\)'.*/\1/p" "$VARIABLES_FILE")

if [[ -z "$filepath" || -z "$resume_z" || -z "$last_file" ]]; then
  echo "PLR stopped: filepath, saved Z, or filename is missing" >&2
  exit 1
fi

mkdir -p "$PLR_PATH"
output_path="$PLR_PATH/$(basename "$last_file")"
rm -f "$output_path"
python3 - "$filepath" "$resume_z" "$output_path" "$excluded_names" "$bed_preheat_factor" "$nozzle_preheat_factor" "$z_lift" "$dwell_ms" <<'PY'
import re
import sys
import math
from pathlib import Path

source_path = Path(sys.argv[1])
saved_z = float(sys.argv[2])
output_path = Path(sys.argv[3])
excluded_names = sys.argv[4].split()
bed_preheat_factor = float(sys.argv[5])
nozzle_preheat_factor = float(sys.argv[6])
z_lift = float(sys.argv[7])
dwell_ms = int(sys.argv[8])
if not math.isfinite(bed_preheat_factor) or not 1 <= bed_preheat_factor <= 1.1:
	raise SystemExit("PLR stopped: bed preheat factor must be between 1.0 and 1.1")
if not math.isfinite(nozzle_preheat_factor) or not 1 <= nozzle_preheat_factor <= 1.1:
	raise SystemExit("PLR stopped: nozzle preheat factor must be between 1.0 and 1.1")
if not math.isfinite(z_lift) or not 0 <= z_lift <= 20:
	raise SystemExit("PLR stopped: Z lift must be between 0 and 20 mm")
if not 0 <= dwell_ms <= 60000:
	raise SystemExit("PLR stopped: dwell must be between 0 and 60000 ms")
lines = source_path.read_text(errors="replace").splitlines()

number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
parameter_pattern = re.compile(rf"(?:^|\s)([A-Z])\s*({number})(?=\s|$)", re.IGNORECASE)
motion_pattern = re.compile(r"^G(?:0|00|1|01)(?:\s|$)", re.IGNORECASE)

def command_and_parameters(line):
	command = line.split(";", 1)[0].strip().upper()
	if not motion_pattern.match(command):
		return None, {}
	parameters = {key.upper(): float(value) for key, value in parameter_pattern.findall(command)}
	return command, parameters

motions = []
for index, line in enumerate(lines):
	command, parameters = command_and_parameters(line)
	if command is not None:
		motions.append((index, command, parameters))

saved_matches = [item for item in motions if "Z" in item[2] and abs(item[2]["Z"] - saved_z) <= 0.005]
if not saved_matches:
	raise SystemExit(f"PLR stopped: no G-code move matches saved Z={saved_z:g}; refusing to replay from the start")

last_saved_index = saved_matches[-1][0]
resume_height_move = next(
	(item for item in motions if item[0] > last_saved_index and item[2].get("Z", saved_z) > saved_z + 0.005),
	None,
)
if resume_height_move is None:
	raise SystemExit(f"PLR stopped: no later layer found after saved Z={saved_z:g}")

resume_layer_z = resume_height_move[2]["Z"]
resume_move = next(
	(
		item for item in motions
		if item[0] >= resume_height_move[0]
		and "X" in item[2]
		and "Y" in item[2]
		and "E" not in item[2]
	),
	None,
)
if resume_move is None:
	raise SystemExit("PLR stopped: no non-extruding XY travel move found at the resume layer")

resume_index, _, resume_parameters = resume_move

temperature_pattern = re.compile(
	rf"^\s*(M104|M109|M140|M190)\s+.*?\bS\s*({number})(?:\s|$)",
	re.IGNORECASE,
)
bed_temp = None
nozzle_temp = None
for line in lines[:resume_index]:
	match = temperature_pattern.match(line.split(";", 1)[0])
	if match:
		command, value = match.group(1).upper(), float(match.group(2))
		if command in ("M140", "M190"):
			bed_temp = value
		else:
			nozzle_temp = value

def metadata_temperature(keys):
	pattern = re.compile(rf"^\s*;\s*(?:{'|'.join(keys)})\s*=\s*({number})(?:\s*,.*)?\s*$", re.IGNORECASE)
	for line in lines:
		match = pattern.match(line)
		if match:
			return float(match.group(1))
	return None

bed_metadata_temp = metadata_temperature(("hot_plate_temp", "bed_temperature"))
nozzle_metadata_temp = metadata_temperature(("nozzle_temperature",))
if bed_metadata_temp is not None:
	bed_temp = bed_metadata_temp
if nozzle_metadata_temp is not None:
	nozzle_temp = nozzle_metadata_temp
if bed_temp is None or nozzle_temp is None or bed_temp <= 0 or nozzle_temp <= 0:
	raise SystemExit("PLR stopped: normal bed/nozzle temperatures were not found in the print G-code")

object_definitions = [
	line.split(";", 1)[0].strip()
	for line in lines
	if re.match(r"^\s*EXCLUDE_OBJECT_DEFINE\s+NAME=", line, re.IGNORECASE)
]
start_pattern = re.compile(r"^\s*EXCLUDE_OBJECT_START\b.*?\bNAME=([^\s;]+)", re.IGNORECASE)
end_pattern = re.compile(r"^\s*EXCLUDE_OBJECT_END\b", re.IGNORECASE)
active_object = None
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
	_, parameters = command_and_parameters(line)
	if "E" in parameters:
		last_e = parameters["E"]

output = [
	"SET_GCODE_OFFSET Z=0 MOVE=0",
	f"SET_KINEMATIC_POSITION Z={saved_z:g} SET_HOMED=XYZ",
	f"M140 S{bed_temp * bed_preheat_factor:g}",
	f"M190 S{bed_temp * bed_preheat_factor:g}",
	f"M104 S{nozzle_temp * nozzle_preheat_factor:g}",
	f"M109 S{nozzle_temp * nozzle_preheat_factor:g}",
	f"G4 P{dwell_ms}",
	f"M140 S{bed_temp:g}",
	f"M104 S{nozzle_temp:g}",
	"G91",
	f"G1 Z{z_lift:g} F600",
	"G90",
	"G28 X Y",
	"EXCLUDE_OBJECT_DEFINE RESET=1",
]
output.extend(object_definitions)
output.extend(f"EXCLUDE_OBJECT NAME={name}" for name in excluded_names)
if active_object:
	output.append(f"EXCLUDE_OBJECT_START NAME={active_object}")
if fan_command:
	output.append(fan_command)
output.extend([
	f"G1 X{resume_parameters['X']:g} Y{resume_parameters['Y']:g} F6000",
	f"G1 Z{resume_layer_z:g} F600",
	f"G92 E{0 if extrusion_mode == 'M83' else last_e:g}",
	extrusion_mode,
	"M118 PLR resume position prepared",
])
output.extend(lines[resume_index:])
output_path.write_text("\n".join(output) + "\n")
print(
	f"Created {output_path}; saved Z={saved_z:g}, resume Z={resume_layer_z:g}, "
	f"bed={bed_temp:g}C, nozzle={nozzle_temp:g}C"
)
PY
