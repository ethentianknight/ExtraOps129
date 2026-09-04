import hashlib,json,os,shutil,subprocess,time,uuid
from datetime import datetime,timezone
from pathlib import Path

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def inventory(root):
    files={}
    for path in root.rglob('*'):
        if path.is_symlink() or path.is_junction():raise RuntimeError('Save folder contains a link; backup stopped.')
        if path.is_file():files[path.relative_to(root).as_posix()]=digest(path)
    return files

def backup_saves(game,package):
    source=game.parent/'mgspw_savedata_win'
    if not source.is_dir():raise RuntimeError(f'Save folder not found: {source}. No game files changed.')
    if source.is_symlink() or source.is_junction():raise RuntimeError('Save root is a link; backup stopped.')
    before=inventory(source)
    if not before:raise RuntimeError('Save folder is empty; no verified save backup can be made.')
    name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    destination=package/'save-backups'/name
    destination.mkdir(parents=True)
    shutil.copytree(source,destination/'files')
    if inventory(destination/'files')!=before or inventory(source)!=before:
        raise RuntimeError('Save files changed during backup or verification failed. Install stopped.')
    receipt={'game':str(game.resolve()),'save_root':str(source.resolve()),'files':before,'created_utc':name}
    (destination/'manifest.json').write_text(json.dumps(receipt,indent=2))
    print(f'Verified save backup: {destination}',flush=True)
    return destination

def restore_saves(game,package,snapshot):
    result=subprocess.run(['powershell','-NoProfile','-Command',"@(Get-Process -Name steam -ErrorAction SilentlyContinue).Count"],capture_output=True,text=True,check=True,creationflags=0x08000000)
    if result.stdout.strip()!='0':raise RuntimeError('Exit Steam completely before restoring saves to prevent cloud-sync interference.')
    snapshot=snapshot.resolve();backup_root=(package/'save-backups').resolve()
    if snapshot.parent!=backup_root:raise RuntimeError('Select a snapshot from this package save-backups folder.')
    receipt=json.loads((snapshot/'manifest.json').read_text())
    if Path(receipt['game']).resolve()!=game.resolve():raise RuntimeError('Snapshot belongs to a different game installation.')
    if inventory(snapshot/'files')!=receipt['files']:raise RuntimeError('Save snapshot verification failed.')
    target=game.parent/'mgspw_savedata_win'
    if target.exists():backup_saves(game,package)
    suffix=uuid.uuid4().hex
    staged=target.with_name(target.name+'.restore-'+suffix)
    previous=target.with_name(target.name+'.before-restore-'+suffix)
    shutil.copytree(snapshot/'files',staged)
    if inventory(staged)!=receipt['files']:raise RuntimeError('Staged save restoration failed verification.')
    moved=False
    try:
        if target.exists():os.replace(target,previous);moved=True
        os.replace(staged,target)
        if inventory(target)!=receipt['files']:raise RuntimeError('Restored save verification failed after replacement.')
    except Exception:
        failed=target.with_name(target.name+'.failed-restore-'+suffix)
        if moved:
            if target.exists():os.replace(target,failed)
            os.replace(previous,target)
        raise
    timestamp=time.time()
    for path in target.rglob('*'):
        if path.is_file():os.utime(path,(timestamp,timestamp))
    if inventory(target)!=receipt['files']:raise RuntimeError('Restored save changed while updating local timestamps.')
    state=package/'state';state.mkdir(exist_ok=True)
    result={'snapshot':snapshot.name,'game':str(game.resolve()),'save_root':str(target.resolve()),'files':receipt['files'],'restored_utc':datetime.now(timezone.utc).isoformat(),'previous_saves':str(previous.resolve()),'verified_after_replacement':True,'local_timestamps_refreshed':True}
    (state/'last-save-restore.json').write_text(json.dumps(result,indent=2))
    print('Verified save snapshot restored. Pre-restore saves were preserved.')
    print(f'Previous saves: {previous}')
    print('Steam Cloud must already be disabled for Peace Walker before Steam restarts. If Steam reports a conflict, keep the local files.')
