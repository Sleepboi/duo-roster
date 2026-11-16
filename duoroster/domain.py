from __future__ import annotations
from collections import Counter
import copy
from datetime import date,timedelta,datetime
import re
from . import engine

COLORS={'D':'#57B874','E':'#D8EF9A','MD':'#8FC4F1','OFF':'#F8B26B'}
OPPOSITE={'D':'E','E':'D','MD':'OFF','OFF':'MD'}

def month_key(year,month):return f'{year:04d}-{month:02d}'

def next_month(key,delta=1):
    year,month=map(int,key.split('-'))
    index=year*12+month-1+delta
    return month_key(index//12,index%12+1)

def ensure_month(state,key):
    if key not in state['months']:
        year,month=map(int,key.split('-'))
        data=engine.default_data(year,month,1,state['settings']['names'])
        state['months'][key]={'days':data['days'],'result':{},'off_goal':minimum_off(data['days']),
                              'status':'draft','updated_at':None}
    return state['months'][key]

def minimum_off(days):
    count=sum(date.fromisoformat(r['date']).weekday()>=5 or r['holiday'] for r in days)
    return max(8,count-2)

def complete(month):
    return all(month['result'].get(r['date']) and all(c in engine.CODES for c in month['result'][r['date']]) for r in month['days'])

def counts(month,person):
    if not complete(month):return None
    return Counter(month['result'][r['date']][person] for r in month['days'])

def build_problem(state,key,include_next=False):
    keys=[key]
    if include_next and next_month(key) in state['months']:keys.append(next_month(key))
    year,month=map(int,key.split('-'))
    data=engine.default_data(year,month,len(keys),state['settings']['names'])
    data['days']=[];data['target_overrides']={};data['previous_plan']=[]
    data['breaks']=state['settings'].get('breaks',[None,None,None])
    data['max_seconds']=20
    for selected in keys:
        m=ensure_month(state,selected)
        data['days'].extend(copy.deepcopy(m['days']))
        data['target_overrides'][selected]=int(m['off_goal'])
        data['previous_plan'].extend(copy.deepcopy(m['result'].get(r['date'])) for r in m['days'])
    first=date.fromisoformat(data['days'][0]['date'])
    for rec in data['history']:
        old=state['months'].get(rec['date'][:7],{})
        row=old.get('result',{}).get(rec['date'])
        rec['shifts']=copy.deepcopy(row) if row else ['','']
    data['annual_records']=[]
    for stored,m in state['months'].items():
        if stored>=key or m.get('status')!='actual' or not complete(m):continue
        for p,name in enumerate(data['names']):
            data['annual_records'].append({'month':stored,'name':name,'counts':{c:counts(m,p)[c] for c in engine.CODES}})
    return data

def generate(state,key,include_next=False):
    candidate=copy.deepcopy(state)
    data=build_problem(candidate,key,include_next)
    engine.solve(data)  # Never silently deliver a partial horizon.
    if data['result'] is None:
        return {'ok':False,'issues':data['issues']}
    changes=[]
    for rec,row in zip(data['days'],data['result']):
        m=ensure_month(candidate,rec['date'][:7])
        old=m['result'].get(rec['date'])
        if old!=row:changes.append({'date':rec['date'],'before':old,'after':row})
        m['result'][rec['date']]=row
        m['status']='plan';m['updated_at']=datetime.now().isoformat(timespec='seconds')
    return {'ok':True,'state':candidate,'changes':changes,'exceptions':data['return_exceptions'],
            'boundary_complete':data['boundary_complete'],'status':data['solver_status']}

def edit_shift(state,key,day,person,code,fixed=True):
    if code not in engine.CODES:raise ValueError('근무 코드를 확인하세요.')
    m=ensure_month(state,key)
    rec=next(r for r in m['days'] if r['date']==day)
    partner=1-person
    partner_fixed=rec['fixed'][partner]
    if partner_fixed and partner_fixed!=OPPOSITE[code]:
        raise ValueError('상대방의 고정 근무와 충돌합니다. 먼저 상대방의 고정을 해제하세요.')
    row=[None,None];row[person]=code;row[partner]=OPPOSITE[code]
    m['result'][day]=row
    rec['fixed'][person]=code if fixed else ''
    m['status']='draft';m['updated_at']=datetime.now().isoformat(timespec='seconds')

def inspect_month(state,key):
    m=ensure_month(state,key)
    if not complete(m):
        return {'errors':['아직 배정하지 않은 날짜가 있습니다. 근무표 만들기를 눌러 주세요.'],
                'exceptions':[],'boundary_complete':False}
    data=build_problem(state,key)
    data['result']=[m['result'][r['date']] for r in m['days']]
    year,month=map(int,key.split('-'))
    data['targets']=[{'year':year,'month':month,'off':m['off_goal']}]
    errors=engine.validate(data)
    friendly=[]
    for error in errors:
        match=re.match(r'^([01]) (\d+) 6연근$',error)
        if match:
            p,index=map(int,match.groups())
            day=data['days'][max(0,index-5)]['date']
            friendly.append(f'{day} {data["names"][p]}: 연속근무가 5일을 넘습니다.')
            continue
        match=re.match(r'^([01]) 휴무 수$',error)
        if match:
            p=int(match[1]);actual=counts(m,p)['OFF']
            friendly.append(f'{data["names"][p]}: 휴무 {actual}일 / 목표 {m["off_goal"]}일')
            continue
        text=error.replace('6연근','최대 연속근무 초과').replace('OFF 상대는 반드시 MD','상대방이 OFF이면 MD 필수')
        text=re.sub(r'^([01]) ',lambda v:data['names'][int(v[1])]+' ',text)
        friendly.append(text)
    return {'errors':friendly,'exceptions':engine.return_day_exceptions(data),
            'boundary_complete':all(all(r['shifts']) for r in data['history'])}

def yearly_counts(state,year):
    totals=[Counter(),Counter()]
    known=0
    for key,m in state['months'].items():
        if key.startswith(str(year)) and m.get('status')=='actual' and complete(m):
            known+=1
            for p in range(2):totals[p].update(counts(m,p))
    return totals,known
