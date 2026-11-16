from __future__ import annotations
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile

SCHEMA=1

def default_state():
    return {'schema':SCHEMA,'settings':{'names':['직원 1','직원 2'],'breaks':[None,None,None],
            'check_updates':True},'months':{}}

def data_directory():
    explicit=os.environ.get('DUOROSTER_DATA_DIR')
    if explicit:return Path(explicit).expanduser().resolve()
    return Path(os.environ.get('APPDATA',str(Path.home()/'.config')))/'DuoRoster'

def validate_state(state):
    if not isinstance(state,dict) or state.get('schema')!=SCHEMA:raise ValueError('지원하지 않는 데이터 버전입니다.')
    names=state.get('settings',{}).get('names',[])
    if len(names)!=2 or not all(isinstance(v,str) and v.strip() for v in names) or names[0]==names[1]:
        raise ValueError('서로 다른 직원 이름 두 개가 필요합니다.')
    if not isinstance(state.get('months'),dict):raise ValueError('월별 기록이 올바르지 않습니다.')
    return state

class Store:
    def __init__(self,directory=None):
        self.directory=Path(directory) if directory else data_directory()
        self.path=self.directory/'state.json'
        self.directory.mkdir(parents=True,exist_ok=True)

    def load(self):
        if not self.path.exists():return default_state()
        try:return validate_state(json.loads(self.path.read_text(encoding='utf-8')))
        except (ValueError,OSError) as exc:
            raise ValueError(f'저장 기록을 읽을 수 없습니다. 원본은 보존되어 있습니다. 백업에서 복원하세요.\n{self.path}') from exc

    def save(self,state):
        validate_state(state)
        backups=self.directory/'backups'
        backups.mkdir(exist_ok=True)
        if self.path.exists():
            old=backups/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
            old.write_bytes(self.path.read_bytes())
            # Only remove known application-owned JSON snapshots in this directory.
            for stale in sorted(backups.glob('*.json'))[:-60]:stale.unlink()
        raw=json.dumps(state,ensure_ascii=False,indent=2)
        fd,name=tempfile.mkstemp(prefix='state-',suffix='.tmp',dir=self.directory)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            os.replace(name,self.path)
        finally:
            if Path(name).exists():Path(name).unlink()

    def export_backup(self,target,state):
        validate_state(state)
        Path(target).write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')

    def restore(self,target):
        state=validate_state(json.loads(Path(target).read_text(encoding='utf-8')))
        self.save(state)
        return copy.deepcopy(state)
