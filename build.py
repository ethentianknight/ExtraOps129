import hashlib,importlib.util,shutil,struct,subprocess,sys,zipfile
from pathlib import Path

def digest(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
 if sys.platform!='win32' or sys.version_info[:2]!=(3,12) or struct.calcsize('P')!=8:raise RuntimeError('Build with Windows x64 and Python 3.12 x64.')
 if importlib.util.find_spec('PyInstaller') is None:raise RuntimeError('Run: python -m pip install -r requirements.txt')
 root=Path(__file__).resolve().parent;assets=root/'assets';output=root/'dist/Extra-Ops-129-v0.2.1';work=root/'.build'
 if output.exists():shutil.rmtree(output)
 output.mkdir(parents=True);work.mkdir(exist_ok=True);members=[]
 for source in sorted(assets.rglob('*')):
  if source.is_file():
   relative=source.relative_to(assets);target=output/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);members.append(relative)
 subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--console','--name','EO129','--distpath',str(output),'--workpath',str(work/'work'),'--specpath',str(work),str(root/'src/eo129.py')],check=True,cwd=root)
 members.append(Path('EO129.exe'));hashes={p.as_posix():digest(output/p) for p in sorted(members)};(output/'SHA256SUMS.txt').write_text(''.join(f'{value}  {name}\n' for name,value in hashes.items()),encoding='utf8');members.append(Path('SHA256SUMS.txt'))
 archive=root/'dist/Extra-Ops-129-v0.2.1.zip'
 with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as package:
  for relative in sorted(members):package.write(output/relative,Path('Extra Ops 129')/relative)
 with zipfile.ZipFile(archive) as package:
  if package.testzip() is not None:raise RuntimeError('ZIP integrity check failed.')
  for name,expected in hashes.items():
   if hashlib.sha256(package.read('Extra Ops 129/'+name)).hexdigest()!=expected:raise RuntimeError(f'ZIP verification failed: {name}')
 archive.with_suffix('.sha256').write_text(digest(archive)+'  '+archive.name+'\n',encoding='ascii');print(f'Built and verified: {archive}')

if __name__=='__main__':main()
