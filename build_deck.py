import hashlib
import os
import shutil
import subprocess
import zipfile
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    root = Path(__file__).resolve().parent
    assets = root / "assets"
    deck = root / "deck"
    work = root / ".build/deck"
    output = root / "dist/Extra-Ops-129-Steam-Deck-v1.0"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    work.mkdir(parents=True, exist_ok=True)
    vswhere = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    installation = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip()
    vcvars = Path(installation) / "VC/Auxiliary/Build/vcvars64.bat"
    dll = work / "winmm.dll"
    command_file = work / "compile.cmd"
    command_file.write_text(f'@call "{vcvars}"\n@if errorlevel 1 exit /b %errorlevel%\n@cl.exe /nologo /std:c++17 /O2 /EHsc /LD /Fo"{work / "winmm.obj"}" /Fe"{dll}" "{deck / "src/winmm_proxy.cpp"}" /link /DEF:"{deck / "src/winmm_proxy.def"}" /IMPLIB:"{work / "winmm.lib"}"\n', encoding="ascii")
    subprocess.run(["cmd.exe", "/d", "/c", str(command_file)], check=True, cwd=root)
    shutil.copytree(assets / "data", output / "data")
    shutil.copytree(assets / "licenses", output / "licenses")
    shutil.copy2(assets / "character_config.txt", output)
    shutil.copy2(assets / "Roster.txt", output)
    (output / "deck").mkdir()
    shutil.copy2(deck / "deck_setup.py", output / "deck")
    shutil.copy2(deck / "setup.sh", output / "deck")
    shutil.copy2(dll, output / "deck/winmm.dll")
    shutil.copy2(deck / "README.txt", output / "README.txt")
    shutil.copy2(root / "NETWORK_PROTOCOL.md", output / "NETWORK_PROTOCOL.md")
    (output / "source").mkdir()
    shutil.copy2(root / "src/network_protocol.py", output / "source/network_protocol.py")
    shutil.copy2(deck / "src/winmm_proxy.cpp", output / "source/winmm_proxy.cpp")
    members = sorted(path.relative_to(output) for path in output.rglob("*") if path.is_file())
    hashes = {path.as_posix(): digest(output / path) for path in members}
    (output / "SHA256SUMS.txt").write_text("".join(f"{value}  {name}\n" for name, value in hashes.items()), encoding="utf8")
    members.append(Path("SHA256SUMS.txt"))
    archive = output.parent / (output.name + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for relative in sorted(members):
            source = output / relative
            name = Path("Extra Ops 129") / relative
            info = zipfile.ZipInfo.from_file(source, name.as_posix())
            if relative.as_posix() == "deck/setup.sh":
                info.external_attr = (0o100755 << 16)
            with source.open("rb") as stream:
                package.writestr(info, stream.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None:
            raise RuntimeError("ZIP integrity check failed.")
        for name, expected in hashes.items():
            if hashlib.sha256(package.read("Extra Ops 129/" + name)).hexdigest() != expected:
                raise RuntimeError(f"ZIP verification failed: {name}")
    archive.with_suffix(".sha256").write_text(digest(archive) + "  " + archive.name + "\n", encoding="ascii")
    print(f"Built and verified: {archive}")


if __name__ == "__main__":
    main()
