from __future__ import annotations
import calendar
import copy
from datetime import date,datetime
import json
import os
from pathlib import Path
from .domain import COLORS,ensure_month,counts,complete,inspect_month,minimum_off
from .storage import default_state

def export_excel(state,keys,path):
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill,Font,Alignment,Border,Side
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.utils import get_column_letter
    wb=Workbook();wb.remove(wb.active)
    metadata=wb.create_sheet('_DuoRoster');metadata.append(['DuoRoster','1'])
    metadata.append(['settings',json.dumps(state['settings'],ensure_ascii=False)])
    for key in keys:
        m=ensure_month(state,key)
        metadata.append([key,json.dumps(m,ensure_ascii=False)])
        s=wb.create_sheet(key)
        s.sheet_view.showGridLines=False
        year,month=map(int,key.split('-'))
        offset=date(year,month,1).weekday();weeks=(offset+len(m['days'])+6)//7
        last=10+weeks*4
        for col in 'ABCDEFG':s.column_dimensions[col].width=26
        for row in s.iter_rows(min_row=1,max_row=last+9,max_col=7):
            for cell in row:cell.font=Font(name='맑은 고딕',size=11);cell.alignment=Alignment(vertical='center')
        s['A2']=f'{year}년 {month}월 근무표';s['A2'].font=Font(name='맑은 고딕',size=22,bold=True)
        report=inspect_month(state,key)
        s['A3']='수정 중: '+report['errors'][0] if report['errors'] else '필수 규칙 확인 완료'
        s['A4']='D 데이 / E 이브닝 / MD 단독 근무 / OFF 휴무'
        headers=['직원','D(일)','E(일)','MD(일)','OFF(일)','체류시간(h)','실근로시간(h)']
        for i,v in enumerate(headers,1):s.cell(6,i,v)
        for p,name in enumerate(state['settings']['names']):
            r=7+p;s.cell(r,1,name)
            if complete(m):
                for col,code in enumerate(('D','E','MD','OFF'),2):
                    name_escaped=name.replace('~','~~').replace('*','~*').replace('?','~?').replace('"','""')
                    s.cell(r,col,f'=COUNTIF(A11:G{last},"{name_escaped} {code}")')
                s.cell(r,6,f'=(B{r}+C{r})*8.5+D{r}*9')
                breaks=state['settings'].get('breaks',[None]*3)
                if all(v is not None for v in breaks):s.cell(r,7,f'=F{r}-(B{r}*{breaks[0]}+C{r}*{breaks[1]}+D{r}*{breaks[2]})/60')
                else:s.cell(r,7,'휴게 미입력')
                s.cell(r,6).number_format='0.0';s.cell(r,7).number_format='0.0'
        for i,v in enumerate(('월','화','수','목','금','토','일'),1):s.cell(10,i,v)
        border=Side(style='thin',color='8492A6')
        for rec in m['days']:
            d=date.fromisoformat(rec['date']);index=offset+d.day-1
            r=11+(index//7)*4;c=index%7+1
            s.cell(r,c,d).number_format='d'
            s.cell(r,c).fill=PatternFill('solid',fgColor='F3F5F8')
            s.cell(r,c).font=Font(name='맑은 고딕',size=15,bold=True,color='A44747' if d.weekday()>=5 or rec['holiday'] else '253347')
            pair=m['result'].get(rec['date'])
            for p,name in enumerate(state['settings']['names']):
                code=pair[p] if pair else '미배정'
                cell=s.cell(r+1+p,c,f'{name} {code}')
                cell.font=Font(name='맑은 고딕',size=15,bold=True,color='1C2D3B')
                cell.border=Border(top=border,bottom=border,left=border,right=border)
                if code in COLORS:cell.fill=PatternFill('solid',fgColor=COLORS[code][1:])
                s.row_dimensions[r+1+p].height=36
            s.cell(r+3,c,rec.get('holiday_name','') if rec['holiday'] else '')
        for row in (6,10):
            s.row_dimensions[row].height=30
            for cell in s[row][:7]:
                cell.fill=PatternFill('solid',fgColor='33465F');cell.font=Font(name='맑은 고딕',size=12,bold=True,color='FFFFFF')
                cell.alignment=Alignment(horizontal='center',vertical='center')
        for code,color in COLORS.items():
            s.conditional_formatting.add(f'A11:G{last}',FormulaRule(formula=[f'RIGHT(A11,{len(code)+1})=" {code}"'],fill=PatternFill('solid',fgColor=color[1:])))
        s.cell(last+2,1,f'각자 휴무 목표 {m["off_goal"]}일 / D 08:00~16:30 / E 11:00~19:30 / MD 08:00~17:00')
        s.cell(last+3,1,'체류시간은 휴게 포함. 실근로시간은 설정한 휴게시간을 제외합니다.')
        s.cell(last+4,1,'월초 경계: '+('검사 완료' if report['boundary_complete'] else '전월 기록 미입력으로 미완료'))
        if report['exceptions']:s.cell(last+5,1,'휴무 후 D 선호 예외: '+', '.join(r['date'][5:]+' '+r['name']+' '+r['shift'] for r in report['exceptions']))
        s.freeze_panes='A11';s.sheet_properties.pageSetUpPr.fitToPage=True
        s.page_setup.orientation='landscape';s.page_setup.paperSize=s.PAPERSIZE_A4
        s.page_setup.fitToWidth=1;s.page_setup.fitToHeight=1
        s.print_area=f'A1:G{last+5}'
    metadata.sheet_state='hidden'
    wb.active=1
    wb.save(path)

def import_excel(path):
    from openpyxl import load_workbook
    wb=load_workbook(path,data_only=False)
    state=default_state()
    try:
        if '_DuoRoster' in wb.sheetnames:
            rows=list(wb['_DuoRoster'].values)
            if rows[0][:2]!=('DuoRoster','1'):raise ValueError('지원하지 않는 근무표 형식입니다.')
            state['settings']=json.loads(rows[1][1])
            for key,raw,*_ in rows[2:]:state['months'][key]=json.loads(raw)
        elif {'설정','날짜입력'}<=set(wb.sheetnames):
            s=wb['설정'];state['settings']['names']=[str(s['B7'].value),str(s['B8'].value)]
            state['settings']['breaks']=[s[f'B{r}'].value for r in (9,10,11)]
            overrides={}
            for row in range(16,28):
                key=s[f'A{row}'].value
                if isinstance(key,str) and len(key)==7:
                    overrides[key]=s[f'D{row}'].value if s[f'E{row}'].value is not None else None
            for row in wb['날짜입력'].iter_rows(min_row=6,max_col=9,values_only=True):
                if not row[0]:continue
                d=row[0].date() if isinstance(row[0],datetime) else row[0]
                if not isinstance(d,date):raise ValueError('날짜입력의 날짜를 확인하세요.')
                key=d.strftime('%Y-%m');m=ensure_month(state,key)
                rec=next(r for r in m['days'] if r['date']==d.isoformat())
                rec.update(holiday=int(row[2] or 0),holiday_name=str(row[3] or ''),
                           fixed=[str(v or '') for v in row[4:6]],wish=[int(v or 0) for v in row[6:8]],coverage=int(row[8] or 1))
            for key,m in state['months'].items():
                m['off_goal']=int(overrides.get(key) or minimum_off(m['days']))
        else:raise ValueError('DuoRoster에서 저장한 파일 또는 이전 근무표 양식만 불러올 수 있습니다.')
        # Read visible cells so manual Excel edits are respected, not stale metadata.
        for key,m in state['months'].items():
            if key not in wb.sheetnames:continue
            s=wb[key];first=date.fromisoformat(m['days'][0]['date'])
            m['result']={}
            for rec in m['days']:
                d=date.fromisoformat(rec['date']);index=first.weekday()+d.day-1
                r=12+(index//7)*4;c=index%7+1
                values=[s.cell(r+p,c).value for p in range(2)]
                pair=[str(v or '').rsplit(' ',1)[-1] for v in values]
                if all(v in COLORS for v in pair):m['result'][rec['date']]=pair
            m['status']='draft'
        return state
    finally:wb.close()

def export_pdf(state,keys,path):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4,landscape
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'malgun.ttf'
    if not font_path.exists():raise ValueError('한국어 PDF에 필요한 맑은 고딕 글꼴이 없습니다.')
    if 'DuoKorean' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('DuoKorean',str(font_path)))
    page_w,page_h=landscape(A4);pdf=canvas.Canvas(str(path),pagesize=(page_w,page_h))
    for key in keys:
        m=ensure_month(state,key);year,month=map(int,key.split('-'))
        offset=date(year,month,1).weekday();weeks=(offset+len(m['days'])+6)//7
        margin=28;cell_w=(page_w-2*margin)/7;cell_h=min(70,(page_h-160)/weeks)
        top=page_h-110
        pdf.setFont('DuoKorean',20);pdf.drawString(margin,page_h-38,f'{year}년 {month}월 근무표')
        pdf.setFont('DuoKorean',10)
        summary=[]
        for p,name in enumerate(state['settings']['names']):
            c=counts(m,p)
            summary.append(name+': '+(' / '.join(f'{v} {c[v]}' for v in ('D','E','MD','OFF')) if c else '미배정'))
        pdf.drawString(margin,page_h-60,'     '.join(summary))
        for col,text in enumerate(('월','화','수','목','금','토','일')):
            pdf.setFillColor(HexColor('#33465F'));pdf.rect(margin+col*cell_w,top,cell_w,22,fill=1,stroke=0)
            pdf.setFillColor(HexColor('#FFFFFF'));pdf.drawCentredString(margin+(col+.5)*cell_w,top+7,text)
        for rec in m['days']:
            d=date.fromisoformat(rec['date']);index=offset+d.day-1
            x=margin+(index%7)*cell_w;y=top-(index//7+1)*cell_h
            pdf.setStrokeColor(HexColor('#A1ADBA'));pdf.setFillColor(HexColor('#F3F5F8'));pdf.rect(x,y,cell_w,cell_h,fill=1,stroke=1)
            pdf.setFillColor(HexColor('#A44747' if d.weekday()>=5 or rec['holiday'] else '#253347'))
            pdf.setFont('DuoKorean',10);pdf.drawString(x+5,y+cell_h-13,str(d.day))
            pair=m['result'].get(rec['date'])
            for p,name in enumerate(state['settings']['names']):
                code=pair[p] if pair else '미배정';height=(cell_h-20)/2
                line_y=y+(1-p)*height
                pdf.setFillColor(HexColor(COLORS.get(code,'#FFFFFF')));pdf.rect(x+1,line_y+1,cell_w-2,height-1,fill=1,stroke=0)
                pdf.setFillColor(HexColor('#1C2D3B'));pdf.setFont('DuoKorean',10)
                pdf.drawString(x+5,line_y+height/2-3,f'{name} {code}')
        pdf.setFillColor(HexColor('#253347'));pdf.setFont('DuoKorean',9)
        pdf.drawString(margin,36,'D 08:00~16:30    E 11:00~19:30    MD 08:00~17:00    OFF 휴무')
        report=inspect_month(state,key)
        pdf.drawString(margin,22,'수정 중: '+report['errors'][0] if report['errors'] else '필수 규칙 확인 완료 / 전월 기록이 없는 경우 월초 경계는 미검증')
        pdf.showPage()
    pdf.save()
