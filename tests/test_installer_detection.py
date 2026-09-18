import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import eo129


class ExistingInstallDetection(unittest.TestCase):
    def run_case(self, with_backup, legacy=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game = root / "mgspw"
            archives = game / "MLG" / "disc0_rel"
            archives.mkdir(parents=True)
            for name in eo129.NAMES:
                (archives / name).write_bytes(b"changed")
            (game / "METAL GEAR SOLID PEACE WALKER.exe").write_bytes(b"exe")
            eo129.ROOT = root / "Extra Ops 129"
            eo129.DATA = eo129.ROOT / "data"
            eo129.STATE = eo129.ROOT / "state"
            eo129.USER_BACKUP = root / "Extra Ops 129 User Files Backup"
            eo129.BACKUP = eo129.USER_BACKUP / "game-files"
            eo129.LEGACY_BACKUP = eo129.ROOT / "backups"
            if with_backup:
                backup = eo129.LEGACY_BACKUP if legacy else eo129.BACKUP
                backup.mkdir(parents=True)
                for name in eo129.NAMES:
                    (backup / name).write_bytes(b"backup")
            eo129.game_dir = lambda: game
            eo129.require_game_closed = lambda: None
            eo129.manifest = lambda: {
                "exe_sha256": "exe",
                "original_files": {name: "vanilla" for name in eo129.NAMES},
            }
            eo129.digest = lambda path: "exe" if path.name.endswith(".exe") else "changed"
            with self.assertRaises(RuntimeError) as caught:
                eo129.install("both")
            return str(caught.exception)

    def test_existing_install_with_backup(self):
        self.assertEqual(
            self.run_case(True),
            "Extra Ops is already installed, you need to uninstall it first to run the installer again",
        )

    def test_existing_install_without_backup(self):
        self.assertEqual(
            self.run_case(False),
            "Extra Ops is already installed and it appears the backup folder was removed. You will need to verify your game installation via steam in order to properly uninstall the previous mod, and you should then be able to install extra ops 129.",
        )

    def test_existing_install_with_legacy_backup(self):
        self.assertEqual(
            self.run_case(True, legacy=True),
            "Extra Ops is already installed, you need to uninstall it first to run the installer again",
        )


if __name__ == "__main__":
    unittest.main()
