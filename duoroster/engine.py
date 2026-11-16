from __future__ import annotations
from datetime import date, datetime, timedelta
import calendar
import holidays
from ortools.sat.python import cp_model

CODES=("D","E","MD","OFF")


def dates_for(year, month, count):
    if not 2000 <= year <= 2100 or not 1 <= month <= 12 or not 1 <= count <= 12:
        raise ValueError('연도 2000~2100, 월 1~12, 개월 수 1~12를 입력하세요.')
    start = date(year, month, 1)
    end_index = year * 12 + month - 1 + count
    end = date(end_index // 12, end_index % 12 + 1, 1)
    return [start + timedelta(days=i) for i in range((end - start).days)]

def default_data(year=2026, month=11, count=2, names=None):
    days = dates_for(year, month, count)
    kr = holidays.KR(years=sorted({d.year for d in days}), language='ko')
    return {
        'year': year, 'month': month, 'count': count,
        'names': names or ['직원 1', '직원 2'],
        'breaks': [None, None, None], 'max_seconds': 35, 'weekend_pair': 0,
        'annual_records': [], 'previous_plan': None,
        'target_overrides': {},
        'days': [{'date': d.isoformat(), 'holiday': int(d in kr),
                  'holiday_name': kr.get(d, ''), 'fixed': ['', ''],
                  'wish': [0, 0], 'coverage': 1} for d in days],
        'history': [{'date': (days[0] - timedelta(days=5-i)).isoformat(),
                     'shifts': ['', '']} for i in range(5)],
        'result': None, 'issues': [],
    }

def solve(data):
    model = cp_model.CpModel()
    days = [date.fromisoformat(r['date']) for r in data['days']]
    n = len(days)
    x = {(p, t, c): model.new_bool_var(f'x{p}_{t}_{c}')
         for p in range(2) for t in range(n) for c in CODES}
    for p in range(2):
        for t in range(n):
            model.add_exactly_one(x[p, t, c] for c in CODES)
    labels = {}
    def group(label):
        g = model.new_bool_var('rule_' + str(len(labels)))
        model.add_assumption(g)
        labels[g.index] = label
        return g
    coverage = group('날짜별 최소 출근 인원')
    wednesdays = group('공휴일이 아닌 수요일은 두 명 D/E 근무 필수')
    transitions = group('E 다음날은 E 또는 OFF만 허용')
    consecutive = group('최대 5일 연속근무')
    weekend = group('주말·공휴일 단독 MD, 필요 시 2인 D/E' if data['weekend_pair'] else '주말·공휴일은 단독 MD')
    pairing = group('허용 조합은 D+E / MD+OFF / OFF+MD만')
    penalties = []
    return_penalties = []
    for t, d in enumerate(days):
        off = [x[p, t, 'OFF'] for p in range(2)]
        model.add(sum(off) <= 2 - data['days'][t]['coverage']).only_enforce_if(coverage)
        for p in range(2):
            q=1-p
            model.add(x[p,t,'MD'] == off[q]).only_enforce_if(pairing)
            model.add(x[p,t,'E'] <= x[q,t,'D']).only_enforce_if(pairing)
            model.add(x[p,t,'D'] <= x[q,t,'E']).only_enforce_if(pairing)
            model.add(x[p,t,'D'] + x[q,t,'D'] <= 1).only_enforce_if(pairing)
        special = d.weekday() >= 5 or data['days'][t]['holiday']
        if d.weekday()==2 and not special:
            model.add(sum(off)==0).only_enforce_if(wednesdays)
        if special:
            for p in range(2):
                if data['weekend_pair']:
                    model.add(x[p,t,'D'] <= x[1-p,t,'E']).only_enforce_if(weekend)
                else:
                    model.add(x[p,t,'D'] + x[p,t,'E'] == 0).only_enforce_if(weekend)
            # Prefer one worker on weekends and public holidays.
            penalties.append((1 - sum(off)) * 40)
        else:
            if d.weekday() in (0,2,4):
                penalties.append(sum(off) * 70)
            else:
                penalties.append((1 - sum(off)) * 10)
        for p in range(2):
            fixed = data['days'][t]['fixed'][p]
            if fixed:
                g = group(f'{d} {data["names"][p]} 고정 {fixed}')
                model.add(x[p,t,fixed] == 1).only_enforce_if(g)
            if data['days'][t]['wish'][p]:
                penalties.append((1 - x[p,t,'OFF']) * 120)
            previous=data.get('previous_plan')
            if previous and previous[t]:
                old=previous[t][p]
                penalties.append((1-x[p,t,old])*5)
                model.add_hint(x[p,t,old],1)
    for p in range(2):
        history = [r['shifts'][p] for r in data['history']]
        def is_off(t):
            if t >= 0:
                return x[p,t,'OFF']
            v = history[t + 5]
            return None if not v else int(v == 'OFF')
        for t in range(n):
            special=days[t].weekday()>=5 or data['days'][t]['holiday']
            if t:
                model.add(x[p,t-1,'E'] <= x[p,t,'OFF']+x[p,t,'E']).only_enforce_if(transitions)
            elif history[-1] == 'E':
                model.add(x[p,0,'OFF']+x[p,0,'E'] == 1).only_enforce_if(transitions)
            prev = is_off(t-1)
            if prev is not None and not special:
                exception=model.new_bool_var(f'return_exception{p}_{t}')
                model.add(exception >= prev - x[p,t,'OFF'] - x[p,t,'D'])
                return_penalties.append(exception)
            window = [is_off(j) for j in range(t-5,t+1)]
            if all(v is not None for v in window):
                model.add(sum(window) >= 1).only_enforce_if(consecutive)
    months = sorted({(d.year, d.month) for d in days})
    targets = []
    def balance(expr0, expr1, bound, weight, key):
        diff = model.new_int_var(0, bound, key)
        model.add_abs_equality(diff, expr0 - expr1)
        penalties.append(diff * weight)
    for y,m in months:
        ix = [t for t,d in enumerate(days) if (d.year,d.month) == (y,m)]
        h = sum(days[t].weekday() >= 5 or data['days'][t]['holiday'] for t in ix)
        base_target=max(8,h-2)
        target=data['target_overrides'].get(f'{y}-{m:02d}',base_target)
        if target<base_target:
            raise ValueError(f'{y}-{m:02d} 지정 휴무가 최소 보장 {base_target}일보다 적습니다.')
        targets.append({'year':y,'month':m,'holidays':h,'off':target})
        off_counts=[sum(x[p,t,'OFF'] for t in ix) for p in range(2)]
        for p in range(2):
            g = group(f'{y}-{m:02d} {data["names"][p]} 휴무 정확히 {target}일')
            model.add(off_counts[p] == target).only_enforce_if(g)
        fair=group(f'{y}-{m:02d} 두 사람 D/E 횟수 차이 각각 최대 3일')
        for c in ('D','E'):
            delta=sum(x[0,t,c]-x[1,t,c] for t in ix)
            model.add(delta<=3).only_enforce_if(fair)
            model.add(delta>=-3).only_enforce_if(fair)
        for c in ('D','E','MD'):
            balance(sum(x[0,t,c] for t in ix),sum(x[1,t,c] for t in ix),len(ix),60,f'fair{y}{m}{c}')
        for label, subset in [('weekend',[t for t in ix if days[t].weekday() >= 5]),
                              ('holiday',[t for t in ix if data['days'][t]['holiday']])]:
            balance(sum(x[0,t,'OFF'] for t in subset),sum(x[1,t,'OFF'] for t in subset),len(ix),35,f'{label}{y}{m}')
    for c in ('D','E','MD'):
        balance(sum(x[0,t,c] for t in range(n)),sum(x[1,t,c] for t in range(n)),n,45,'total'+c)
    annual_info=[]
    for year in sorted({d.year for d in days}):
        first=min(d for d in days if d.year==year)
        records=[r for r in data['annual_records'] if r['month']<first.strftime('%Y-%m') and r['month'].startswith(str(year))]
        complete=[]
        for month in sorted({r['month'] for r in records}):
            pair=[r for r in records if r['month']==month]
            if len(pair)==2 and {r['name'] for r in pair}==set(data['names']):complete.extend(pair)
        annual_info.append({'year':year,'known_months':len(complete)//2,'expected_months':first.month-1})
        for c in ('D','E','MD'):
            baseline=[sum(r['counts'][c] for r in complete if r['name']==name) for name in data['names']]
            sums=[baseline[p]+sum(x[p,t,c] for t,d in enumerate(days) if d.year==year) for p in range(2)]
            balance(sums[0],sums[1],366,300,'annual'+str(year)+c)
    data['annual_info']=annual_info
    # A whole point of the other preferences outweighs every return-D exception.
    model.minimize(sum(penalties)*(2*n+1)+sum(return_penalties))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = data['max_seconds']
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 12
    status = solver.solve(model)
    data['targets'] = targets
    data['solver_status'] = solver.status_name(status)
    if status == cp_model.INFEASIBLE:
        data['result'] = None
        data['issues'] = [labels.get(i, str(i)) for i in solver.sufficient_assumptions_for_infeasibility()]
        return data
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError('제한 시간 안에 근무표를 찾지 못했습니다. 계산 제한(초)을 늘려 재실행하세요. 불가능이 증명된 것은 아닙니다.')
    data['result'] = [[next(c for c in CODES if solver.value(x[p,t,c])) for p in range(2)] for t in range(n)]
    errors = validate(data)
    if errors:
        raise RuntimeError('독립 검증 실패: ' + '; '.join(errors))
    data['issues'] = []
    data['generated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data['objective'] = solver.objective_value
    data['boundary_complete'] = all(all(r['shifts']) for r in data['history'])
    data['return_exceptions'] = return_day_exceptions(data)
    return data

def plan(data):
    """Try the continuous horizon; retain feasible months if another month conflicts."""
    import copy
    solve(data)
    if data['result'] is not None:
        data['month_status']={f'{r["year"]}-{r["month"]:02d}':{'solved':True,'status':data['solver_status'],'issues':[],
            'boundary_complete':i>0 or all(all(h['shifts']) for h in data['history'])} for i,r in enumerate(data['targets'])}
        return data
    aggregate=[None]*len(data['days'])
    statuses={}
    for month in sorted({r['date'][:7] for r in data['days']}):
        indices=[i for i,r in enumerate(data['days']) if r['date'].startswith(month)]
        part=copy.deepcopy(data)
        part['days']=[copy.deepcopy(data['days'][i]) for i in indices]
        part['previous_plan']=[data['previous_plan'][i] for i in indices] if data.get('previous_plan') else None
        if indices[0]:
            first=date.fromisoformat(part['days'][0]['date'])
            part['history']=[]
            for back in range(5,0,-1):
                old=aggregate[indices[0]-back] if indices[0]>=back else None
                if old is None and indices[0]>=back:old=data['days'][indices[0]-back]['fixed']
                part['history'].append({'date':(first-timedelta(days=back)).isoformat(),'shifts':old or ['','']})
        solve(part)
        statuses[month]={'solved':part['result'] is not None,'status':part['solver_status'],
                         'issues':part['issues'],'boundary_complete':all(all(r['shifts']) for r in part['history'])}
        if part['result'] is not None:
            for i,row in zip(indices,part['result']):aggregate[i]=row
    data['result']=aggregate if any(r is not None for r in aggregate) else None
    data['month_status']=statuses
    data['solver_status']='PARTIAL' if data['result'] is not None else 'INFEASIBLE'
    data['generated_at']=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data['boundary_complete']=False
    data['return_exceptions']=return_day_exceptions(data)
    return data

def return_day_exceptions(data):
    """Informational lowest-priority exceptions, not hard-rule failures."""
    exceptions=[]
    if not data.get('result'):return exceptions
    for t,(rec,row) in enumerate(zip(data['days'],data['result'])):
        if row is None:continue
        special=date.fromisoformat(rec['date']).weekday()>=5 or rec['holiday']
        if special:continue
        previous=data['result'][t-1] if t else data['history'][-1]['shifts']
        if previous is None:continue
        for p in range(2):
            if previous[p]=='OFF' and row[p] in ('E','MD'):
                exceptions.append({'name':data['names'][p],'date':rec['date'],'shift':row[p]})
    return exceptions

def validate(data):
    """Independent ordinary-Python check, not a second rendering of CP constraints."""
    errors = []
    result = data['result']
    if result is None:
        return ['근무표 없음']
    for t, rec in enumerate(data['days']):
        d = date.fromisoformat(rec['date'])
        row = result[t]
        if row is None:
            errors.append(f'{d} 근무 미생성')
            continue
        if any(c not in CODES for c in row): errors.append(f'{d} 코드')
        if sum(c != 'OFF' for c in row) < rec['coverage']: errors.append(f'{d} 인원')
        special = d.weekday() >= 5 or rec['holiday']
        if d.weekday()==2 and not special and 'OFF' in row:
            errors.append(f'{d} 수요일 2인 근무 필수')
        if special:
            valid = sorted(row) in (['MD','OFF'], ['D','E']) if data['weekend_pair'] else sorted(row)==['MD','OFF']
            if not valid: errors.append(f'{d} 주말 MD / 허용된 D/E')
        if 'OFF' not in row and sorted(row) != ['D','E']: errors.append(f'{d} D/E 배치')
        if tuple(row) not in {('D','E'),('E','D'),('MD','OFF'),('OFF','MD')}:
            errors.append(f'{d} OFF 상대는 반드시 MD')
        if 'E' in row and 'D' not in row: errors.append(f'{d} E의 상대 D 누락')
        for p in range(2):
            if rec['fixed'][p] and row[p] != rec['fixed'][p]: errors.append(f'{d} 고정')
    for p in range(2):
        seq = [r['shifts'][p] for r in data['history']] + [r[p] if r else '' for r in result]
        for t in range(5,len(seq)):
            a,b = seq[t-1],seq[t]
            rec=data['days'][t-5]
            special=date.fromisoformat(rec['date']).weekday()>=5 or rec['holiday']
            if b and a == 'E' and b not in ('E','OFF'): errors.append(f'{p} {rec["date"]} E 다음날 D/MD 금지')
            window = seq[t-5:t+1]
            if all(window) and 'OFF' not in window: errors.append(f'{p} {t} 6연근')
        for target in data['targets']:
            ix = [t for t,r in enumerate(data['days']) if r['date'].startswith(f'{target["year"]}-{target["month"]:02d}')]
            if all(result[t] for t in ix) and sum(result[t][p]=='OFF' for t in ix) != target['off']: errors.append(f'{p} 휴무 수')
            if all(result[t] for t in ix) and sum(result[t][p]=='MD' for t in ix) != sum(result[t][1-p]=='OFF' for t in ix):
                errors.append(f'{p} MD 횟수와 상대 OFF 횟수 불일치')
    for target in data['targets']:
        ix=[t for t,r in enumerate(data['days']) if r['date'].startswith(f'{target["year"]}-{target["month"]:02d}')]
        if all(result[t] for t in ix):
            for c in ('D','E'):
                if abs(sum(result[t][0]==c for t in ix)-sum(result[t][1]==c for t in ix))>3:
                    errors.append(f'{c} 월별 차이 3일 초과')
    return errors
