import argparse, ctypes as C, ctypes.wintypes as W, hashlib, json, struct, time
from pathlib import Path
import sys
R = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
DATA = R / 'data'
D = R / 'state'
D.mkdir(exist_ok=True)

def read_manifest():
    from eo129 import game_dir
    unified = json.loads((DATA / 'manifest.json').read_text())
    receipt = json.loads((D / 'install.json').read_text())
    mode = receipt['mode']
    result = {'exe_sha256': unified['exe_sha256'], 'files': {name: {'patched_sha256': value} for name, value in unified['modes'][mode]['files'].items()}}
    result['game_dir'] = str(game_dir() / 'MLG/disc0_rel')
    return result
from character_config import load_config, CONFIG_PATH, SLOTS
config = load_config(json.loads((DATA / 'runtime_config.json').read_text()))
HOOK = 873582
MAP = 18916496
TAIL = MAP + (96 - len(config['resource_map'])) * 8
MAP_BYTES = len(config['resource_map']) * 8
expected_tail = bytes.fromhex('33 c0 48 83 c4 20 5b c3 cc cc cc cc')
original_pair = struct.pack('<2I', 4425344, 3503788)

def stub_code(base):
    out = bytearray(b'I\xba' + struct.pack('<Q', base + TAIL))
    for i, (ident, packed) in enumerate(config['resource_map']):
        out += b'H\xb8' + struct.pack('<II', ident, packed)
        out += b'I\x89\x82' + struct.pack('<I', i * 8)
    out += expected_tail[:8]
    return bytes(out)

def validate():
    if len(config['resource_map']) != 18 or len({p[0] for p in config['resource_map']}) != 18:
        raise ValueError('Invalid model resource list')
    pairs = [(a['gender'], a['outfit']) for a in config['assignments']]
    if pairs[:10] != [(1, 3), (1, 16), (1, 24), (2, 27), (2, 14), (2, 15), (2, 25), (2, 17), (2, 18), (2, 19)]:
        raise ValueError('Invalid base roster')
    if len(pairs) != len(set(pairs)) or not set(pairs[10:]) <= {(s[0], s[1]) for s in SLOTS.values()}:
        raise ValueError('Conflicting outfit choices')
    print('Character configuration loaded.', flush=True)
    for key, value in config['user_selections'].items():
        print(f'  {key}: {value}', flush=True)

def file_identity(path):
    s = path.stat()
    return [s.st_size, s.st_mtime_ns, s.st_ctime_ns]

def preflight():
    manifest = read_manifest()
    verified = {}
    paths = {Path(manifest['game_dir']) / name: record['patched_sha256'] for name, record in manifest['files'].items()}
    paths[Path(manifest['game_dir']).parents[1] / 'METAL GEAR SOLID PEACE WALKER.exe'] = config['exe_sha256']
    for path, expected in paths.items():
        before = file_identity(path)
        with path.open('rb') as f:
            actual = hashlib.file_digest(f, 'sha256').hexdigest()
        assert actual == expected, f'Installed file does not match variant build: {path.name}'
        assert file_identity(path) == before, 'File changed during verification'
        verified[str(path)] = {'sha256': actual, 'identity': before}
    (D / 'preflight.json').write_text(json.dumps({'files': verified, 'time': time.time()}, indent=2))
    print('Pre-launch archive and executable SHA-256 verification passed.', flush=True)

