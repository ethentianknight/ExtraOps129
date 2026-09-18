import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import eo129


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RuntimeInstallLayout(unittest.TestCase):
    def install_mode(self, mode):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        package = root / "Extra Ops 129"
        game = root / "mgspw"
        archives = game / "MLG" / "disc0_rel"
        data = package / "data"
        archives.mkdir(parents=True)
        data.mkdir(parents=True)
        names = eo129.NAMES
        for name in names:
            (archives / name).write_bytes(("vanilla-" + name).encode())
        executable = game / "METAL GEAR SOLID PEACE WALKER.exe"
        executable.write_bytes(b"exe")
        original = {name: sha(archives / name) for name in names}
        models = {name: hashlib.sha256(("model-" + name).encode()).hexdigest() for name in names}
        coop = dict(original)
        coop["009645fa.PDT"] = hashlib.sha256(b"four-coop").hexdigest()
        both = dict(models)
        both["009645fa.PDT"] = hashlib.sha256(b"four-both").hexdigest()
        document = {
            "exe_sha256": sha(executable),
            "original_files": original,
            "modes": {"models": {"files": models}, "coop": {"files": coop}, "both": {"files": both}},
            "patches": ({"model_" + name: {"file": name + ".patch"} for name in names}
                        | {"coop_from_vanilla": {"file": "coop.patch"}, "coop_from_models": {"file": "both.patch"}}),
        }
        eo129.ROOT, eo129.DATA = package, data
        eo129.STATE = package / "state"
        eo129.USER_BACKUP = root / "Extra Ops 129 User Files Backup"
        eo129.BACKUP = eo129.USER_BACKUP / "game-files"
        eo129.MISSION_FILES = eo129.USER_BACKUP / "mission-modes"
        eo129.LEGACY_BACKUP = package / "backups"
        eo129.digest = sha
        eo129.game_dir = lambda: game
        eo129.require_game_closed = lambda: None
        eo129.backup_saves = lambda game, root: None
        eo129.manifest = lambda: document
        eo129.reconstruct_model = lambda source, patch, destination, record: destination.write_bytes(("model-" + destination.name).encode())
        eo129.apply_coop = lambda source, patch, destination, record: destination.write_bytes(b"four-both" if mode == "both" else b"four-coop")
        eo129.install(mode)
        return temporary, package, game, original, models, coop, both

    def test_both_installs_combined_archive_enabled_by_default(self):
        temporary, package, game, original, models, coop, both = self.install_mode("both")
        try:
            archives = game / "MLG" / "disc0_rel"
            self.assertEqual({name: sha(archives / name) for name in eo129.NAMES}, both)
            receipt = json.loads((package / "state" / "install.json").read_text())
            self.assertEqual(receipt["installed_files"], both)
            self.assertTrue(receipt["mission_files"]["enabled"])
            self.assertEqual(Path(receipt["backup"]), package.parent / "Extra Ops 129 User Files Backup")
            self.assertTrue((package.parent / "Extra Ops 129 User Files Backup" / "game-files").is_dir())
            stored = package.parent / "Extra Ops 129 User Files Backup" / "mission-modes" / "009645fa.two-player.PDT"
            self.assertEqual(sha(stored), models["009645fa.PDT"])
        finally:
            temporary.cleanup()

    def test_coop_defaults_enabled_and_swaps_complete_libraries(self):
        temporary, package, game, original, models, coop, both = self.install_mode("coop")
        try:
            archives = game / "MLG" / "disc0_rel"
            self.assertEqual({name: sha(archives / name) for name in eo129.NAMES}, coop)
            receipt = json.loads((package / "state" / "install.json").read_text())
            self.assertTrue(receipt["mission_files"]["enabled"])
            eo129.set_four_player(False)
            self.assertEqual(sha(archives / "009645fa.PDT"), original["009645fa.PDT"])
            receipt = json.loads((package / "state" / "install.json").read_text())
            self.assertFalse(receipt["mission_files"]["enabled"])
            eo129.set_four_player(True)
            self.assertEqual(sha(archives / "009645fa.PDT"), coop["009645fa.PDT"])
            receipt = json.loads((package / "state" / "install.json").read_text())
            self.assertTrue(receipt["mission_files"]["enabled"])
        finally:
            temporary.cleanup()

    def test_reinstall_after_steam_restores_archives_with_stale_receipt(self):
        temporary, package, game, original, models, coop, both = self.install_mode("both")
        try:
            archives = game / "MLG" / "disc0_rel"
            for name in eo129.NAMES:
                (archives / name).write_bytes(("vanilla-" + name).encode())
            self.assertTrue((package / "state" / "install.json").exists())
            eo129.install("both")
            self.assertEqual({name: sha(archives / name) for name in eo129.NAMES}, both)
            eo129.set_four_player(False)
            self.assertEqual(sha(archives / "009645fa.PDT"), models["009645fa.PDT"])
            eo129.uninstall()
            self.assertEqual({name: sha(archives / name) for name in eo129.NAMES}, original)
        finally:
            temporary.cleanup()

    def test_partial_steam_restore_still_refuses_reinstall(self):
        temporary, package, game, original, models, coop, both = self.install_mode("both")
        try:
            archives = game / "MLG" / "disc0_rel"
            (archives / eo129.NAMES[0]).write_bytes(("vanilla-" + eo129.NAMES[0]).encode())
            before = {name: sha(archives / name) for name in eo129.NAMES}
            with self.assertRaisesRegex(RuntimeError, "already installed"):
                eo129.install("both")
            self.assertEqual({name: sha(archives / name) for name in eo129.NAMES}, before)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
