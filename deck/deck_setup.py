import gzip
import hashlib
import json
import os
import shutil
import struct
import sys
import time
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE = ROOT / "state"
USER_BACKUP = ROOT.parent / "Extra Ops 129 User Files Backup"
BACKUP = USER_BACKUP / "game-files"
MISSION_FILES = USER_BACKUP / "mission-modes"
LEGACY_BACKUP = ROOT / "backups"
NAMES = ("002aba34.DAT", "002aba34.KEY", "009645fa.PDT")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def game_dir():
    for path in (ROOT.parent / "mgspw", ROOT.parent):
        if (path / "METAL GEAR SOLID PEACE WALKER.exe").is_file() and (path / "MLG/disc0_rel").is_dir():
            return path
    raise RuntimeError("Put the complete Extra Ops 129 folder beside the mgspw folder.")


def game_running():
    for item in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            if b"METAL GEAR SOLID PEACE WALKER.exe" in item.read_bytes():
                return True
        except OSError:
            pass
    return False


def steam_running():
    for item in Path("/proc").glob("[0-9]*/comm"):
        try:
            if item.read_text(errors="ignore").strip().lower() == "steam":
                return True
        except OSError:
            pass
    return False


def require_game_closed():
    if game_running():
        raise RuntimeError("Close Peace Walker before installation or removal.")


def manifest():
    return json.loads((DATA / "manifest.json").read_text())


def inventory(root):
    files = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("Save folder contains a link; backup stopped.")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = digest(path)
    return files


def backup_saves(game):
    source = game.parent / "mgspw_savedata_win"
    if not source.is_dir():
        raise RuntimeError(f"Save folder not found: {source}")
    before = inventory(source)
    if not before:
        raise RuntimeError("Save folder is empty; installation stopped.")
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    destination = USER_BACKUP / "save-backups" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination / "files")
    if inventory(destination / "files") != before or inventory(source) != before:
        raise RuntimeError("Save backup verification failed.")
    receipt = {"game": str(game.resolve()), "save_root": str(source.resolve()), "files": before, "created_utc": name}
    (destination / "manifest.json").write_text(json.dumps(receipt, indent=2))
    print(f"Verified save backup: {destination}")


def reconstruct_model(source, patch, destination, record):
    if digest(patch) != record["sha256"]:
        raise RuntimeError("A model patch is damaged. Extract the package again.")
    shutil.copy2(source, destination)
    with gzip.open(patch, "rb") as inp, destination.open("r+b") as out:
        if inp.read(8) != b"EO129P1\0":
            raise RuntimeError("Invalid model patch.")
        size, count = struct.unpack("<QI", inp.read(12))
        if size != record["output_size"]:
            raise RuntimeError("Unexpected model patch size.")
        end = 0
        for _ in range(count):
            offset, length = struct.unpack("<QI", inp.read(12))
            if offset < end or offset + length > size:
                raise RuntimeError("Invalid model patch range.")
            value = inp.read(length)
            if len(value) != length:
                raise RuntimeError("Truncated model patch.")
            out.seek(offset)
            out.write(value)
            end = offset + length
        if inp.read(1):
            raise RuntimeError("Unexpected model patch data.")
        out.truncate(size)
    if digest(destination) != record["output_sha256"]:
        raise RuntimeError("Rebuilt model archive failed verification.")


def apply_coop(source, patch, destination, record):
    if digest(patch) != record["sha256"]:
        raise RuntimeError("The co-op patch is damaged. Extract the package again.")
    shutil.copy2(source, destination)
    payload = zlib.decompress(patch.read_bytes())
    if payload[:4] != b"CP4P":
        raise RuntimeError("Invalid co-op patch.")
    cursor = 8
    with destination.open("r+b") as stream:
        for _ in range(struct.unpack_from("<I", payload, 4)[0]):
            offset, length = struct.unpack_from("<QI", payload, cursor)
            cursor += 12
            if offset + length > record["output_size"] or cursor + length > len(payload):
                raise RuntimeError("Invalid co-op patch range.")
            stream.seek(offset)
            stream.write(payload[cursor:cursor + length])
            cursor += length
    if cursor != len(payload) or digest(destination) != record["output_sha256"]:
        raise RuntimeError("Rebuilt co-op archive failed verification.")


