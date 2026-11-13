import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plr


class RecoveryGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / "sample.gcode"
        self.output = self.root / "recovery.gcode"

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_gcode(self, bed=55, nozzle=190, first_bed=60, first_nozzle=200):
        self.source.write_text(
            "\n".join(
                [
                    "; hot_plate_temp = " + str(bed),
                    "; hot_plate_temp_initial_layer = " + str(first_bed),
                    "; nozzle_temperature = " + str(nozzle),
                    "; nozzle_temperature_initial_layer = " + str(first_nozzle),
                    "M140 S" + str(first_bed),
                    "M104 S" + str(first_nozzle),
                    "G1 Z0.2 F600",
                    "G1 X10 Y10 E0.5",
                    "EXCLUDE_OBJECT_DEFINE NAME=PART_A",
                    "EXCLUDE_OBJECT_START NAME=PART_A",
                    "G1 Z0.4 F600",
                    "G1 X20 Y20 F6000",
                    "G1 X21 Y21 E0.6",
                    "M83",
                    "M106 S128",
                ]
            ),
            encoding="utf-8",
        )

    def generate(self, bed_factor=1.05, nozzle_factor=1.05):
        return plr.build_recovery(
            self.source,
            0.2,
            self.output,
            "PART_B",
            bed_factor,
            nozzle_factor,
            2,
            0,
        )

    def test_reads_normal_targets_and_ignores_first_layer_targets(self):
        self.write_gcode()
        bed, nozzle, resume_z = self.generate()
        generated = self.output.read_text(encoding="utf-8").splitlines()
        expected = [
            "M140 S57.75",
            "M190 S57.75",
            "M104 S199.5",
            "M109 S199.5",
            "G4 P0",
            "M140 S55",
            "M104 S190",
            "G1 Z2 F600",
            "G28 X Y",
        ]
        positions = [generated.index(command) for command in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual((bed, nozzle, resume_z), (55, 190, 0.4))
        self.assertIn("EXCLUDE_OBJECT NAME=PART_B", generated)
        self.assertIn("EXCLUDE_OBJECT_START NAME=PART_A", generated)
        self.assertIn("M106 S128", generated)
        self.assertIn("M83", generated)

    def test_uses_material_specific_targets(self):
        self.write_gcode(bed=100, nozzle=245, first_bed=110, first_nozzle=255)
        self.generate()
        generated = self.output.read_text(encoding="utf-8").splitlines()
        for command in (
            "M140 S105",
            "M190 S105",
            "M104 S257.25",
            "M109 S257.25",
            "M140 S100",
            "M104 S245",
        ):
            self.assertIn(command, generated)

    def test_refuses_missing_saved_layer(self):
        self.write_gcode()
        with self.assertRaises(plr.RecoveryError):
            plr.build_recovery(
                self.source, 1.24, self.output, "", 1.05, 1.05, 2, 0
            )

    def test_refuses_preheat_factor_above_allowed_range(self):
        self.write_gcode()
        with self.assertRaises(plr.RecoveryError):
            self.generate(bed_factor=1.11)

    def test_reads_klipper_quoted_saved_variables(self):
        variables = self.root / "variables.cfg"
        variables.write_text(
            "[Variables]\n"
            "filepath = '\"/tmp/print file.gcode\"'\n"
            "last_file = '\"print file.gcode\"'\n"
            "power_resume_z = 0.4\n",
            encoding="utf-8",
        )
        values = plr.load_variables(variables)
        self.assertEqual(values["filepath"], "/tmp/print file.gcode")
        self.assertEqual(values["last_file"], "print file.gcode")

    def test_cli_generates_recovery_from_saved_variables(self):
        self.write_gcode()
        variables = self.root / "variables.cfg"
        variables.write_text(
            "[Variables]\n"
            "filepath = '" + repr(str(self.source)) + "'\n"
            "last_file = '\"sample.gcode\"'\n"
            "power_resume_z = 0.2\n"
            "plr_excluded_objects = '\"PART_B\"'\n",
            encoding="utf-8",
        )
        with mock.patch.object(
            sys,
            "argv",
            [
                "plr.py",
                "generate",
                "--variables",
                str(variables),
                "--output-dir",
                str(self.root),
                "--z",
                "0.2",
                "--file",
                "sample.gcode",
                "--bed-factor",
                "1.05",
                "--nozzle-factor",
                "1.05",
                "--z-lift",
                "2",
                "--dwell-ms",
                "0",
            ],
        ):
            self.assertEqual(plr.main(), 0)
        self.assertTrue((self.root / "sample.gcode").is_file())

    def test_clear_removes_only_generated_gcode_files(self):
            variables = self.root / "variables.cfg"
            variables.write_text("[Variables]\n", encoding="utf-8")
            output_dir = self.root / "gcodes" / "plr_custom"
            output_dir.mkdir(parents=True)
            generated = output_dir / "resume.gcode"
            unrelated = output_dir / "notes.txt"
            generated.write_text("G1 X1\n", encoding="utf-8")
            unrelated.write_text("keep\n", encoding="utf-8")
            with mock.patch.object(
                sys,
                "argv",
                [
                    "plr.py",
                    "clear",
                    "--variables",
                    str(variables),
                    "--output-dir",
                    str(output_dir),
                ],
            ):
                self.assertEqual(plr.main(), 0)
            self.assertFalse(generated.exists())
            self.assertTrue(unrelated.exists())


if __name__ == "__main__":
    unittest.main()
