import ctypes as C, ctypes.wintypes as W, hashlib, json, struct, time, sys
from pathlib import Path
R=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
D=R
HOOK=0x1f8277
expected_tail=bytes.fromhex('443bf6418bc6bb01000000410f4dc4')

def stub_code(base, return_address=None):
 out=bytearray();labels={};fixups=[]
 def emit(data):out.extend(bytes.fromhex(data))
 def branch(op,label):
  emit(op);fixups.append((len(out),label));out.append(0)
 emit('48 b8');out.extend(struct.pack('<Q',base+0xea4860))
 emit('48 8b 00 48 85 c0');branch('74','original')
 emit('81 78 34 72 5f 6e 65');branch('75','original')
 emit('81 78 38 74 5f 63 6f');branch('74','coop')
 emit('81 78 38 74 5f 70 72');branch('75','original')
 emit('81 78 3c 69 73 6f 6e');branch('74','accepted');branch('eb','original')
 labels['coop']=len(out);emit('81 78 3c 6f 70 32 00');branch('75','original')
 labels['accepted']=len(out);emit('83 fe 02');branch('75','original')
 emit('41 83 fe 02');branch('72','original')
 emit('41 83 fe 03');branch('77','original')
 emit('44 89 f0 83 e0 01 bb 01 00 00 00');branch('eb','return')
 labels['original']=len(out);out.extend(expected_tail)
 labels['return']=len(out);emit('ff 25 00 00 00 00')
 out.extend(struct.pack('<Q',return_address if return_address is not None else base+HOOK+15))
 for pos,label in fixups:
  delta=labels[label]-pos-1
  assert -128<=delta<=127
  out[pos]=delta&255
 return bytes(out)

