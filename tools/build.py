from __future__ import annotations
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from duoroster import __version__

def main():
    subprocess.run([sys.executable,str(ROOT/'tools'/'generate_icon.py')],check=True)
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed',
        '--name','DuoRoster','--icon','assets/duoroster.ico','--add-data','assets/duoroster.ico;assets',
        '--collect-all','ortools','--collect-submodules','holidays',
        '--collect-data','holidays','--collect-data','reportlab','main.py'],cwd=ROOT,check=True)
    app=ROOT/'dist'/'DuoRoster'
    (app/'설치.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0DuoRoster.exe" --install\r\n',encoding='ascii')
    for name in ('USER_GUIDE.md','THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT/name,app/name)
    release=ROOT/'release';release.mkdir(exist_ok=True)
    archive=release/f'DuoRoster-{__version__}-windows-x64.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as zipped:
        for path in app.rglob('*'):
            if path.is_file():zipped.write(path,path.relative_to(app.parent))
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (release/'SHA256SUMS.txt').write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    print(archive)

if __name__=='__main__':main()