def apply(pid, base):
    k = C.WinDLL('kernel32', use_last_error=True)
    nt = C.WinDLL('ntdll')
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
    k.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
    k.FlushInstructionCache.restype = W.BOOL
    k.CloseHandle.argtypes = [W.HANDLE]
    k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    nt.NtSuspendProcess.argtypes = [W.HANDLE]
    nt.NtSuspendProcess.restype = C.c_long
    nt.NtResumeProcess.argtypes = [W.HANDLE]
    nt.NtResumeProcess.restype = C.c_long
    nt.NtGetNextThread.argtypes = [W.HANDLE, W.HANDLE, W.DWORD, W.DWORD, W.DWORD, C.POINTER(W.HANDLE)]
    nt.NtGetNextThread.restype = C.c_long
    k.GetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
    k.GetThreadContext.restype = W.BOOL
    k.GetExitCodeThread.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    k.GetExitCodeThread.restype = W.BOOL
    k.GetThreadId.argtypes = [W.HANDLE]
    k.GetThreadId.restype = W.DWORD
    k.VirtualFreeEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD]
    k.VirtualFreeEx.restype = W.BOOL
    h = k.OpenProcess(2035711, False, pid)
    if not h:
        raise C.WinError(C.get_last_error())

    def read(addr, n):
        buf = C.create_string_buffer(n)
        got = C.c_size_t()
        if not k.ReadProcessMemory(h, addr, buf, n, C.byref(got)) or got.value != n:
            raise C.WinError(C.get_last_error())
        return buf.raw

    def write(addr, data):
        buf = C.create_string_buffer(data)
        got = C.c_size_t()
        if not k.WriteProcessMemory(h, addr, buf, len(data), C.byref(got)) or got.value != len(data):
            raise C.WinError(C.get_last_error())
        assert read(addr, len(data)) == data

    def protect(addr, n, mode):
        old = W.DWORD()
        if not k.VirtualProtectEx(h, addr, n, mode, C.byref(old)):
            raise C.WinError(C.get_last_error())
        return old.value
    suspended = False
    written = []
    allocation = None
    applied = False
    try:
        path = C.create_unicode_buffer(32768)
        length = W.DWORD(len(path))
        if not k.QueryFullProcessImageNameW(h, 0, path, C.byref(length)):
            raise C.WinError(C.get_last_error())
        exe = Path(path.value)
        assert exe.name == 'METAL GEAR SOLID PEACE WALKER.exe', str(exe)
        manifest = read_manifest()
        receipt = json.loads((D / 'preflight.json').read_text())
        paths = {Path(manifest['game_dir']) / name: record['patched_sha256'] for name, record in manifest['files'].items()}
        paths[exe] = config['exe_sha256']
        for path, expected in paths.items():
            record = receipt['files'][str(path)]
            assert record['sha256'] == expected and file_identity(path) == record['identity'], f'File changed since pre-launch verification: {path.name}'
        captured = (DATA / 'selector.bin').read_bytes()
        assert len(captured) == 124
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if read(base + HOOK, 12) == expected_tail and read(base + 4289552, 124) == captured:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError('Loaded code did not match the verified game build')
        code = stub_code(base)
        allocation = k.VirtualAllocEx(h, None, len(code), 12288, 4)
        if not allocation:
            raise C.WinError(C.get_last_error())
        write(allocation, code)
        protect(allocation, len(code), 32)
        assert k.FlushInstructionCache(h, allocation, len(code))
        if nt.NtSuspendProcess(h) != 0:
            raise RuntimeError('Could not suspend game for atomic patch')
        suspended = True
        previous = W.HANDLE()
        try:
            while True:
                following = W.HANDLE()
                status = nt.NtGetNextThread(h, previous, 72, 0, 0, C.byref(following))
                if previous:
                    k.CloseHandle(previous)
                    previous = W.HANDLE()
                if status & 4294967295 == 2147483674:
                    break
                if status != 0:
                    raise RuntimeError(f'Thread enumeration failed: {status}')
                previous = following
                exit_code = W.DWORD()
                if not k.GetExitCodeThread(previous, C.byref(exit_code)):
                    raise C.WinError(C.get_last_error())
                if exit_code.value != 259:
                    continue
                context = C.create_string_buffer(1248)
                aligned = C.addressof(context) + 15 & ~15
                C.c_uint32.from_address(aligned + 48).value = 1048577
                if not k.GetThreadContext(previous, aligned):
                    error = C.get_last_error()
                    if k.GetExitCodeThread(previous, C.byref(exit_code)) and exit_code.value != 259:
                        continue
                    print(f'Thread {k.GetThreadId(previous)} context unavailable (Windows {error}); no patch applied.', flush=True)
                    raise C.WinError(error)
                rip = C.c_uint64.from_address(aligned + 248).value
                assert not base + HOOK < rip < base + HOOK + 12, 'Thread inside patch site; retry the helper'
        finally:
            if previous:
                k.CloseHandle(previous)
        assert read(base + HOOK, 12) == expected_tail
        assert read(base + TAIL, MAP_BYTES) == bytes(MAP_BYTES), 'Reserved mapping slots are already in use'
        patches = [(base + HOOK, b'H\xb8' + struct.pack('<Q', allocation) + b'\xff\xe0')]
        for a in config['assignments']:
            addr = base + 16345920 + a['outfit'] * 872 + a['gender'] * 8
            expected = struct.pack('<2I', *a['original_models'])
            assert read(addr, 8) == expected, 'Unexpected outfit model pair'
            patches.append((addr, struct.pack('<2I', *a['models'])))
        patches.append((base + TAIL, b''.join((struct.pack('<2I', *pair) for pair in config['resource_map']))))
        try:
            for addr, data in patches:
                old = read(addr, len(data))
                mode = protect(addr, len(data), 64)
                written.append((addr, old, mode))
                write(addr, data)
                protect(addr, len(data), mode)
            assert k.FlushInstructionCache(h, base + HOOK, 12)
        except BaseException:
            for addr, old, mode in reversed(written):
                protect(addr, len(old), 64)
                write(addr, old)
                protect(addr, len(old), mode)
            k.FlushInstructionCache(h, base + HOOK, 12)
            raise
        (D / 'runtime_applied.json').write_text(json.dumps({'pid': pid, 'base': hex(base), 'stub': hex(allocation), 'assignments': config['assignments'], 'resource_map': config['resource_map'], 'verified': True, 'time': time.time()}, indent=2))
        applied = True
        print(f"APPLIED: roster and {len(config['assignments']) - 10} configured outfit overrides; readback verified.", flush=True)
    finally:
        if suspended:
            status = nt.NtResumeProcess(h)
            if status != 0:
                print('ERROR: game resume failed:', status, flush=True)
        if allocation and (not applied) and (not written):
            k.VirtualFreeEx(h, allocation, 0, 32768)
        k.CloseHandle(h)
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--pid', type=int)
    parser.add_argument('--base', type=lambda s: int(s, 0))
    args = parser.parse_args()
    validate()
    if args.preflight:
        preflight()
    elif not args.check:
        assert args.pid and args.base, 'Provide the actual game PID and image base'
        for attempt in range(6):
            try:
                apply(args.pid, args.base)
                break
            except OSError as exc:
                if exc.winerror != 31 or attempt == 5:
                    raise
                print('Startup thread changed; retrying the complete verified patch in 3 seconds.', flush=True)
                time.sleep(3)
