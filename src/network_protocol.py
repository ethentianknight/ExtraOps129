import configparser
import ctypes as C
import ctypes.wintypes as W
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

GAME = "METAL GEAR SOLID PEACE WALKER.exe"
GAME_SHA256 = "9100e40cab8a4d96fbf6a06102e6d3a82dd2a8d951644ffbbef9f536a91f975c"
RETRY_RVA = 0x6F10F
RETRY_PATTERN = bytes.fromhex("83 f8 01 7c 17")
PAYLOAD_STATE_RVA = 0x6EB2E
PAYLOAD_STATE_PATTERN = bytes.fromhex("85 c0 74 4f 83 f8 03 0f 85 14 01 00 00")
SEND_FLAGS_RVA = 0x6EB5E
SEND_FLAGS_PATTERN = bytes.fromhex("0f b6 84 24 90 04 00 00 c1 e0 03 89 44 24 20")
FAILED_STATE_RVA = 0x6EF89
FAILED_STATE_PATTERN = bytes.fromhex("83 f8 05 0f 85 ce 01 00 00")
FAILED_STATE_REPLACEMENT = bytes.fromhex("83 f8 04 0f 82 ce 01 00 00")
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent


class ProcessEntry(C.Structure):
    _fields_ = [("size", W.DWORD), ("usage", W.DWORD), ("pid", W.DWORD), ("heap", C.c_size_t), ("module", W.DWORD), ("threads", W.DWORD), ("parent", W.DWORD), ("priority", W.LONG), ("flags", W.DWORD), ("exe", W.WCHAR * 260)]


class ModuleEntry(C.Structure):
    _fields_ = [("size", W.DWORD), ("id", W.DWORD), ("pid", W.DWORD), ("global_usage", W.DWORD), ("process_usage", W.DWORD), ("base", C.c_void_p), ("bytes", W.DWORD), ("handle", W.HMODULE), ("name", W.WCHAR * 256), ("path", W.WCHAR * 260)]


def api():
    k = C.WinDLL("kernel32", use_last_error=True)
    n = C.WinDLL("ntdll")
    k.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    k.CreateToolhelp32Snapshot.restype = W.HANDLE
    k.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(ProcessEntry)]
    k.Process32NextW.argtypes = k.Process32FirstW.argtypes
    k.Module32FirstW.argtypes = [W.HANDLE, C.POINTER(ModuleEntry)]
    k.Module32NextW.argtypes = k.Module32FirstW.argtypes
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.OpenProcess.restype = W.HANDLE
    k.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k.ReadProcessMemory.restype = W.BOOL
    k.WriteProcessMemory.argtypes = k.ReadProcessMemory.argtypes
    k.WriteProcessMemory.restype = W.BOOL
    k.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k.VirtualAllocEx.restype = C.c_void_p
    k.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
    k.VirtualProtectEx.restype = W.BOOL
    k.VirtualFreeEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD]
    k.VirtualFreeEx.restype = W.BOOL
    k.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
    k.FlushInstructionCache.restype = W.BOOL
    k.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    k.CreateRemoteThread.restype = W.HANDLE
    k.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    k.GetExitCodeThread.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    k.CloseHandle.argtypes = [W.HANDLE]
    n.NtSuspendProcess.argtypes = [W.HANDLE]
    n.NtSuspendProcess.restype = C.c_long
    n.NtResumeProcess.argtypes = [W.HANDLE]
    n.NtResumeProcess.restype = C.c_long
    return k, n


def find_game(k):
    snap = k.CreateToolhelp32Snapshot(2, 0)
    if snap == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        item = ProcessEntry()
        item.size = C.sizeof(item)
        ok = k.Process32FirstW(snap, C.byref(item))
        while ok:
            if item.exe == GAME:
                return item.pid
            ok = k.Process32NextW(snap, C.byref(item))
    finally:
        k.CloseHandle(snap)