def apply(pid,base):
 k=C.WinDLL('kernel32',use_last_error=True);nt=C.WinDLL('ntdll')
 k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenProcess.restype=W.HANDLE
 k.ReadProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)];k.ReadProcessMemory.restype=W.BOOL
 k.WriteProcessMemory.argtypes=k.ReadProcessMemory.argtypes;k.WriteProcessMemory.restype=W.BOOL
 k.VirtualAllocEx.argtypes=[W.HANDLE,C.c_void_p,C.c_size_t,W.DWORD,W.DWORD];k.VirtualAllocEx.restype=C.c_void_p
 k.VirtualProtectEx.argtypes=[W.HANDLE,C.c_void_p,C.c_size_t,W.DWORD,C.POINTER(W.DWORD)];k.VirtualProtectEx.restype=W.BOOL
 k.FlushInstructionCache.argtypes=[W.HANDLE,C.c_void_p,C.c_size_t];k.FlushInstructionCache.restype=W.BOOL
 k.CloseHandle.argtypes=[W.HANDLE]
 k.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
 nt.NtSuspendProcess.argtypes=[W.HANDLE];nt.NtSuspendProcess.restype=C.c_long
 nt.NtResumeProcess.argtypes=[W.HANDLE];nt.NtResumeProcess.restype=C.c_long
 nt.NtGetNextThread.argtypes=[W.HANDLE,W.HANDLE,W.DWORD,W.DWORD,W.DWORD,C.POINTER(W.HANDLE)];nt.NtGetNextThread.restype=C.c_long
 k.GetThreadContext.argtypes=[W.HANDLE,C.c_void_p];k.GetThreadContext.restype=W.BOOL
 k.GetExitCodeThread.argtypes=[W.HANDLE,C.POINTER(W.DWORD)];k.GetExitCodeThread.restype=W.BOOL
 k.GetThreadId.argtypes=[W.HANDLE];k.GetThreadId.restype=W.DWORD
 k.VirtualFreeEx.argtypes=[W.HANDLE,C.c_void_p,C.c_size_t,W.DWORD];k.VirtualFreeEx.restype=W.BOOL
 h=k.OpenProcess(0x1f0fff,False,pid)
 if not h:raise C.WinError(C.get_last_error())
 def read(addr,n):
  buf=C.create_string_buffer(n);got=C.c_size_t()
  if not k.ReadProcessMemory(h,addr,buf,n,C.byref(got)) or got.value!=n:raise C.WinError(C.get_last_error())
  return buf.raw
 def write(addr,data):
  buf=C.create_string_buffer(data);got=C.c_size_t()
  if not k.WriteProcessMemory(h,addr,buf,len(data),C.byref(got)) or got.value!=len(data):raise C.WinError(C.get_last_error())
  assert read(addr,len(data))==data
 def protect(addr,n,mode):
  old=W.DWORD()
  if not k.VirtualProtectEx(h,addr,n,mode,C.byref(old)):raise C.WinError(C.get_last_error())
  return old.value
 suspended=False;written=[];allocation=None;applied=False
 try:
  path=C.create_unicode_buffer(32768);length=W.DWORD(len(path))
  if not k.QueryFullProcessImageNameW(h,0,path,C.byref(length)):raise C.WinError(C.get_last_error())
  exe=Path(path.value)
  assert exe.name=='METAL GEAR SOLID PEACE WALKER.exe',str(exe)
  assert hashlib.sha256(exe.read_bytes()).hexdigest()=='9100e40cab8a4d96fbf6a06102e6d3a82dd2a8d951644ffbbef9f536a91f975c','Unsupported game build'
  captured=bytes.fromhex('440fb6d1488d05a521240149c1e2054c03d04885d27407410fb7026689024d85c07409410fb74202664189004d85c97409410fb7420466418901488b4424284885c07409410f284210660f7f00c3')
  deadline=time.monotonic()+120
  while time.monotonic()<deadline:
   if read(base+HOOK,15)==expected_tail and read(base+0x1f8810,0x4e)==captured:break
   time.sleep(.25)
  else:raise RuntimeError('Loaded code did not match the verified game build')
  code=stub_code(base);allocation=k.VirtualAllocEx(h,None,len(code),0x3000,0x04)
  if not allocation:raise C.WinError(C.get_last_error())
  write(allocation,code);protect(allocation,len(code),0x20)
  assert k.FlushInstructionCache(h,allocation,len(code))

  if nt.NtSuspendProcess(h)!=0:raise RuntimeError('Could not suspend game for atomic patch')
  suspended=True
  previous=W.HANDLE()
  try:
   while True:
    following=W.HANDLE()
    status=nt.NtGetNextThread(h,previous,0x48,0,0,C.byref(following))
    if previous:k.CloseHandle(previous);previous=W.HANDLE()
    if status & 0xffffffff==0x8000001a:break
    if status!=0:raise RuntimeError(f'Thread enumeration failed: {status}')
    previous=following
    exit_code=W.DWORD()
    if not k.GetExitCodeThread(previous,C.byref(exit_code)):raise C.WinError(C.get_last_error())
    if exit_code.value!=259:continue
    context=C.create_string_buffer(1248);aligned=(C.addressof(context)+15)&~15
    C.c_uint32.from_address(aligned+48).value=0x100001
    if not k.GetThreadContext(previous,aligned):
     error=C.get_last_error()


     if k.GetExitCodeThread(previous,C.byref(exit_code)) and exit_code.value!=259:continue
     print(f'Thread {k.GetThreadId(previous)} context unavailable (Windows {error}); no patch applied.',flush=True)
     raise C.WinError(error)
    rip=C.c_uint64.from_address(aligned+248).value
    assert not base+HOOK<rip<base+HOOK+15,'Thread inside patch site; retry the helper'
  finally:
   if previous:k.CloseHandle(previous)
  assert read(base+HOOK,15)==expected_tail
  patches=[(base+HOOK,b'\x48\xb8'+struct.pack('<Q',allocation)+b'\xff\xe0'+b'\x90'*3)]
  try:
   for addr,data in patches:
    old=read(addr,len(data));mode=protect(addr,len(data),0x40)
    written.append((addr,old,mode))
    write(addr,data);protect(addr,len(data),mode)
   assert k.FlushInstructionCache(h,base+HOOK,15)
  except BaseException:
   for addr,old,mode in reversed(written):
    protect(addr,len(old),0x40);write(addr,old);protect(addr,len(old),mode)
   k.FlushInstructionCache(h,base+HOOK,15)
   raise
  (D/'spawn_runtime_applied.json').write_text(json.dumps({'pid':pid,'base':hex(base),'stub':hex(allocation),'scope':'r_net_coop2/r_net_prison two-entry placement list; indices 2 and 3 map to 0 and 1','verified':True,'time':time.time()},indent=2))
  applied=True
  print('APPLIED: placement-index fallback. Restart the game to remove it.',flush=True)
 finally:
  if suspended:
   status=nt.NtResumeProcess(h)
   if status!=0:print('ERROR: game resume failed:',status,flush=True)
  if allocation and not applied and not written:k.VirtualFreeEx(h,allocation,0,0x8000)
  k.CloseHandle(h)


if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser(description='Experimental placement-index fallback; does not change save files.')
 parser.add_argument('--pid',type=int,required=True)
 parser.add_argument('--base',type=lambda s:int(s,0),required=True)
 args=parser.parse_args()
 apply(args.pid,args.base)
