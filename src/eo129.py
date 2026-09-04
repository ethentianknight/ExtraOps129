import ctypes as C,ctypes.wintypes as W,gzip,hashlib,json,os,shutil,struct,subprocess,sys,time,traceback,zlib
from pathlib import Path
from save_backup import backup_saves,restore_saves
ROOT=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
DATA=ROOT/'data';STATE=ROOT/'state';BACKUP=ROOT/'backups';NAMES=('002aba34.DAT','002aba34.KEY','009645fa.PDT')

def digest(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def game_dir():
 for path in (ROOT.parent/'mgspw',ROOT.parent):
  if (path/'METAL GEAR SOLID PEACE WALKER.exe').is_file() and (path/'MLG/disc0_rel').is_dir():return path
 raise RuntimeError('Put this complete Extra Ops 129 folder beside the mgspw folder in the MGS_PW Steam directory.')

def manifest():return json.loads((DATA/'manifest.json').read_text())

def installation_receipt():
 path=STATE/'install.json'
 if not path.is_file():raise RuntimeError('No installation record was found. Run Setup Extra Ops 129.cmd from this same folder and choose install option 1, 2, or 3 before Play.')
 try:return json.loads(path.read_text())
 except (OSError,json.JSONDecodeError) as error:raise RuntimeError('The installation record is unreadable. Keep this folder in its original location and reinstall from verified vanilla files.') from error

def processes():
 k=C.WinDLL('kernel32',use_last_error=True)
 class Entry(C.Structure):_fields_=[('size',W.DWORD),('usage',W.DWORD),('pid',W.DWORD),('heap',C.c_size_t),('module',W.DWORD),('threads',W.DWORD),('parent',W.DWORD),('priority',W.LONG),('flags',W.DWORD),('exe',W.WCHAR*260)]
 k.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD];k.CreateToolhelp32Snapshot.restype=W.HANDLE;k.Process32FirstW.argtypes=[W.HANDLE,C.POINTER(Entry)];k.Process32NextW.argtypes=k.Process32FirstW.argtypes;k.CloseHandle.argtypes=[W.HANDLE]
 snap=k.CreateToolhelp32Snapshot(2,0)
 if snap==C.c_void_p(-1).value:raise C.WinError(C.get_last_error())
 found=[]
 try:
  entry=Entry();entry.size=C.sizeof(entry);ok=k.Process32FirstW(snap,C.byref(entry))
  while ok:
   if entry.exe=='METAL GEAR SOLID PEACE WALKER.exe':found.append(entry.pid)
   ok=k.Process32NextW(snap,C.byref(entry))
 finally:k.CloseHandle(snap)
 return found

def module_base(pid):
 k=C.WinDLL('kernel32',use_last_error=True)
 class Module(C.Structure):_fields_=[('size',W.DWORD),('id',W.DWORD),('pid',W.DWORD),('global_usage',W.DWORD),('process_usage',W.DWORD),('base',C.c_void_p),('bytes',W.DWORD),('handle',W.HMODULE),('name',W.WCHAR*256),('path',W.WCHAR*260)]
 k.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD];k.CreateToolhelp32Snapshot.restype=W.HANDLE;k.Module32FirstW.argtypes=[W.HANDLE,C.POINTER(Module)];k.CloseHandle.argtypes=[W.HANDLE]
 snap=k.CreateToolhelp32Snapshot(0x18,pid)
 if snap==C.c_void_p(-1).value:raise C.WinError(C.get_last_error())
 try:
  module=Module();module.size=C.sizeof(module)
  if not k.Module32FirstW(snap,C.byref(module)):raise C.WinError(C.get_last_error())
  if Path(module.path).resolve()!=(game_dir()/'METAL GEAR SOLID PEACE WALKER.exe').resolve():raise RuntimeError('The running game is from a different installation.')
  return module.base
 finally:k.CloseHandle(snap)

def require_game_closed():
 if processes():raise RuntimeError('Close Peace Walker before installation or removal.')

def require_steam_closed():
 result=subprocess.run(['powershell','-NoProfile','-Command',"@(Get-Process -Name steam -ErrorAction SilentlyContinue).Count"],capture_output=True,text=True,check=True,creationflags=0x08000000)
 if result.stdout.strip()!='0':raise RuntimeError('Exit Steam completely before restoring saves.')

def reconstruct_model(source,patch,destination,record):
 if digest(patch)!=record['sha256']:raise RuntimeError('A model patch is damaged. Extract the package again.')
 shutil.copy2(source,destination)
 with gzip.open(patch,'rb') as inp,destination.open('r+b') as out:
  if inp.read(8)!=b'EO129P1\0':raise RuntimeError('Invalid model patch.')
  size,count=struct.unpack('<QI',inp.read(12));end=0
  if size!=record['output_size']:raise RuntimeError('Unexpected model patch size.')
  for _ in range(count):
   offset,length=struct.unpack('<QI',inp.read(12))
   if offset<end or offset+length>size:raise RuntimeError('Invalid model patch range.')
   data=inp.read(length)
   if len(data)!=length:raise RuntimeError('Truncated model patch.')
   out.seek(offset);out.write(data);end=offset+length
  if inp.read(1):raise RuntimeError('Unexpected model patch data.')
  out.truncate(size)
 if digest(destination)!=record['output_sha256']:raise RuntimeError('Rebuilt model archive failed verification.')