def modules(k, pid):
    snap = k.CreateToolhelp32Snapshot(0x18, pid)
    if snap == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    found = {}
    try:
        item = ModuleEntry()
        item.size = C.sizeof(item)
        ok = k.Module32FirstW(snap, C.byref(item))
        while ok:
            found[item.name.lower()] = (int(item.base), Path(item.path))
            ok = k.Module32NextW(snap, C.byref(item))
    finally:
        k.CloseHandle(snap)
    return found


def export_rvas(path, wanted):
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    coff = pe + 4
    section_count = struct.unpack_from("<H", data, coff + 2)[0]
    optional_size = struct.unpack_from("<H", data, coff + 16)[0]
    optional = coff + 20
    if struct.unpack_from("<H", data, optional)[0] != 0x20B:
        raise RuntimeError("Expected a 64-bit steam_api64.dll")
    export_rva = struct.unpack_from("<I", data, optional + 112)[0]
    sections = []
    for index in range(section_count):
        offset = optional + optional_size + index * 40
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from("<IIII", data, offset + 8)
        sections.append((virtual_address, max(virtual_size, raw_size), raw_offset))

    def file_offset(rva):
        for virtual_address, size, raw_offset in sections:
            if virtual_address <= rva < virtual_address + size:
                return raw_offset + rva - virtual_address
        raise RuntimeError(f"RVA {rva:#x} is outside the image")

    directory = file_offset(export_rva)
    count = struct.unpack_from("<I", data, directory + 24)[0]
    functions, names, ordinals = struct.unpack_from("<III", data, directory + 28)
    result = {}
    for index in range(count):
        name_rva = struct.unpack_from("<I", data, file_offset(names) + index * 4)[0]
        name_offset = file_offset(name_rva)
        end = data.index(0, name_offset)
        name = data[name_offset:end].decode("ascii")
        if name in wanted:
            ordinal = struct.unpack_from("<H", data, file_offset(ordinals) + index * 2)[0]
            result[name] = struct.unpack_from("<I", data, file_offset(functions) + ordinal * 4)[0]
    missing = wanted - result.keys()
    if missing:
        raise RuntimeError("Missing Steam API exports: " + ", ".join(sorted(missing)))
    return result


def setting_stub(accessor, setter, settings):
    out = bytearray(bytes.fromhex("53 48 83 ec 20 31 db"))
    branches = []
    for option, value in settings:
        out.extend(bytes.fromhex("48 b8"))
        out.extend(struct.pack("<Q", accessor))
        out.extend(bytes.fromhex("ff d0 48 85 c0 0f 84"))
        branches.append(len(out))
        out.extend(b"\0" * 4)
        out.extend(bytes.fromhex("48 89 c1 ba"))
        out.extend(struct.pack("<I", option))
        out.extend(bytes.fromhex("41 b8"))
        out.extend(struct.pack("<I", value))
        out.extend(bytes.fromhex("48 b8"))
        out.extend(struct.pack("<Q", setter))
        out.extend(bytes.fromhex("ff d0 84 c0 0f 84"))
        branches.append(len(out))
        out.extend(b"\0" * 4)
        out.extend(bytes.fromhex("ff c3"))
    end = len(out)
    out.extend(bytes.fromhex("89 d8 48 83 c4 20 5b c3"))
    for location in branches:
        struct.pack_into("<i", out, location, end - location - 4)
    return bytes(out)