def install(mode):
    if mode not in ("models", "coop", "both"):
        raise ValueError("Invalid installation mode.")
    require_game_closed()
    game = game_dir()
    doc = manifest()
    archives = game / "MLG/disc0_rel"
    if digest(game / "METAL GEAR SOLID PEACE WALKER.exe") != doc["exe_sha256"]:
        raise RuntimeError("This game executable is not supported. No files changed.")
    current = {name: digest(archives / name) for name in NAMES}
    prior = (STATE / "install.json").exists() or current != doc["original_files"]
    if prior:
        complete_backup = any(all((folder / name).is_file() for name in NAMES) for folder in (BACKUP, LEGACY_BACKUP))
        if complete_backup:
            raise RuntimeError("Extra Ops is already installed, you need to uninstall it first to run the installer again")
        raise RuntimeError("Extra Ops is already installed and it appears the backup folder was removed. You will need to verify your game installation via steam in order to properly uninstall the previous mod, and you should then be able to install extra ops 129.")
    local_dll = game / "winmm.dll"
    if local_dll.exists():
        raise RuntimeError("mgspw/winmm.dll already exists. Remove the other DLL mod first.")
    backup_saves(game)
    BACKUP.mkdir(parents=True, exist_ok=True)
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    for name in NAMES:
        destination = BACKUP / name
        if destination.exists() and digest(destination) != doc["original_files"][name]:
            raise RuntimeError(f"Existing backup does not match vanilla: {name}")
        if not destination.exists():
            shutil.copy2(archives / name, destination)
        shutil.copy2(destination, work / name)
    if mode in ("models", "both"):
        for name in NAMES:
            record = doc["patches"]["model_" + name]
            reconstruct_model(BACKUP / name, DATA / record["file"], work / name, record)
    two_player = digest(work / "009645fa.PDT")
    two_staged = work / "009645fa.two-player.PDT"
    if mode in ("coop", "both"):
        shutil.copy2(work / "009645fa.PDT", two_staged)
        patch_name = "coop_from_models" if mode == "both" else "coop_from_vanilla"
        record = doc["patches"][patch_name]
        temporary = work / "009645fa.PDT.four"
        apply_coop(work / "009645fa.PDT", DATA / record["file"], temporary, record)
        os.replace(temporary, work / "009645fa.PDT")
    expected = doc["modes"][mode]["files"]
    if {name: digest(work / name) for name in NAMES} != expected:
        raise RuntimeError("Staged installation verification failed.")
    mission_files = {}
    if mode in ("coop", "both"):
        MISSION_FILES.mkdir(parents=True, exist_ok=True)
        shutil.copy2(two_staged, MISSION_FILES / "009645fa.two-player.PDT")
        (MISSION_FILES / "009645fa.four-player.PDT").unlink(missing_ok=True)
        mission_files = {"two_player_sha256": two_player, "four_player_sha256": expected["009645fa.PDT"], "enabled": True}
    STATE.mkdir(exist_ok=True)
    receipt = {"mode": mode, "game": str(game.resolve()), "backup": str(USER_BACKUP.resolve()), "original_files": current, "installed_files": expected, "mission_files": mission_files, "runtime_sha256": digest(ROOT / "deck/winmm.dll"), "installed_utc": time.time()}
    (STATE / "install.json").write_text(json.dumps(receipt, indent=2))
    try:
        for name in NAMES:
            shutil.copy2(work / name, archives / name)
            if digest(archives / name) != expected[name]:
                raise RuntimeError(f"Installed file verification failed: {name}")
        shutil.copy2(ROOT / "deck/winmm.dll", local_dll)
        (STATE / "deck_mode.txt").write_text(mode + "\n")
    except BaseException:
        for name in NAMES:
            shutil.copy2(BACKUP / name, archives / name)
        local_dll.unlink(missing_ok=True)
        (STATE / "install.json").unlink(missing_ok=True)
        (STATE / "deck_mode.txt").unlink(missing_ok=True)
        raise
    finally:
        for name in NAMES:
            (work / name).unlink(missing_ok=True)
        two_staged.unlink(missing_ok=True)
    print(f"Installed Steam Deck mode: {mode}.")
    print('Set Steam launch options to: WINEDLLOVERRIDES="winmm=n,b" %command%')


def receipt():
    path = STATE / "install.json"
    if not path.is_file():
        raise RuntimeError("No Steam Deck installation record was found.")
    return json.loads(path.read_text())


