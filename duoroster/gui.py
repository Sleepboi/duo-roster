from __future__ import annotations
import calendar
import copy
from datetime import date
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk,messagebox,filedialog
from . import __version__,RELEASE_REPOSITORY
from .domain import (COLORS,ensure_month,next_month,minimum_off,counts,complete,
                     inspect_month,edit_shift,generate,yearly_counts)
from .storage import Store
from .exporting import export_excel,export_pdf,import_excel
from .updating import check_update,download_update,launch_update

INK='#253347';BG='#F4F6FA';NAVY='#33465F'
SHIFT_NAMES={'D':'데이','E':'이브닝','MD':'엠디','OFF':'휴무'}

class App(tk.Tk):
    def __init__(self,store=None,state=None):
        super().__init__()
        self.title('두 사람 근무표')
        import sys
        icon=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'assets'/'duoroster.ico'
        if icon.exists():
            try:self.iconbitmap(str(icon))
            except tk.TclError:pass
        width=min(1380,self.winfo_screenwidth()-70);height=min(960,self.winfo_screenheight()-100)
        self.geometry(f'{width}x{height}+30+30');self.minsize(min(1120,width),min(720,height))
        self.configure(bg=BG)
        self.store=store or Store();self.state=state or self.store.load()
        self.key=date.today().strftime('%Y-%m');self.undo_stack=[];self.revision=0;self.busy=False
        self.jobs=queue.Queue();self.update_info=None;self.latest_report=None
        self.option_add('*Font',('맑은 고딕',11))
        style=ttk.Style(self);style.theme_use('clam')
        style.configure('TButton',font=('맑은 고딕',11),padding=(10,7))
        style.configure('TCombobox',padding=5)
        self._build()
        ensure_month(self.state,self.key)
        self.render();self.after(100,self._poll)
        self.protocol('WM_DELETE_WINDOW',self._close)
        if self.state['settings'].get('check_updates',True):self.after(3000,lambda:self.check_updates(False))

    def _build(self):
        menu=tk.Menu(self)
        filemenu=tk.Menu(menu,tearoff=False)
        filemenu.add_command(label='기존 엑셀 불러오기',command=self.load_excel)
        filemenu.add_command(label='엑셀로 저장',command=lambda:self.export('xlsx'))
        filemenu.add_command(label='PDF로 저장',command=lambda:self.export('pdf'))
        filemenu.add_separator();filemenu.add_command(label='기록 백업하기',command=self.backup)
        filemenu.add_command(label='백업에서 복원',command=self.restore)
        filemenu.add_command(label='저장 폴더 열기',command=lambda:os.startfile(self.store.directory))
        menu.add_cascade(label='파일',menu=filemenu)
        menu.add_command(label='규칙 보기',command=self.show_rules)
        menu.add_command(label='업데이트 확인',command=lambda:self.check_updates(True))
        self.config(menu=menu)
        top=tk.Frame(self,bg=BG);top.pack(fill='x',padx=22,pady=(18,8))
        tk.Label(top,text='두 사람 근무표',font=('맑은 고딕',22,'bold'),fg=INK,bg=BG).pack(side='left')
        self.saved_label=tk.Label(top,text='자동 저장',fg='#527568',bg=BG);self.saved_label.pack(side='left',padx=20)
        self.update_button=ttk.Button(top,text='업데이트 확인',command=lambda:self.check_updates(True));self.update_button.pack(side='right')
        tk.Label(top,text='v'+__version__,fg='#718096',bg=BG).pack(side='right',padx=12)
        nav=tk.Frame(self,bg=BG);nav.pack(fill='x',padx=22,pady=(2,12))
        ttk.Button(nav,text='이전 달',command=lambda:self.navigate(-1)).pack(side='left')
        self.year_var=tk.StringVar();self.month_var=tk.StringVar()
        self.year_box=ttk.Combobox(nav,textvariable=self.year_var,width=7,state='readonly',values=list(range(2020,2101)))
        self.year_box.pack(side='left',padx=(16,4));self.year_box.bind('<<ComboboxSelected>>',self.select_period)
        tk.Label(nav,text='년',bg=BG,fg=INK).pack(side='left')
        self.month_box=ttk.Combobox(nav,textvariable=self.month_var,width=4,state='readonly',values=list(range(1,13)))
        self.month_box.pack(side='left',padx=(8,4));self.month_box.bind('<<ComboboxSelected>>',self.select_period)
        tk.Label(nav,text='월',bg=BG,fg=INK).pack(side='left',padx=(0,16))
        ttk.Button(nav,text='다음 달',command=lambda:self.navigate(1)).pack(side='left')
        ttk.Button(nav,text='이름·휴게시간',command=self.settings).pack(side='right')
        ttk.Button(nav,text='되돌리기',command=self.undo).pack(side='right',padx=8)
        body=tk.Frame(self,bg=BG);body.pack(fill='both',expand=True,padx=22)
        side_wrap=tk.Frame(body,bg='white',width=275);side_wrap.pack(side='right',fill='y',padx=(14,0));side_wrap.pack_propagate(False)
        side_canvas=tk.Canvas(side_wrap,bg='white',highlightthickness=0,width=228)
        side_scroll=ttk.Scrollbar(side_wrap,orient='vertical',command=side_canvas.yview)
        side_scroll.pack(side='right',fill='y');side_canvas.pack(side='left',fill='both',expand=True)
        side_canvas.configure(yscrollcommand=side_scroll.set)
        self.side=tk.Frame(side_canvas,bg='white',padx=12,pady=14)
        side_item=side_canvas.create_window((0,0),window=self.side,anchor='nw')
        self.side.bind('<Configure>',lambda e:side_canvas.configure(scrollregion=side_canvas.bbox('all')))
        side_canvas.bind('<Configure>',lambda e:side_canvas.itemconfigure(side_item,width=e.width))
        tk.Label(self.side,text='이번 달 휴무',font=('맑은 고딕',15,'bold'),bg='white',fg=INK).pack(anchor='w')
        offbox=tk.Frame(self.side,bg='white');offbox.pack(fill='x',pady=(10,4))
        tk.Label(offbox,text='각자',bg='white',fg=INK).pack(side='left')
        self.off_var=tk.StringVar()
        self.off_spin=ttk.Spinbox(offbox,from_=8,to=31,width=5,textvariable=self.off_var,command=self.change_goal)
        self.off_spin.pack(side='left',padx=10);self.off_spin.bind('<Return>',self.change_goal);self.off_spin.bind('<FocusOut>',self.change_goal)
        tk.Label(offbox,text='일',bg='white',fg=INK).pack(side='left')
        self.base_label=tk.Label(self.side,bg='white',fg='#64748B',anchor='w',justify='left');self.base_label.pack(fill='x',pady=(0,15))
        self.generate_button=tk.Button(self.side,text='근무표 만들기',command=self.make,
             bg='#2E7055',fg='white',activebackground='#245B45',activeforeground='white',font=('맑은 고딕',14,'bold'),relief='flat',pady=11)
        self.generate_button.pack(fill='x')
        self.next_var=tk.BooleanVar(value=True)
        self.next_check=tk.Checkbutton(self.side,text='다음 달도 함께 계산',variable=self.next_var,bg='white',anchor='w',font=('맑은 고딕',10))
        self.next_check.pack(fill='x',pady=(6,18))
        self.summary_frame=tk.Frame(self.side,bg='white');self.summary_frame.pack(fill='x')
        guide=tk.Frame(self.side,bg='#F0F3F8',padx=10,pady=9);guide.pack(fill='x',pady=(6,0))
        tk.Label(guide,text='표시 안내',bg='#F0F3F8',fg=INK,font=('맑은 고딕',11,'bold')).pack(anchor='w')
        tk.Label(guide,text='고정  자동 편성해도 유지',bg=NAVY,fg='white',padx=5,pady=3,font=('맑은 고딕',10,'bold')).pack(anchor='w',pady=(6,4))
        tk.Label(guide,text='복귀 예외  휴무 후 D 대신 E/MD\n허용되는 선호 조건 예외입니다.',bg='#FFF1CC',fg='#6F4800',justify='left',padx=5,pady=5,font=('맑은 고딕',10)).pack(anchor='w')
        tk.Frame(self.side,height=1,bg='#DFE5EC').pack(fill='x',pady=15)
        ttk.Button(self.side,text='엑셀로 저장',command=lambda:self.export('xlsx')).pack(fill='x')
        ttk.Button(self.side,text='PDF·인쇄용 저장',command=lambda:self.export('pdf')).pack(fill='x',pady=6)
        ttk.Button(self.side,text='연간 실적 보기',command=self.annual).pack(fill='x',pady=(8,6))
        ttk.Button(self.side,text='전월 마지막 5일 입력',command=self.history).pack(fill='x',pady=(0,6))
        ttk.Button(self.side,text='이달 실제 근무 확정',command=self.confirm_actual).pack(fill='x')
        tk.Label(self.side,text='날짜의 근무 칸을 눌러\n수정하거나 고정하세요.',fg='#64748B',bg='white',justify='left',font=('맑은 고딕',10)).pack(anchor='w',pady=18)
        calendar_wrap=tk.Frame(body,bg=BG);calendar_wrap.pack(side='left',fill='both',expand=True)
        self.calendar_canvas=tk.Canvas(calendar_wrap,bg=BG,highlightthickness=0)
        calendar_scroll=ttk.Scrollbar(calendar_wrap,orient='vertical',command=self.calendar_canvas.yview)
        calendar_scroll.pack(side='right',fill='y');self.calendar_canvas.pack(side='left',fill='both',expand=True)
        self.calendar_canvas.configure(yscrollcommand=calendar_scroll.set)
        self.side_canvas=side_canvas
        self.bind('<MouseWheel>',self.scroll_panel)
        self.cal=tk.Frame(self.calendar_canvas,bg='#D7DFE9')
        self.calendar_min_height=580
        self.calendar_item=self.calendar_canvas.create_window((0,0),window=self.cal,anchor='nw')
        self.cal.bind('<Configure>',lambda e:self.calendar_canvas.configure(scrollregion=self.calendar_canvas.bbox('all')))
        self.calendar_canvas.bind('<Configure>',lambda e:self.calendar_canvas.itemconfigure(self.calendar_item,width=e.width,height=max(e.height,self.calendar_min_height)))
        bottom=tk.Frame(self,bg=BG);bottom.pack(fill='x',padx=22,pady=(10,14))
        self.report_label=tk.Label(bottom,bg=BG,fg=INK,justify='left',anchor='w',font=('맑은 고딕',10))
        self.report_label.pack(side='left',fill='x',expand=True)
        ttk.Button(bottom,text='검사 상세',command=self.details).pack(side='right')
        for code in ('D','E','MD','OFF'):
            tk.Label(bottom,text=code,bg=COLORS[code],fg=INK,padx=12,pady=4,font=('맑은 고딕',10,'bold')).pack(side='right',padx=2)

    def scroll_panel(self,event):
        for panel in (self.side_canvas,self.calendar_canvas):
            if panel.winfo_rootx()<=event.x_root<panel.winfo_rootx()+panel.winfo_width() and panel.winfo_rooty()<=event.y_root<panel.winfo_rooty()+panel.winfo_height():
                panel.yview_scroll(-int(event.delta/120)*2,'units')
                return 'break'

    def mutate(self,callback):
        if self.busy:return
        previous=copy.deepcopy(self.state)
        try:
            callback();self.store.save(self.state)
        except Exception as exc:
            self.state=previous;messagebox.showerror('변경하지 못했습니다',str(exc),parent=self);self.render();return
        self.undo_stack.append(previous);self.undo_stack=self.undo_stack[-25:]
        self.revision+=1;self.render()

    def navigate(self,delta):
        if self.busy:return
        self.key=next_month(self.key,delta);ensure_month(self.state,self.key);self.render()

    def select_period(self,event=None):
        if self.busy:return
        self.key=f'{int(self.year_var.get()):04d}-{int(self.month_var.get()):02d}'
        ensure_month(self.state,self.key);self.render()

    def change_goal(self,event=None):
        if self.busy:return
        m=ensure_month(self.state,self.key)
        try:
            goal=int(self.off_var.get())
            if goal==m['off_goal']:return
            if not minimum_off(m['days'])<=goal<=len(m['days']):raise ValueError(f'최소 휴무 {minimum_off(m["days"])}일 이상을 입력하세요.')
        except ValueError as exc:
            self.off_var.set(str(m['off_goal']));messagebox.showerror('휴무 일수',str(exc),parent=self);return
        self.mutate(lambda:m.update(off_goal=goal,status='draft'))

    def render(self):
        m=ensure_month(self.state,self.key);year,month=map(int,self.key.split('-'))
        self.year_var.set(str(year));self.month_var.set(str(month));self.off_var.set(str(m['off_goal']))
        self.base_label.config(text=f'기본 최소 {minimum_off(m["days"])}일\n필요한 추가 휴무를 포함하세요.')
        has_next=next_month(self.key) in self.state['months']
        self.next_check.config(state='normal' if has_next and not self.busy else 'disabled')
        self.latest_report=inspect_month(self.state,self.key)
        exceptions={(e['date'],e['name']) for e in self.latest_report['exceptions']}
        for child in self.summary_frame.winfo_children():child.destroy()
        for p,name in enumerate(self.state['settings']['names']):
            c=counts(m,p)
            tk.Label(self.summary_frame,text=name,bg='white',fg=INK,font=('맑은 고딕',15,'bold')).pack(anchor='w',pady=(6,5))
            tiles=tk.Frame(self.summary_frame,bg='white');tiles.pack(fill='x')
            for i,code in enumerate(('D','E','MD','OFF')):
                tile=tk.Frame(tiles,bg=COLORS[code],padx=6,pady=4)
                tile.grid(row=i//2,column=i%2,sticky='nsew',padx=2,pady=2)
                tiles.columnconfigure(i%2,weight=1,uniform='totals')
                tk.Label(tile,text=code,bg=COLORS[code],fg=INK,font=('맑은 고딕',12,'bold')).pack(anchor='w')
                tk.Label(tile,text=f'{c[code] if c else 0}일',bg=COLORS[code],fg=INK,font=('맑은 고딕',22,'bold')).pack(anchor='w')
            off_count=c['OFF'] if c else 0
            tk.Label(self.summary_frame,text=f'휴무 목표 {m["off_goal"]}일 · 현재 {off_count}일',bg='white',fg='#A44747' if off_count!=m['off_goal'] else '#35644F',font=('맑은 고딕',10,'bold')).pack(anchor='w',pady=(3,0))
            fixed_count=sum(bool(rec['fixed'][p]) for rec in m['days'])
            exception_count=sum(who==name for _,who in exceptions)
            status=tk.Frame(self.summary_frame,bg='white');status.pack(fill='x',pady=(4,10))
            tk.Label(status,text=f'고정 {fixed_count}일',bg=NAVY,fg='white',padx=6,pady=3,font=('맑은 고딕',10,'bold')).pack(side='left')
            if exception_count:
                tk.Button(status,text=f'복귀 예외 {exception_count}건',command=lambda who=name:self.return_exceptions(who),bg='#FFF1CC',fg='#6F4800',relief='flat',padx=6,pady=3,font=('맑은 고딕',10,'bold')).pack(side='left',padx=(4,0))
        for child in self.cal.winfo_children():child.destroy()
        offset=date(year,month,1).weekday();weeks=(offset+len(m['days'])+6)//7
        self.calendar_min_height=45+weeks*156
        self.calendar_canvas.itemconfigure(self.calendar_item,height=max(self.calendar_canvas.winfo_height(),self.calendar_min_height))
        for c,title in enumerate(('월','화','수','목','금','토','일')):
            self.cal.columnconfigure(c,weight=1,uniform='days')
            tk.Label(self.cal,text=title,bg=NAVY,fg='white',font=('맑은 고딕',12,'bold'),pady=9).grid(row=0,column=c,sticky='nsew',padx=1)
        for row in range(1,7):self.cal.rowconfigure(row,weight=1 if row<=weeks else 0,uniform='weeks' if row<=weeks else '')
        for rec in m['days']:
            d=date.fromisoformat(rec['date']);index=offset+d.day-1;r=index//7+1;c=index%7
            day=tk.Frame(self.cal,bg='white',padx=3,pady=2);day.grid(row=r,column=c,sticky='nsew',padx=1,pady=1)
            day.columnconfigure(0,weight=1)
            holiday=bool(rec['holiday']) or d.weekday()>=5
            top=str(d.day)+((' '+rec.get('holiday_name','')[:6]) if rec['holiday'] else '')
            tk.Button(day,text=top,command=lambda v=rec:self.day_settings(v),bg='white',fg='#A44747' if holiday else '#455970',relief='flat',anchor='w',font=('맑은 고딕',11,'bold')).grid(row=0,column=0,sticky='ew')
            pair=m['result'].get(rec['date'])
            for p,name in enumerate(self.state['settings']['names']):
                code=pair[p] if pair else '-'
                color=COLORS.get(code,'#F2F4F8')
                card=tk.Frame(day,bg=color,highlightthickness=2,highlightbackground=NAVY if rec['fixed'][p] else color)
                card.grid(row=1+p,column=0,sticky='nsew',pady=2)
                head=tk.Frame(card,bg=color,height=24);head.pack(fill='x',padx=3,pady=(2,0));head.pack_propagate(False)
                name_label=tk.Label(head,text=name,bg=color,fg=INK,font=('맑은 고딕',10,'bold'));name_label.pack(side='left')
                edit_targets=[card,head,name_label]
                if rec['fixed'][p]:
                    fixed_label=tk.Label(head,text='고정',bg=NAVY,fg='white',padx=3,font=('맑은 고딕',9,'bold'));fixed_label.pack(side='right')
                    edit_targets.append(fixed_label)
                if (rec['date'],name) in exceptions:
                    tk.Button(head,text='예외',command=lambda who=name:self.return_exceptions(who),bg='#FFF1CC',fg='#6F4800',relief='flat',borderwidth=0,padx=3,pady=0,font=('맑은 고딕',9,'bold')).pack(side='right',padx=2)
                if rec['wish'][p]:tk.Label(head,text='희망',bg='#F0F3F8',fg=NAVY,padx=3,font=('맑은 고딕',9,'bold')).pack(side='right')
                button=tk.Button(card,text=code,bg=color,fg='#1C2D3B',activebackground=color,
                    font=('맑은 고딕',18,'bold'),relief='flat',borderwidth=0,pady=0,command=lambda v=rec,who=p:self.shift_dialog(v,who))
                button.pack(fill='both',expand=True)
                for widget in edit_targets:
                    widget.bind('<Button-1>',lambda event,v=rec,who=p:self.shift_dialog(v,who))
                day.rowconfigure(1+p,weight=1,uniform='person',minsize=76)
        report=self.latest_report
        self.cal.update_idletasks()
        self.calendar_min_height=max(self.calendar_min_height,self.cal.winfo_reqheight())
        self.calendar_canvas.itemconfigure(self.calendar_item,height=max(self.calendar_canvas.winfo_height(),self.calendar_min_height))
        if report['errors']:
            self.report_label.config(text='수정 중 · '+report['errors'][0],fg='#A44747')
        else:
            boundary='월초 검사 완료' if report['boundary_complete'] else '전월 기록 없음 · 월초 검사 미완료'
            self.report_label.config(text=f'필수 규칙 확인 완료 · {boundary}\n복귀 D 선호 예외 {len(report["exceptions"])}건',fg='#35644F')
        self.saved_label.config(text='계산 중...' if self.busy else '자동 저장 · '+('실제 근무 확정' if m['status']=='actual' else '계획'))

    def return_exceptions(self,name):
        entries=[e for e in self.latest_report['exceptions'] if e['name']==name]
        lines=[f'{e["date"]}  OFF → {e["shift"]}' for e in entries]
        win=self.dialog('복귀 선호 예외',650,440)
        tk.Label(win,text=f'{name} · 복귀 선호 예외 {len(entries)}건',font=('맑은 고딕',16,'bold'),fg=INK).pack(anchor='w',padx=20,pady=(18,10))
        tk.Label(win,text='허용되는 예외 · 필수 규칙 위반 아님',bg='#FFF1CC',fg='#6F4800',font=('맑은 고딕',12,'bold'),padx=12,pady=9).pack(fill='x',padx=20)
        tk.Label(win,text='휴무 다음 평일에는 D를 우선하지만, 다른 조건을 맞추기 위해\nE 또는 MD로 복귀한 날짜입니다.',justify='left',font=('맑은 고딕',12)).pack(anchor='w',padx=20,pady=12)
        from tkinter.scrolledtext import ScrolledText
        listing=ScrolledText(win,font=('맑은 고딕',12),height=6,wrap='word',relief='flat',padx=10,pady=8)
        listing.pack(fill='both',expand=True,padx=20)
        listing.insert('1.0','\n'.join(lines));listing.config(state='disabled')
        ttk.Button(win,text='닫기',command=win.destroy).pack(pady=14)

    def shift_dialog(self,rec,person):
        if self.busy:return
        win=self.dialog(f'{rec["date"]} · {self.state["settings"]["names"][person]}',450,420)
        tk.Label(win,text='근무를 선택하세요',font=('맑은 고딕',15,'bold')).pack(pady=14)
        fixed=tk.BooleanVar(value=True)
        tk.Checkbutton(win,text='이 근무를 고정하고 재계산에도 유지',variable=fixed).pack(pady=(0,12))
        grid=tk.Frame(win);grid.pack(fill='x',padx=18)
        def apply(code):
            def change():edit_shift(self.state,self.key,rec['date'],person,code,fixed.get())
            self.mutate(change);win.destroy()
        for i,code in enumerate(('D','E','MD','OFF')):
            tk.Button(grid,text=code,bg=COLORS[code],font=('맑은 고딕',16,'bold'),height=2,command=lambda v=code:apply(v)).grid(row=i//2,column=i%2,sticky='ew',padx=4,pady=4)
        grid.columnconfigure(0,weight=1);grid.columnconfigure(1,weight=1)
        actions=tk.Frame(win);actions.pack(fill='x',padx=18,pady=12)
        def unlock():
            self.mutate(lambda:rec['fixed'].__setitem__(person,''));win.destroy()
        def wish():
            self.mutate(lambda:rec['wish'].__setitem__(person,0 if rec['wish'][person] else 1));win.destroy()
        ttk.Button(actions,text='고정 해제',command=unlock).pack(side='left')
        ttk.Button(actions,text='희망 휴무 '+('해제' if rec['wish'][person] else '설정'),command=wish).pack(side='right')

    def day_settings(self,rec):
        if self.busy:return
        win=self.dialog(rec['date']+' 날짜 설정',430,290)
        holiday=tk.BooleanVar(value=bool(rec['holiday']));name=tk.StringVar(value=rec.get('holiday_name',''))
        tk.Checkbutton(win,text='사업장 공휴일로 적용',variable=holiday).pack(anchor='w',padx=20,pady=(20,8))
        ttk.Entry(win,textvariable=name,width=30).pack(padx=20,fill='x')
        tk.Label(win,text='공휴일 이름은 달력에 표시됩니다.').pack(anchor='w',padx=20,pady=8)
        def apply():
            def change():
                rec['holiday']=int(holiday.get());rec['holiday_name']=name.get().strip()
                m=ensure_month(self.state,self.key);m['off_goal']=max(m['off_goal'],minimum_off(m['days']));m['status']='draft'
            self.mutate(change);win.destroy()
        ttk.Button(win,text='적용',command=apply).pack(pady=15)

    def dialog(self,title,width=650,height=450):
        win=tk.Toplevel(self);win.title(title)
        x=max(0,self.winfo_rootx()+(self.winfo_width()-width)//2)
        y=max(0,self.winfo_rooty()+(self.winfo_height()-height)//2)
        win.geometry(f'{width}x{height}+{x}+{y}');win.transient(self);win.grab_set()
        win.bind('<Escape>',lambda event:win.destroy())
        return win

    def settings(self):
        if self.busy:return
        win=self.dialog('이름·휴게시간',500,400)
        names=[tk.StringVar(value=v) for v in self.state['settings']['names']]
        breaks=[tk.StringVar(value='' if v is None else str(v)) for v in self.state['settings'].get('breaks',[None]*3)]
        frame=tk.Frame(win,padx=24,pady=20);frame.pack(fill='both',expand=True)
        for i,var in enumerate(names):
            tk.Label(frame,text=f'직원 {i+1} 이름').grid(row=i,column=0,sticky='w',pady=8);ttk.Entry(frame,textvariable=var).grid(row=i,column=1,padx=12)
        for i,(code,var) in enumerate(zip(('D','E','MD'),breaks),3):
            tk.Label(frame,text=f'{code} 휴게시간(분)').grid(row=i,column=0,sticky='w',pady=6);ttk.Entry(frame,textvariable=var,width=8).grid(row=i,column=1,sticky='w',padx=12)
        tk.Label(frame,text='휴게시간이 비어 있으면 실근로시간을 계산하지 않습니다.',font=('맑은 고딕',9)).grid(row=6,column=0,columnspan=2,pady=10)
        def apply():
            values=[v.get().strip() for v in names]
            try:
                if not all(values) or values[0]==values[1]:raise ValueError('서로 다른 이름 두 개를 입력하세요.')
                rest=[int(v.get()) if v.get().strip() else None for v in breaks]
                if any(v is not None and not 0<=v<=limit for v,limit in zip(rest,(510,510,540))):raise ValueError('휴게시간 범위를 확인하세요.')
            except ValueError as exc:messagebox.showerror('입력 확인',str(exc),parent=win);return
            self.mutate(lambda:self.state['settings'].update(names=values,breaks=rest));win.destroy()
        ttk.Button(frame,text='저장',command=apply).grid(row=7,column=0,columnspan=2,pady=8)

    def _worker(self,function,callback,block=False):
        if block:
            self.busy=True;self.generate_button.config(state='disabled');self.render()
        def work():
            try:self.jobs.put((callback,function(),None,block))
            except Exception as exc:self.jobs.put((callback,None,str(exc),block))
        threading.Thread(target=work,daemon=True).start()

    def _poll(self):
        try:
            while True:
                callback,result,error,block=self.jobs.get_nowait()
                if block:self.busy=False;self.generate_button.config(state='normal');self.render()
                callback(result,error)
        except queue.Empty:pass
        self.after(100,self._poll)

    def make(self):
        if self.busy:return
        self.change_goal()
        snapshot=copy.deepcopy(self.state);key=self.key
        include=self.next_var.get() and next_month(key) in snapshot['months']
        revision=self.revision
        def done(result,error):
            if error:messagebox.showerror('계산하지 못했습니다',error,parent=self);return
            if not result['ok']:
                messagebox.showerror('조건을 함께 맞출 수 없습니다','고정 근무·휴무와 규칙을 확인해 주세요.\n\n'+'\n'.join(result['issues']),parent=self);return
            if revision!=self.revision:
                messagebox.showinfo('다시 계산해 주세요','계산 중 입력이 바뀌어 결과를 적용하지 않았습니다.',parent=self);return
            if not result['changes']:
                self.mutate(lambda:setattr(self,'state',result['state']))
                messagebox.showinfo('계산 완료','현재 배정이 조건을 만족합니다. 바뀌는 날짜가 없습니다.',parent=self);return
            self.review(result)
        self._worker(lambda:generate(snapshot,key,include),done,True)

    def review(self,result):
        win=self.dialog('바뀌는 날짜 확인',760,540)
        tk.Label(win,text=f'{len(result["changes"])}개 날짜 변경 · 복귀 D 선호 예외 {len(result["exceptions"])}건',font=('맑은 고딕',13,'bold')).pack(anchor='w',padx=18,pady=16)
        tree=ttk.Treeview(win,columns=('date','before','after'),show='headings',height=12)
        for col,title,width in [('date','날짜',115),('before','이전 배정',230),('after','새 배정',230)]:tree.heading(col,text=title);tree.column(col,width=width)
        for change in result['changes']:
            def desc(pair):return '미배정' if not pair else ' / '.join(f'{n} {v}' for n,v in zip(self.state['settings']['names'],pair))
            tree.insert('',tk.END,values=(change['date'],desc(change['before']),desc(change['after'])))
        tree.pack(fill='both',expand=True,padx=18)
        tk.Label(win,text='적용 후에도 되돌리기로 이전 배정으로 돌아갈 수 있습니다.').pack(pady=10)
        def apply():
            self.mutate(lambda:setattr(self,'state',result['state']));win.destroy()
        ttk.Button(win,text='이 배정 적용',command=apply).pack(pady=(0,16))

    def undo(self):
        if self.busy or not self.undo_stack:return
        previous=self.undo_stack.pop();self.store.save(previous);self.state=previous;self.revision+=1;self.render()

    def details(self):
        report=inspect_month(self.state,self.key)
        lines=report['errors'] or ['필수 규칙을 모두 만족합니다.']
        lines+=['','휴무 후 D 선호 예외:']+[f'{e["date"]} {e["name"]} {e["shift"]}' for e in report['exceptions']]
        if not report['boundary_complete']:lines+=['','직전 5일 근무가 없어 월초 경계 검사는 미완료입니다.']
        messagebox.showinfo('검사 결과','\n'.join(lines),parent=self)

    def show_rules(self):
        text=('필수 조건\n\n두 명 출근: D와 E 한 명씩\n한 명 OFF: 상대방 MD\n주말·공휴일: MD와 OFF\n공휴일이 아닌 수요일: 두 명 근무\n이브닝 다음날: E 또는 OFF\n연속근무: 최대 5일\n월별 휴무: 설정한 일수와 정확히 일치\n월별 D/E 차이: 각각 최대 3일\n\n선호 조건\n\n연간 실제 기록을 반영한 균형\n월·금 두 명, 화·목 한 명 우선\n고정하지 않은 기존 일정은 가능하면 유지\n휴무 후 평일 D 복귀는 가장 낮은 우선순위')
        messagebox.showinfo('근무표 규칙',text,parent=self)

    def confirm_actual(self):
        if self.busy:return
        report=inspect_month(self.state,self.key)
        if report['errors']:
            messagebox.showerror('확정할 수 없습니다','필수 규칙을 확인한 뒤 확정하세요.\n'+report['errors'][0],parent=self);return
        if messagebox.askyesno('실제 근무 확인',f'{self.key}의 배정이 실제 근무와 같은지 확인하셨나요?\n확정한 기록은 연간 균형 계산에 반영합니다.',parent=self):
            self.mutate(lambda:ensure_month(self.state,self.key).update(status='actual'))

    def history(self):
        if self.busy:return
        from datetime import timedelta
        first=date.fromisoformat(self.key+'-01')
        win=self.dialog('전월 마지막 5일 실제 근무',560,390)
        tk.Label(win,text='확인되지 않은 근무는 미입력으로 두세요.',font=('맑은 고딕',11)).pack(pady=15)
        grid=tk.Frame(win);grid.pack(padx=20)
        for c,title in enumerate(['날짜']+self.state['settings']['names']):tk.Label(grid,text=title,font=('맑은 고딕',11,'bold')).grid(row=0,column=c,padx=12,pady=8)
        entries=[]
        for row,back in enumerate(range(5,0,-1),1):
            d=(first-timedelta(days=back)).isoformat()
            old=self.state['months'].get(d[:7],{}).get('result',{}).get(d,['',''])
            variables=[tk.StringVar(value=v or '미입력') for v in old]
            tk.Label(grid,text=d).grid(row=row,column=0,pady=7)
            for p,var in enumerate(variables):ttk.Combobox(grid,textvariable=var,state='readonly',values=['미입력','D','E','MD','OFF'],width=10).grid(row=row,column=p+1,padx=12)
            entries.append((d,variables))
        def apply():
            def change():
                for d,variables in entries:
                    m=ensure_month(self.state,d[:7]);values=[v.get() if v.get()!='미입력' else '' for v in variables]
                    if any(values):m['result'][d]=values
                    else:m['result'].pop(d,None)
            self.mutate(change);win.destroy()
        ttk.Button(win,text='저장하고 월초 연결 검사',command=apply).pack(pady=20)

    def annual(self):
        totals,known=yearly_counts(self.state,int(self.key[:4]))
        lines=[f'{self.key[:4]}년 확정 실제 기록 {known}개월','']
        for name,c in zip(self.state['settings']['names'],totals):lines.append(name+'\n'+' / '.join(f'{code} {c[code]}일' for code in ('D','E','MD','OFF'))+'\n')
        lines.append('실제 근무로 확정하지 않은 계획은 누적 실적에 포함하지 않습니다.')
        messagebox.showinfo('연간 실제 근무','\n'.join(lines),parent=self)

    def export(self,kind):
        if self.busy:return
        path=filedialog.asksaveasfilename(parent=self,title='근무표 저장',initialfile=self.key+' 근무표.'+kind,defaultextension='.'+kind,filetypes=[(kind.upper(),'*.'+kind)])
        if not path:return
        try:
            (export_excel if kind=='xlsx' else export_pdf)(self.state,[self.key],path)
            messagebox.showinfo('저장 완료',str(path),parent=self)
        except Exception as exc:messagebox.showerror('저장하지 못했습니다',str(exc),parent=self)

    def load_excel(self):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self,title='기존 근무표 불러오기',filetypes=[('Excel','*.xlsx')])
        if not path:return
        try:incoming=import_excel(path)
        except Exception as exc:messagebox.showerror('불러오지 못했습니다',str(exc),parent=self);return
        if not messagebox.askyesno('기록 가져오기','같은 월의 기록은 가져온 엑셀 내용으로 바뀝니다.\n이전 기록은 자동 백업됩니다. 계속할까요?',parent=self):return
        def change():
            self.state['settings'].update(incoming['settings']);self.state['months'].update(incoming['months'])
        self.mutate(change)
        if incoming['months']:self.key=min(incoming['months']);self.render()

    def backup(self):
        path=filedialog.asksaveasfilename(parent=self,title='기록 백업',initialfile='근무표 기록 백업.json',defaultextension='.json',filetypes=[('근무 기록','*.json')])
        if path:
            try:self.store.export_backup(path,self.state);messagebox.showinfo('백업 완료',path,parent=self)
            except Exception as exc:messagebox.showerror('백업 실패',str(exc),parent=self)

    def restore(self):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self,title='백업에서 복원',initialdir=self.store.directory/'backups',filetypes=[('근무 기록','*.json')])
        if not path:return
        if not messagebox.askyesno('백업 복원','현재 기록을 백업한 뒤 선택한 기록으로 복원합니다. 계속할까요?',parent=self):return
        try:
            previous=copy.deepcopy(self.state);self.state=self.store.restore(path);self.undo_stack.append(previous);self.render()
        except Exception as exc:messagebox.showerror('복원 실패',str(exc),parent=self)

    def check_updates(self,manual=True):
        if self.update_info:
            self.offer_update();return
        self.update_button.config(state='disabled',text='버전 확인 중...')
        def done(info,error):
            self.update_button.config(state='normal',text='업데이트 확인')
            if error:
                if manual:messagebox.showinfo('업데이트 확인','인터넷 연결이나 GitHub 응답을 확인해 주세요. 근무표는 그대로 사용할 수 있습니다.\n'+error,parent=self)
                return
            if info:
                self.update_info=info;self.update_button.config(text='새 버전 '+info['version'])
                if manual:self.offer_update()
            elif manual:messagebox.showinfo('업데이트 확인','현재 사용할 수 있는 새 정식 버전이 없습니다.',parent=self)
        self._worker(check_update,done)

    def offer_update(self):
        if self.busy:return
        info=self.update_info
        if not info:return
        if not messagebox.askyesno('업데이트',f'새 버전 {info["version"]}을 설치할까요?\n현재 기록은 저장되며, 설치 후 앱이 다시 열립니다.\n\n'+info['notes'][:1200],parent=self):return
        self.store.save(self.state)
        def done(archive,error):
            if error:messagebox.showerror('업데이트하지 못했습니다',error,parent=self);return
            try:launch_update(archive,info['sha256'],self.store.directory/'updates')
            except Exception as exc:messagebox.showerror('업데이트하지 못했습니다',str(exc),parent=self);return
            self.destroy()
        self._worker(lambda:download_update(info,self.store.directory/'updates'),done,True)

    def _close(self):
        try:self.store.save(self.state)
        except Exception as exc:
            messagebox.showerror('저장하지 못했습니다',str(exc),parent=self);return
        self.destroy()