def payload_state_stub(game_base):
    out = bytearray()
    labels = {}
    branches = []

    def emit(value):
        out.extend(bytes.fromhex(value))

    def branch(opcode, label):
        emit(opcode)
        branches.append((len(out), label))
        out.append(0)

    def jump(address):
        emit("49 bb")
        out.extend(struct.pack("<Q", address))
        emit("41 ff e3")

    emit("83 f8 03")
    branch("74", "send")
    emit("80 bc 24 90 04 00 00 00")
    branch("75", "send")
    emit("85 c0")
    branch("74", "initialize")
    branch("eb", "success")
    labels["send"] = len(out)
    jump(game_base + 0x6EB3B)
    labels["initialize"] = len(out)
    jump(game_base + 0x6EB81)
    labels["success"] = len(out)
    jump(game_base + 0x6EC4F)
    for location, label in branches:
        displacement = labels[label] - location - 1
        if not -128 <= displacement <= 127:
            raise RuntimeError("Payload-state stub branch is out of range")
        out[location] = displacement & 0xFF
    return bytes(out)


def send_flags_stub(game_base):
    out = bytearray(bytes.fromhex("0f b6 84 24 90 04 00 00 c1 e0 03 85 c0 74 03 83 c8 20 89 44 24 20 49 bb"))
    out.extend(struct.pack("<Q", game_base + 0x6EB6D))
    out.extend(bytes.fromhex("41 ff e3"))
    return bytes(out)


def load_config():
    path = ROOT / "network_protocol.ini"
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    section = parser["Connection"] if parser.has_section("Connection") else {}
    retry = int(section.get("retry_attempts", 5))
    initial = int(section.get("initial_timeout_ms", 60000))
    connected = int(section.get("connected_timeout_ms", 60000))
    if not 2 <= retry <= 127:
        raise RuntimeError("retry_attempts must be from 2 through 127")
    if not 5000 <= initial <= 300000 or not 5000 <= connected <= 300000:
        raise RuntimeError("timeout values must be from 5000 through 300000 milliseconds")
    return retry, initial, connected


def read_memory(k, process, address, size):
    buffer = C.create_string_buffer(size)
    read = C.c_size_t()
    if not k.ReadProcessMemory(process, address, buffer, size, C.byref(read)) or read.value != size:
        raise C.WinError(C.get_last_error())
    return buffer.raw


def write_memory(k, process, address, data):
    buffer = C.create_string_buffer(data)
    written = C.c_size_t()
    if not k.WriteProcessMemory(process, address, buffer, len(data), C.byref(written)) or written.value != len(data):
        raise C.WinError(C.get_last_error())


def set_steam_timeouts(k, process, steam_base, steam_path, initial, connected):
    names = {"SteamAPI_SteamNetworkingUtils_SteamAPI_v004", "SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueInt32"}
    exports = export_rvas(steam_path, names)
    code = setting_stub(
        steam_base + exports["SteamAPI_SteamNetworkingUtils_SteamAPI_v004"],
        steam_base + exports["SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueInt32"],
        [(24, initial), (25, connected)],
    )
    allocation = k.VirtualAllocEx(process, None, len(code), 0x3000, 0x04)
    if not allocation:
        raise C.WinError(C.get_last_error())
    thread = None
    try:
        write_memory(k, process, allocation, code)
        old = W.DWORD()
        if not k.VirtualProtectEx(process, allocation, len(code), 0x20, C.byref(old)):
            raise C.WinError(C.get_last_error())
        if not k.FlushInstructionCache(process, allocation, len(code)):
            raise C.WinError(C.get_last_error())
        thread_id = W.DWORD()
        thread = k.CreateRemoteThread(process, None, 0, allocation, None, 0, C.byref(thread_id))
        if not thread:
            raise C.WinError(C.get_last_error())
        if k.WaitForSingleObject(thread, 10000) != 0:
            raise RuntimeError("Timed out while configuring Steam networking")
        exit_code = W.DWORD()
        if not k.GetExitCodeThread(thread, C.byref(exit_code)):
            raise C.WinError(C.get_last_error())
        if exit_code.value != 2:
            raise RuntimeError(f"Steam accepted only {exit_code.value} of 2 timeout settings")
    finally:
        if thread:
            k.CloseHandle(thread)
        k.VirtualFreeEx(process, allocation, 0, 0x8000)