def apply_coop(source,patch,destination,record):
 if digest(patch)!=record['sha256']:raise RuntimeError('The co-op patch is damaged. Extract the package again.')
 shutil.copy2(source,destination);payload=zlib.decompress(patch.read_bytes())
 if payload[:4]!=b'CP4P':raise RuntimeError('Invalid co-op patch.')
 cursor=8
 with destination.open('r+b') as stream:
  for _ in range(struct.unpack_from('<I',payload,4)[0]):
   offset,length=struct.unpack_from('<QI',payload,cursor);cursor+=12
   if offset+length>record['output_size'] or cursor+length>len(payload):raise RuntimeError('Invalid co-op patch range.')
   stream.seek(offset);stream.write(payload[cursor:cursor+length]);cursor+=length
 if cursor!=len(payload) or digest(destination)!=record['output_sha256']:raise RuntimeError('Rebuilt co-op archive failed verification.')

def install(mode):
 if mode not in ('models','coop','both'):raise ValueError('Invalid installation mode.')
 require_game_closed();game=game_dir();doc=manifest();archives=game/'MLG/disc0_rel'
 if digest(game/'METAL GEAR SOLID PEACE WALKER.exe')!=doc['exe_sha256']:raise RuntimeError('This game executable is not supported. No files changed.')
 if (STATE/'install.json').exists():raise RuntimeError('A mode is already installed by this folder. Uninstall all first.')
 current={name:digest(archives/name) for name in NAMES}
 if current!=doc['original_files']:raise RuntimeError('Game archives are not the verified vanilla files. Uninstall other archive mods or verify Steam files first.')
 backup_saves(game,ROOT);BACKUP.mkdir(exist_ok=True);work=ROOT/'work';work.mkdir(exist_ok=True)
 for name in NAMES:
  destination=BACKUP/name
  if destination.exists() and digest(destination)!=doc['original_files'][name]:raise RuntimeError(f'Existing backup does not match vanilla: {name}')
  if not destination.exists():shutil.copy2(archives/name,destination)
  shutil.copy2(BACKUP/name,work/name)
 if mode in ('models','both'):
  for name in NAMES:
   rec=doc['patches']['model_'+name];reconstruct_model(BACKUP/name,DATA/rec['file'],work/name,rec)
 if mode=='coop':
  rec=doc['patches']['coop_from_vanilla'];apply_coop(BACKUP/'009645fa.PDT',DATA/rec['file'],work/'009645fa.PDT',rec)
 elif mode=='both':
  rec=doc['patches']['coop_from_models'];source=work/'009645fa.PDT';temporary=work/'009645fa.PDT.combined';apply_coop(source,DATA/rec['file'],temporary,rec);os.replace(temporary,source)
 expected=doc['modes'][mode]['files']
 if {name:digest(work/name) for name in NAMES}!=expected:raise RuntimeError('Staged installation verification failed.')
 require_game_closed()
 if {name:digest(archives/name) for name in NAMES}!=current:raise RuntimeError('Game files changed during preparation.')
 STATE.mkdir(exist_ok=True);receipt={'mode':mode,'game':str(game.resolve()),'original_files':current,'installed_files':expected,'installed_utc':time.time()};(STATE/'install.json').write_text(json.dumps(receipt,indent=2))
 try:
  for name in NAMES:
   shutil.copy2(work/name,archives/name)
   if digest(archives/name)!=expected[name]:raise RuntimeError(f'Installed file verification failed: {name}')
 except BaseException:
  for name in NAMES:shutil.copy2(BACKUP/name,archives/name)
  (STATE/'install.json').unlink(missing_ok=True)
  raise
 finally:
  for name in NAMES:(work/name).unlink(missing_ok=True)
 print(f'Installed mode: {mode}. Use Play Extra Ops 129.cmd for each session.')

def uninstall():
 require_game_closed();receipt=installation_receipt();game=Path(receipt['game']);archives=game/'MLG/disc0_rel';work=ROOT/'work';work.mkdir(exist_ok=True)
 if {name:digest(archives/name) for name in NAMES}!=receipt['installed_files']:raise RuntimeError('Installed archives changed. Uninstall stopped to protect them.')
 if {name:digest(BACKUP/name) for name in NAMES}!=receipt['original_files']:raise RuntimeError('Verified original backups are missing or damaged.')
 for name in NAMES:shutil.copy2(archives/name,work/name)
 try:
  for name in NAMES:
   shutil.copy2(BACKUP/name,archives/name)
   if digest(archives/name)!=receipt['original_files'][name]:raise RuntimeError(f'Restore verification failed: {name}')
 except BaseException:
  for name in NAMES:shutil.copy2(work/name,archives/name)
  raise
 finally:
  for name in NAMES:(work/name).unlink(missing_ok=True)
 (STATE/'install.json').unlink();print('Uninstalled all Extra Ops 129 changes. Original archives restored and verified.')

