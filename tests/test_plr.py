import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plr
import install_conflicts
import uninstall as uninstall_module


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
                    "M106 S64",
                    "G1 Z0.2 F600",
                    "G1 X10 Y10 E0.5",
                    "EXCLUDE_OBJECT_DEFINE NAME=PART_A",
                    "EXCLUDE_OBJECT_START NAME=PART_A",
                    "G1 Z0.4 F600",
                    "G1 X20 Y20 F6000",
                    "G1 X21 Y21 E0.6",
                    "M83",
                    "M106 S128",
                    "G1 Z0.6 F600",
                    "M106 S160",
                    "G1 X22 Y22 E0.7",
                    "G1 Z0.8 F600",
                    "M106 S192",
                    "G1 X23 Y23 E0.8",
                ]
            ),
            encoding="utf-8",
        )

    def generate(
        self,
        bed_factor=1.05,
        nozzle_factor=1.05,
        fan_off_layers=0,
        enclosure_wait_ms=0,
    ):
        return plr.build_recovery(
            self.source,
            0.2,
            self.output,
            "PART_B",
            bed_factor,
            nozzle_factor,
            2,
            0,
            fan_off_layers,
            enclosure_wait_ms,
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
        home_index = generated.index("G28 X Y")
        self.assertEqual(generated[home_index + 1], "G4 P0")

    def test_part_fan_stays_off_for_two_layers_then_restores(self):
        self.write_gcode()
        self.generate(fan_off_layers=2, enclosure_wait_ms=30000)
        generated = self.output.read_text(encoding="utf-8").splitlines()
        home_index = generated.index("G28 X Y")
        fan_off_index = generated.index("M106 S0")
        wait_index = generated.index("G4 P30000")
        resume_index = generated.index("G1 X20 Y20 F6000")
        restore_index = generated.index("G1 Z0.8 F600")
        fan_restore_index = generated.index("M106 S160")
        self.assertLess(home_index, fan_off_index)
        self.assertLess(fan_off_index, wait_index)
        self.assertLess(wait_index, resume_index)
        self.assertLess(fan_off_index, restore_index)
        self.assertLess(fan_restore_index, restore_index)
        self.assertNotIn("M106 S128", generated)
        self.assertIn("M106 S192", generated)

    def test_part_fan_can_resume_after_one_layer(self):
        self.write_gcode()
        self.generate(fan_off_layers=1, enclosure_wait_ms=30000)
        generated = self.output.read_text(encoding="utf-8").splitlines()
        self.assertLess(
            generated.index("M106 S128"), generated.index("G1 Z0.6 F600")
        )

    def test_part_fan_off_layer_count_is_limited_to_two(self):
        self.write_gcode()
        with self.assertRaises(plr.RecoveryError):
            self.generate(fan_off_layers=3)

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
        generated = (self.root / "sample.gcode").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertIn("M106 S0", generated)
        self.assertIn("G4 P30000", generated)

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


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.home = self.root / "printer-home"
        self.config = self.home / "printer_data" / "config"
        self.output_dir = self.home / "printer_data" / "gcodes" / "plr_custom"
        self.plr_dir = self.home / "printer_data" / "plr_custom"
        self.extra = (
            self.home / "klipper" / "klippy" / "extras"
            / "gcode_shell_command.py"
        )
        self.project_extra = self.root / "project" / "gcode_shell_command.py"
        self.config.mkdir(parents=True)
        self.output_dir.mkdir(parents=True)
        self.plr_dir.mkdir(parents=True)
        self.extra.parent.mkdir(parents=True)
        self.project_extra.parent.mkdir(parents=True)
        self.project_extra.write_text("project helper\n", encoding="utf-8")
        self.home.joinpath("printer_data", "config", "variables.cfg").write_text(
            "[Variables]\n", encoding="utf-8"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_removes_project_files_and_preserves_user_data(self):
        (self.config / "printer.cfg").write_text(
            "[include plr_custom.cfg]\n[printer]\n", encoding="utf-8"
        )
        (self.config / "moonraker.conf").write_text(
            "[include update_plr_custom.cfg]\n"
            "# [include update_plr.cfg]\n[server]\n",
            encoding="utf-8",
        )
        (self.config / "plr_custom.cfg").write_text(
            "# " + uninstall_module.MANAGED_MARKER + "\n", encoding="utf-8"
        )
        (self.config / "update_plr_custom.cfg").write_text(
            "[update_manager KlipperPLR-Custom]\n", encoding="utf-8"
        )
        for name in ("plr.py", "plr.sh", "clear_plr.sh"):
            (self.plr_dir / name).write_text("installed\n", encoding="utf-8")
        (self.output_dir / "resume.gcode").write_text("G1 X1\n", encoding="utf-8")
        (self.output_dir / "resume.GCODE").write_text("G1 X2\n", encoding="utf-8")
        (self.output_dir / "notes.txt").write_text("keep\n", encoding="utf-8")
        self.extra.write_text("shared helper\n", encoding="utf-8")

        messages = uninstall_module.uninstall(self.home, self.project_extra)

        self.assertNotIn("[include plr_custom.cfg]", (self.config / "printer.cfg").read_text())
        moonraker = (self.config / "moonraker.conf").read_text()
        self.assertNotIn("[include update_plr_custom.cfg]", moonraker)
        self.assertIn("# [include update_plr.cfg]", moonraker)
        self.assertFalse((self.config / "plr_custom.cfg").exists())
        self.assertFalse((self.config / "update_plr_custom.cfg").exists())
        self.assertFalse((self.plr_dir / "plr.py").exists())
        self.assertFalse((self.output_dir / "resume.gcode").exists())
        self.assertFalse((self.output_dir / "resume.GCODE").exists())
        self.assertTrue((self.output_dir / "notes.txt").exists())
        self.assertTrue((self.config / "variables.cfg").exists())
        self.assertEqual(self.extra.read_text(encoding="utf-8"), "shared helper\n")
        self.assertFalse(self.plr_dir.exists())
        self.assertTrue(any("Saved variables" in message for message in messages))

    def test_restores_backed_up_shared_helper(self):
        self.extra.write_bytes(self.project_extra.read_bytes())
        backup = self.extra.with_name(self.extra.name + ".pre-custom-plr")
        backup.write_text("original helper\n", encoding="utf-8")

        uninstall_module.uninstall(self.home, self.project_extra)

        self.assertEqual(self.extra.read_text(encoding="utf-8"), "original helper\n")
        self.assertFalse(backup.exists())

    def test_preserves_modified_shared_helper_and_backup(self):
        self.extra.write_text("customized helper\n", encoding="utf-8")
        backup = self.extra.with_name(self.extra.name + ".pre-custom-plr")
        backup.write_text("original helper\n", encoding="utf-8")

        messages = uninstall_module.uninstall(self.home, self.project_extra)

        self.assertEqual(self.extra.read_text(encoding="utf-8"), "customized helper\n")
        self.assertEqual(backup.read_text(encoding="utf-8"), "original helper\n")
        self.assertTrue(any("differs from the project copy" in message for message in messages))

    def test_removes_empty_recovery_directory(self):
        (self.config / "printer.cfg").write_text("", encoding="utf-8")
        (self.config / "moonraker.conf").write_text("", encoding="utf-8")

        messages = uninstall_module.uninstall(self.home, self.project_extra)

        self.assertFalse(self.output_dir.exists())
        self.assertFalse(self.plr_dir.exists())
        self.assertTrue(
            any("Removed 2 empty PLR directory/directories." == message
                for message in messages)
        )

    def test_refuses_to_remove_unmarked_config(self):
        active_config = self.config / "plr_custom.cfg"
        active_config.write_text("[gcode_macro RESUME_INTERRUPTED]\n", encoding="utf-8")
        managed_file = self.plr_dir / "plr.py"
        managed_file.write_text("installed\n", encoding="utf-8")

        with self.assertRaises(uninstall_module.UninstallError):
            uninstall_module.uninstall(self.home, self.project_extra)

        self.assertTrue(active_config.exists())
        self.assertTrue(managed_file.exists())

    def test_refuses_invalid_recovery_path_before_editing_config(self):
        printer_config = self.config / "printer.cfg"
        printer_config.write_text("[include plr_custom.cfg]\n", encoding="utf-8")
        self.output_dir.rmdir()
        self.output_dir.write_text("user data\n", encoding="utf-8")

        with self.assertRaises(uninstall_module.UninstallError):
            uninstall_module.uninstall(self.home, self.project_extra)

        self.assertIn("[include plr_custom.cfg]", printer_config.read_text())
        self.assertEqual(self.output_dir.read_text(), "user data\n")

    def test_moves_standard_clone_to_backup_and_preserves_its_files(self):
        clone = self.home / uninstall_module.PROJECT_DIRECTORY
        clone.mkdir()
        (clone / ".git").mkdir()
        (clone / "local-change.txt").write_text("keep me\n", encoding="utf-8")

        message = uninstall_module.move_clone_to_backup(self.home, clone)

        self.assertFalse(clone.exists())
        self.assertIn("files preserved", message)
        backup = next(self.home.glob(
            uninstall_module.PROJECT_DIRECTORY + ".uninstalled-*"
        ))
        self.assertTrue((backup / ".git").is_dir())
        self.assertEqual(
            (backup / "local-change.txt").read_text(encoding="utf-8"),
            "keep me\n",
        )

    def test_does_not_move_clone_outside_standard_home_path(self):
        clone = self.root / "elsewhere" / uninstall_module.PROJECT_DIRECTORY
        clone.mkdir(parents=True)

        message = uninstall_module.move_clone_to_backup(self.home, clone)

        self.assertTrue(clone.is_dir())
        self.assertIn("left in place", message)


class InstallConflictTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = Path(self.temp_dir.name) / "config"
        self.config.mkdir()
        self.active_config = self.config / "plr_custom.cfg"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_detects_legacy_includes_and_conflicting_macros(self):
        (self.config / "printer.cfg").write_text(
            "[include plr.cfg]\n"
            "[printer]\nkinematics: corexy\n"
            "[gcode_macro RESUME_INTERRUPTED]\ngcode:\n  G1 X1\n"
            "[gcode_macro EXCLUDE_OBJECT]\ngcode:\n  G1 X2\n",
            encoding="utf-8",
        )

        conflicts = install_conflicts.find_conflicts(
            self.config, self.active_config
        )

        self.assertEqual(len(conflicts), 3)
        self.assertTrue(
            any("[include plr.cfg]" in conflict for conflict in conflicts)
        )
        self.assertTrue(
            any("[gcode_macro RESUME_INTERRUPTED]" in conflict for conflict in conflicts)
        )

    def test_ignores_dormant_backup_configs(self):
        (self.config / "printer.cfg").write_text(
            "[printer]\nkinematics: corexy\n", encoding="utf-8"
        )
        (self.config / "printer-backup.cfg").write_text(
            "[include plr.cfg]\n", encoding="utf-8"
        )

        conflicts = install_conflicts.find_conflicts(
            self.config, self.active_config
        )

        self.assertEqual(conflicts, [])

    def test_allows_clean_symlinked_config(self):
        printer_config = self.config / "printer.cfg"
        printer_config.write_text("[include mainsail.cfg]\n", encoding="utf-8")
        (self.config / "mainsail.cfg").write_text(
            "[gcode_macro CANCEL_PRINT]\ngcode:\n  RESPOND MSG=cancel\n",
            encoding="utf-8",
        )
        original_is_symlink = Path.is_symlink

        def mark_mainsail_as_symlink(path):
            return path.name == "mainsail.cfg" or original_is_symlink(path)

        with mock.patch.object(Path, "is_symlink", mark_mainsail_as_symlink):
            conflicts = install_conflicts.find_conflicts(
                self.config, self.active_config
            )
            result = install_conflicts.disable_conflicts(self.config)

        self.assertEqual(conflicts, [])
        self.assertEqual(result, (0, 0))

    def test_refuses_plr_conflict_inside_symlinked_config(self):
        printer_config = self.config / "printer.cfg"
        printer_config.write_text("[include mainsail.cfg]\n", encoding="utf-8")
        (self.config / "mainsail.cfg").write_text(
            "[gcode_macro RESUME_INTERRUPTED]\ngcode:\n", encoding="utf-8"
        )
        original_is_symlink = Path.is_symlink

        def mark_mainsail_as_symlink(path):
            return path.name == "mainsail.cfg" or original_is_symlink(path)

        with mock.patch.object(Path, "is_symlink", mark_mainsail_as_symlink):
            with self.assertRaises(ValueError):
                install_conflicts.find_conflicts(
                    self.config, self.active_config
                )

    def test_disables_detected_sections_and_preserves_other_config(self):
        printer_config = self.config / "printer.cfg"
        printer_config.write_text(
            "[include plr.cfg]\n"
            "[printer]\nkinematics: corexy\n"
            "[gcode_macro RESUME_INTERRUPTED]\ngcode:\n  G1 X1\n"
            "[gcode_macro CUSTOM]\ngcode:\n  RESPOND MSG=keep\n",
            encoding="utf-8",
        )

        include_count, macro_count = install_conflicts.disable_conflicts(
            self.config
        )
        updated = printer_config.read_text(encoding="utf-8")

        self.assertEqual((include_count, macro_count), (1, 1))
        self.assertIn("# Disabled by custom PLR installer after backup: [include plr.cfg]", updated)
        self.assertIn(
            "# Disabled by custom PLR installer after backup: "
            "[gcode_macro RESUME_INTERRUPTED]",
            updated,
        )
        self.assertIn("#   G1 X1", updated)
        self.assertIn("[printer]\nkinematics: corexy", updated)
        self.assertIn("[gcode_macro CUSTOM]\ngcode:\n  RESPOND MSG=keep", updated)

    def test_detects_existing_unmanaged_active_config(self):
        self.active_config.write_text(
            "[gcode_macro RESUME_INTERRUPTED]\ngcode:\n", encoding="utf-8"
        )

        conflicts = install_conflicts.find_conflicts(
            self.config, self.active_config
        )

        self.assertTrue(any("unmanaged PLR config" in item for item in conflicts))

    def test_detects_even_an_empty_unmanaged_active_config(self):
        self.active_config.write_text("", encoding="utf-8")

        conflicts = install_conflicts.find_conflicts(
            self.config, self.active_config
        )

        self.assertTrue(any("unmanaged PLR config" in item for item in conflicts))


if __name__ == "__main__":
    unittest.main()