def apply(pid, module_map, retry, initial, connected):
    k, n = api()
    game_base, game_path = module_map[GAME.lower()]
    steam_base, steam_path = module_map["steam_api64.dll"]
    if hashlib.sha256(game_path.read_bytes()).hexdigest() != GAME_SHA256:
        raise RuntimeError("Unsupported Peace Walker executable")
    process = k.OpenProcess(0x1F0FFF, False, pid)
    if not process:
        raise C.WinError(C.get_last_error())
    payload_code = payload_state_stub(game_base)
    payload_allocation = k.VirtualAllocEx(process, None, len(payload_code), 0x3000, 0x04)
    if not payload_allocation:
        k.CloseHandle(process)
        raise C.WinError(C.get_last_error())
    flags_code = send_flags_stub(game_base)
    flags_allocation = k.VirtualAllocEx(process, None, len(flags_code), 0x3000, 0x04)
    if not flags_allocation:
        k.VirtualFreeEx(process, payload_allocation, 0, 0x8000)
        k.CloseHandle(process)
        raise C.WinError(C.get_last_error())
    payload_hook = b"\x49\xbb" + struct.pack("<Q", payload_allocation) + b"\x41\xff\xe3"
    flags_hook = b"\x49\xbb" + struct.pack("<Q", flags_allocation) + b"\x41\xff\xe3\x90\x90"
    patches = [
        (game_base + RETRY_RVA, RETRY_PATTERN, RETRY_PATTERN[:2] + bytes([retry]) + RETRY_PATTERN[3:]),
        (game_base + PAYLOAD_STATE_RVA, PAYLOAD_STATE_PATTERN, payload_hook),
        (game_base + SEND_FLAGS_RVA, SEND_FLAGS_PATTERN, flags_hook),
        (game_base + FAILED_STATE_RVA, FAILED_STATE_PATTERN, FAILED_STATE_REPLACEMENT),
    ]
    suspended = False
    changed = []
    applied = False
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if all(read_memory(k, process, address, len(original)) in (original, replacement) for address, original, replacement in patches):
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("Loaded network code did not match the supported game build")
        write_memory(k, process, payload_allocation, payload_code)
        old = W.DWORD()
        if not k.VirtualProtectEx(process, payload_allocation, len(payload_code), 0x20, C.byref(old)):
            raise C.WinError(C.get_last_error())
        if not k.FlushInstructionCache(process, payload_allocation, len(payload_code)):
            raise C.WinError(C.get_last_error())
        write_memory(k, process, flags_allocation, flags_code)
        old = W.DWORD()
        if not k.VirtualProtectEx(process, flags_allocation, len(flags_code), 0x20, C.byref(old)):
            raise C.WinError(C.get_last_error())
        if not k.FlushInstructionCache(process, flags_allocation, len(flags_code)):
            raise C.WinError(C.get_last_error())
        if n.NtSuspendProcess(process) != 0:
            raise RuntimeError("Could not suspend Peace Walker for the connection update")
        suspended = True
        for address, original, replacement in patches:
            current = read_memory(k, process, address, len(original))
            if current == replacement:
                continue
            if current != original:
                raise RuntimeError("Network code changed during patch preparation")
            old = W.DWORD()
            if not k.VirtualProtectEx(process, address, len(original), 0x40, C.byref(old)):
                raise C.WinError(C.get_last_error())
            changed.append((address, original, old.value))
            try:
                write_memory(k, process, address, replacement)
                if read_memory(k, process, address, len(replacement)) != replacement:
                    raise RuntimeError("Connection update verification failed")
            finally:
                restored = W.DWORD()
                k.VirtualProtectEx(process, address, len(original), old.value, C.byref(restored))
            k.FlushInstructionCache(process, address, len(original))
        if n.NtResumeProcess(process) != 0:
            raise RuntimeError("Could not resume Peace Walker")
        suspended = False
        set_steam_timeouts(k, process, steam_base, steam_path, initial, connected)
        record = {"pid": pid, "retry_attempts": retry, "initial_timeout_ms": initial, "connected_timeout_ms": connected, "queue_reliable_payload_until_connected": True, "auto_restart_broken_session_for_reliable_sends": True, "recover_closed_and_failed_sessions": True, "payload_stub": hex(payload_allocation), "flags_stub": hex(flags_allocation), "routing": "Steam default", "time": time.time()}
        (ROOT / "network_protocol_applied.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        applied = True
        return record
    except BaseException:
        if changed:
            if not suspended and n.NtSuspendProcess(process) == 0:
                suspended = True
            if suspended:
                for address, original, protection in reversed(changed):
                    old = W.DWORD()
                    if not k.VirtualProtectEx(process, address, len(original), 0x40, C.byref(old)):
                        continue
                    write_memory(k, process, address, original)
                    restored = W.DWORD()
                    k.VirtualProtectEx(process, address, len(original), protection, C.byref(restored))
                    k.FlushInstructionCache(process, address, len(original))
        raise
    finally:
        if suspended:
            n.NtResumeProcess(process)
        if not applied:
            k.VirtualFreeEx(process, payload_allocation, 0, 0x8000)
            k.VirtualFreeEx(process, flags_allocation, 0, 0x8000)
        k.CloseHandle(process)


def self_test(game_dir):
    game_path = game_dir / GAME
    steam_path = game_dir / "steam_api64.dll"
    if hashlib.sha256(game_path.read_bytes()).hexdigest() != GAME_SHA256:
        raise RuntimeError("Unsupported Peace Walker executable")
    names = {"SteamAPI_SteamNetworkingUtils_SteamAPI_v004", "SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueInt32"}
    exports = export_rvas(steam_path, names)
    code = setting_stub(0x1111222233334444, 0x5555666677778888, [(24, 60000), (25, 60000)])
    payload_code = payload_state_stub(0x140000000)
    flags_code = send_flags_stub(0x140000000)
    if code[:7] != bytes.fromhex("53 48 83 ec 20 31 db") or code[-8:] != bytes.fromhex("89 d8 48 83 c4 20 5b c3"):
        raise RuntimeError("Generated x64 code failed verification")
    if len(PAYLOAD_STATE_PATTERN) != 13 or len(SEND_FLAGS_PATTERN) != 15 or len(FAILED_STATE_PATTERN) != len(FAILED_STATE_REPLACEMENT) or len(payload_code) != 60 or len(flags_code) != 35:
        raise RuntimeError("Connection patches change instruction length")
    return {"game_sha256": GAME_SHA256, "patches": {"retry": hex(RETRY_RVA), "queue_reliable_until_connected": hex(PAYLOAD_STATE_RVA), "auto_restart_reliable": hex(SEND_FLAGS_RVA), "recover_failed_sessions": hex(FAILED_STATE_RVA)}, "steam_exports": {name: hex(rva) for name, rva in exports.items()}, "timeout_stub_bytes": len(code), "payload_stub_bytes": len(payload_code), "flags_stub_bytes": len(flags_code)}


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        print(json.dumps(self_test(Path(sys.argv[2])), indent=2))
        return
    retry, initial, connected = load_config()
    k, _ = api()
    print("Patch PW Networking Protocol\nWaiting for Peace Walker...", flush=True)
    while True:
        pid = find_game(k)
        if pid:
            module_map = modules(k, pid)
            if GAME.lower() in module_map and "steam_api64.dll" in module_map:
                break
        time.sleep(0.25)
    record = apply(pid, module_map, retry, initial, connected)
    print("Connection stability patch applied for this game run.", flush=True)
    print(json.dumps(record, indent=2), flush=True)
    input("Press Enter to close...")


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        print(f"ERROR: {error}", flush=True)
        input("Press Enter to close...")
        raise SystemExit(1)