def snapshots():
 items=sorted((ROOT/'save-backups').glob('*/manifest.json'))
 if not items:raise RuntimeError('No save backups exist in this package.')
 print('Available save backups:')
 for index,path in enumerate(items,1):print(f'{index}: {path.parent.name}')
 choice=int(input('Choose a save backup number: '))
 if not 1<=choice<=len(items):raise ValueError('Invalid save backup number.')
 return items[choice-1].parent

def uninstall_restore_save():
 require_steam_closed();snapshot=snapshots();receipt=installation_receipt();game=Path(receipt['game']);uninstall();restore_saves(game,ROOT,snapshot)

def restore_save_only():
 require_steam_closed();restore_saves(game_dir(),ROOT,snapshots())

def installed_mode():
 receipt=installation_receipt();doc=manifest();mode=receipt['mode']
 if mode not in doc['modes']:raise RuntimeError('Unknown installed mode.')
 game=Path(receipt['game']);archives=game/'MLG/disc0_rel';actual={name:digest(archives/name) for name in NAMES}
 if actual!=doc['modes'][mode]['files'] or actual!=receipt['installed_files']:raise RuntimeError('Installed files do not match the selected mode.')
 if digest(game/'METAL GEAR SOLID PEACE WALKER.exe')!=doc['exe_sha256']:raise RuntimeError('Unsupported game executable.')
 return mode,game

def play():
 require_game_closed();mode,game=installed_mode()
 if mode in ('models','both'):
  import model_runtime
  model_runtime.validate();model_runtime.preflight()
 print(f'Starting Extra Ops 129 ({mode}). Start Peace Walker in its launcher. Waiting for the actual game...',flush=True)
 os.startfile('steam://rungameid/2492660');deadline=time.monotonic()+900
 while time.monotonic()<deadline:
  found=processes()
  if found:
   if len(found)!=1:raise RuntimeError('More than one Peace Walker process is running.')
   pid=found[0];base=module_base(pid)
   if mode in ('models','both'):
    import model_runtime
    from character_config import load_config
    model_runtime.config=load_config(json.loads((DATA/'runtime_config.json').read_text()));model_runtime.validate()
    for attempt in range(6):
     try:model_runtime.apply(pid,base);break
     except OSError as error:
      if error.winerror!=31 or attempt==5:raise
      time.sleep(3)
   if mode in ('coop','both'):
    import coop_runtime
    coop_runtime.D=STATE
    for attempt in range(6):
     try:coop_runtime.apply(pid,base);break
     except OSError as error:
      if error.winerror!=31 or attempt==5:raise
      time.sleep(3)
   print(f'Extra Ops 129 is active in {mode} mode. This helper can close.');return
  time.sleep(.5)
 raise RuntimeError('Timed out waiting for Peace Walker.')

def check():
 mode,game=installed_mode()
 if mode in ('models','both'):
  import model_runtime
  model_runtime.validate()
 print(f'Installation verified. Active mode: {mode}.')

def setup():
 print('Extra Ops 129 Setup')
 print('1: Install models')
 print('2: Install 4-player co-op')
 print('3: Install models and 4-player co-op')
 print('4: Uninstall all')
 print('5: Uninstall all and restore save')
 print('6: Restore save only')
 action=input('Choose 1-6: ').strip()
 actions={'1':lambda:install('models'),'2':lambda:install('coop'),'3':lambda:install('both'),'4':uninstall,'5':uninstall_restore_save,'6':restore_save_only}
 if action not in actions:raise ValueError('Choose 1, 2, 3, 4, 5, or 6.')
 actions[action]()

def main():
 STATE.mkdir(exist_ok=True);action=sys.argv[1].lower() if len(sys.argv)>1 else ''
 if not action:
  print('Extra Ops 129')
  print('1: Setup, change, uninstall, or restore')
  print('2: Play')
  print('3: Check installation')
  action={'1':'setup','2':'play','3':'check'}.get(input('Choose 1-3: ').strip(),'')
 actions={'setup':setup,'play':play,'check':check,'install-models':lambda:install('models'),'install-coop':lambda:install('coop'),'install-both':lambda:install('both'),'uninstall':uninstall}
 if action not in actions:raise ValueError('Choose setup, play, or check.')
 actions[action]()

if __name__=='__main__':
 try:main()
 except Exception as error:
  try:
   STATE.mkdir(exist_ok=True)
   with (STATE/'last_error.log').open('a',encoding='utf8') as stream:stream.write(time.strftime('%Y-%m-%d %H:%M:%S')+'\n'+traceback.format_exc()+'\n')
  except OSError:pass
  print(f'\nERROR: {error}\nDetails: {STATE / "last_error.log"}',flush=True);sys.exit(1)
