from __future__ import annotations
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from packaging.version import Version,InvalidVersion
from . import __version__,RELEASE_REPOSITORY

AGENT='DuoRoster/'+__version__

def _request(url):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme!='https' or parsed.hostname not in {'api.github.com','github.com'}:
        raise ValueError('GitHub HTTPS 주소만 사용할 수 있습니다.')
    return urllib.request.Request(url,headers={'User-Agent':AGENT,'Accept':'application/vnd.github+json'})

def check_update(repository=RELEASE_REPOSITORY):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository or ''):
        return None
    try:
        with urllib.request.urlopen(_request(f'https://api.github.com/repos/{repository}/releases/latest'),timeout=12) as response:
            data=json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code==404:return None
        raise
    if data.get('draft') or data.get('prerelease'):return None
    version=str(data.get('tag_name','')).removeprefix('v')
    try:
        if Version(version)<=Version(__version__):return None
    except InvalidVersion:raise ValueError('업데이트 버전 정보가 올바르지 않습니다.')
    asset_name=f'DuoRoster-{version}-windows-x64.zip'
    asset=next((a for a in data.get('assets',[]) if a.get('name')==asset_name),None)
    if not asset:return None
    digest=asset.get('digest','')
    if not re.fullmatch(r'sha256:[a-fA-F0-9]{64}',digest):
        raise ValueError('업데이트의 SHA-256 검증 정보가 없습니다.')
    url=asset.get('browser_download_url','')
    expected_prefix=f'https://github.com/{repository}/releases/download/'
    if not url.startswith(expected_prefix):raise ValueError('업데이트 주소가 배포 저장소와 다릅니다.')
    return {'version':version,'url':url,'sha256':digest.split(':',1)[1].lower(),
            'notes':str(data.get('body',''))[:4000],'repository':repository}

def verify_archive(path,expected_sha256):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    if digest.hexdigest()!=expected_sha256.lower():raise ValueError('업데이트 파일의 검증 값이 일치하지 않습니다.')
    with zipfile.ZipFile(path) as archive:
        total=0
        for member in archive.infolist():
            raw=member.filename
            part=PurePosixPath(raw)
            if '\\' in raw or ':' in raw or part.is_absolute() or '..' in part.parts or not part.parts or part.parts[0]!='DuoRoster':
                raise ValueError('업데이트 압축 파일의 경로가 올바르지 않습니다.')
            if (member.external_attr>>16)&0o170000==0o120000:raise ValueError('업데이트에 심볼릭 링크가 포함되어 있습니다.')
            total+=member.file_size
            if total>2*1024**3:raise ValueError('업데이트 압축 해제 크기가 너무 큽니다.')
        if 'DuoRoster/DuoRoster.exe' not in archive.namelist():raise ValueError('업데이트 실행 파일이 없습니다.')

def download_update(info,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    target=directory/('DuoRoster-'+info['version']+'.zip')
    partial=target.with_suffix('.part')
    try:
        with urllib.request.urlopen(_request(info['url']),timeout=30) as response,partial.open('wb') as output:
            host=urllib.parse.urlparse(response.geturl()).hostname or ''
            if host!='github.com' and not host.endswith('.githubusercontent.com'):
                raise ValueError('업데이트 다운로드의 최종 주소가 올바르지 않습니다.')
            size=0
            for chunk in iter(lambda:response.read(1024*1024),b''):
                size+=len(chunk)
                if size>1024**3:raise ValueError('업데이트 파일이 너무 큽니다.')
                output.write(chunk)
        verify_archive(partial,info['sha256'])
        os.replace(partial,target)
        return target
    finally:
        if partial.exists():partial.unlink()

def _ps_quote(value):return "'"+str(value).replace("'","''")+"'"

def update_script(install,staged,parent_pid,log_path):
    install=Path(install).resolve();staged=Path(staged).resolve()
    if install.name!='DuoRoster' or not (install/'DuoRoster.exe').is_file():
        raise ValueError('설치된 DuoRoster 폴더에서만 업데이트할 수 있습니다.')
    if install==staged or install in staged.parents or staged in install.parents:
        raise ValueError('업데이트 준비 폴더와 설치 폴더가 겹칩니다.')
    backup=install.with_name('DuoRoster.previous-'+datetime.now().strftime('%Y%m%d%H%M%S%f'))
    return f"""$ErrorActionPreference='Stop'
$install={_ps_quote(install)}
$stage={_ps_quote(staged)}
$backup={_ps_quote(backup)}
$log={_ps_quote(log_path)}
try {{ [Diagnostics.Process]::GetProcessById({int(parent_pid)}).WaitForExit() }} catch {{}}
$moved=$false
try {{
  for($attempt=0;$attempt -lt 25;$attempt++) {{
    try {{ Move-Item -LiteralPath $install -Destination $backup; $moved=$true; break }} catch {{ Start-Sleep -Milliseconds 400 }}
  }}
  if(-not $moved) {{ throw '기존 프로그램 폴더를 옮길 수 없습니다.' }}
  Move-Item -LiteralPath $stage -Destination $install
  '업데이트 완료' | Set-Content -LiteralPath $log -Encoding UTF8
  Start-Process -FilePath (Join-Path $install 'DuoRoster.exe') -WindowStyle Normal
}} catch {{
  $_ | Out-String | Set-Content -LiteralPath $log -Encoding UTF8
  if($moved -and -not (Test-Path -LiteralPath $install)) {{ Move-Item -LiteralPath $backup -Destination $install }}
  if(Test-Path -LiteralPath (Join-Path $install 'DuoRoster.exe')) {{ Start-Process -FilePath (Join-Path $install 'DuoRoster.exe') -WindowStyle Normal }}
}}
"""

def launch_update(archive,expected_sha256,directory):
    if os.name!='nt' or not getattr(sys,'frozen',False):raise ValueError('설치된 윈도우 앱에서 업데이트를 적용하세요.')
    verify_archive(archive,expected_sha256)
    stage=Path(sys.executable).resolve().parent.parent/('DuoRoster.staged-'+datetime.now().strftime('%Y%m%d%H%M%S%f'))
    stage.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zipped:zipped.extractall(stage)
    script=update_script(Path(sys.executable).parent,stage/'DuoRoster',os.getpid(),Path(directory)/'last-update.log')
    encoded=base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                     creationflags=subprocess.CREATE_NO_WINDOW)

def install_application():
    if not getattr(sys,'frozen',False):raise ValueError('배포용 실행 파일에서 설치를 실행하세요.')
    import shutil
    import winreg
    source=Path(sys.executable).parent.resolve()
    destination=Path(os.environ['LOCALAPPDATA'])/'Programs'/'DuoRoster'
    if destination.exists():
        raise ValueError('이미 설치되어 있습니다. 앱의 업데이트 확인을 이용하세요.')
    if source==destination.resolve():return destination
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source,destination)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
        desktop=Path(os.path.expandvars(winreg.QueryValueEx(key,'Desktop')[0]))
    link=desktop/'두 사람 근무표.lnk'
    script=f"$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut({_ps_quote(link)}); $s.TargetPath={_ps_quote(destination/'DuoRoster.exe')}; $s.WorkingDirectory={_ps_quote(destination)}; $s.Description='두 사람 근무표'; $s.Save()"
    encoded=base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    return destination