def set_four_player(enabled):
    require_game_closed()
    receipt_path = STATE / "install.json"
    record = receipt()
    mode = record["mode"]
    if mode not in ("coop", "both"):
        raise RuntimeError("Four-player co-op was not selected during installation. Reinstall using co-op or both mode.")
    mission = record.get("mission_files", {})
    if not mission:
        raise RuntimeError("This installation does not include switchable mission libraries. Reinstall Extra Ops 129.")
    current = bool(mission.get("enabled"))
    if current == enabled:
        print("4-player co-op is already " + ("enabled." if enabled else "disabled."))
        return
    game = Path(record["game"])
    archive = game / "MLG/disc0_rel/009645fa.PDT"
    source = MISSION_FILES / ("009645fa.four-player.PDT" if enabled else "009645fa.two-player.PDT")
    saved = MISSION_FILES / ("009645fa.two-player.PDT" if enabled else "009645fa.four-player.PDT")
    current_hash = mission["two_player_sha256"] if enabled else mission["four_player_sha256"]
    target_hash = mission["four_player_sha256"] if enabled else mission["two_player_sha256"]
    if digest(archive) != current_hash:
        raise RuntimeError("The active mission library changed. Swap stopped.")
    if not source.is_file() or digest(source) != target_hash:
        raise RuntimeError("The stored mission library is missing or changed. Swap stopped.")
    if saved.exists():
        raise RuntimeError("The mission-library swap folder has an unexpected extra file. Swap stopped.")
    os.replace(archive, saved)
    try:
        os.replace(source, archive)
        if digest(archive) != target_hash:
            raise RuntimeError("Mission-library swap verification failed.")
        mission["enabled"] = enabled
        record["installed_files"]["009645fa.PDT"] = target_hash
        temporary = receipt_path.with_suffix(".json.new")
        temporary.write_text(json.dumps(record, indent=2))
        os.replace(temporary, receipt_path)
        deck_mode = mode if enabled else ("models" if mode == "both" else "")
        (STATE / "deck_mode.txt").write_text(deck_mode + "\n")
    except BaseException:
        if archive.exists() and digest(archive) == target_hash:
            os.replace(archive, source)
        if saved.exists():
            os.replace(saved, archive)
        raise
    print("4-player co-op " + ("enabled." if enabled else "disabled.") + " Mission library switched and verified.")


def uninstall():
    require_game_closed()
    record = receipt()
    game = Path(record["game"])
    archives = game / "MLG/disc0_rel"
    if {name: digest(archives / name) for name in NAMES} != record["installed_files"]:
        raise RuntimeError("Installed archives changed. Uninstall stopped to protect them.")
    if {name: digest(BACKUP / name) for name in NAMES} != record["original_files"]:
        raise RuntimeError("Verified original backups are missing or damaged.")
    local_dll = game / "winmm.dll"
    if local_dll.exists() and digest(local_dll) != record["runtime_sha256"]:
        raise RuntimeError("mgspw/winmm.dll changed. Uninstall stopped to protect it.")
    for name in NAMES:
        shutil.copy2(BACKUP / name, archives / name)
        if digest(archives / name) != record["original_files"][name]:
            raise RuntimeError(f"Restore verification failed: {name}")
    local_dll.unlink(missing_ok=True)
    (STATE / "deck_mode.txt").unlink(missing_ok=True)
    (STATE / "install.json").unlink()
    print("Uninstalled all Extra Ops 129 Steam Deck changes.")
    print("Remove the WINEDLLOVERRIDES launch option before starting the vanilla game.")


def restore_save():
    if steam_running():
        raise RuntimeError("Exit Steam completely before restoring saves.")
    snapshots = sorted((USER_BACKUP / "save-backups").glob("*/manifest.json"))
    if not snapshots:
        raise RuntimeError("No save backups exist.")
    for index, path in enumerate(snapshots, 1):
        print(f"{index}: {path.parent.name}")
    selected = snapshots[int(input("Choose backup number: ")) - 1].parent
    record = json.loads((selected / "manifest.json").read_text())
    game = game_dir()
    if Path(record["game"]).resolve() != game.resolve() or inventory(selected / "files") != record["files"]:
        raise RuntimeError("Save snapshot verification failed.")
    target = game.parent / "mgspw_savedata_win"
    if target.exists():
        backup_saves(game)
    temporary = target.with_name(target.name + ".restore-" + uuid.uuid4().hex)
    shutil.copytree(selected / "files", temporary)
    previous = target.with_name(target.name + ".before-restore-" + uuid.uuid4().hex)
    if target.exists():
        os.replace(target, previous)
    os.replace(temporary, target)
    if inventory(target) != record["files"]:
        raise RuntimeError("Restored save verification failed.")
    now = time.time()
    for path in target.rglob("*"):
        if path.is_file():
            os.utime(path, (now, now))
    print("Save restored and verified.")


def main():
    print("Extra Ops 129 Steam Deck Setup")
    print("1: Install models")
    print("2: Install 4-player co-op")
    print("3: Install models and 4-player co-op")
    print("4: Uninstall all")
    print("5: Uninstall all and restore save")
    print("6: Restore save only")
    print("7: Disable 4-player co-op")
    print("8: Enable 4-player co-op")
    action = input("Choose 1-8: ").strip()
    if action == "1": install("models")
    elif action == "2": install("coop")
    elif action == "3": install("both")
    elif action == "4": uninstall()
    elif action == "5": uninstall(); restore_save()
    elif action == "6": restore_save()
    elif action == "7": set_four_player(False)
    elif action == "8": set_four_player(True)
    else: raise ValueError("Choose 1, 2, 3, 4, 5, 6, 7, or 8.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        STATE.mkdir(exist_ok=True)
        (STATE / "last_error.log").write_text(str(error) + "\n")
        print(f"\nERROR: {error}")
        raise SystemExit(1)
