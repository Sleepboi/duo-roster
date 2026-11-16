from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import traceback

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--smoke-test',action='store_true')
    parser.add_argument('--smoke-report',type=Path)
    parser.add_argument('--install',action='store_true')
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--import-xlsx',type=Path)
    parser.add_argument('--period')
    args=parser.parse_args()
    if args.data_dir:os.environ['DUOROSTER_DATA_DIR']=str(args.data_dir.resolve())
    if os.name=='nt':
        import ctypes
        try:ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:pass
    from duoroster.storage import Store
    from duoroster.gui import App
    if args.smoke_test:
        from duoroster.engine import default_data,solve,validate
        import tempfile
        d=default_data(2026,11,1);d['max_seconds']=3;solve(d)
        if not d['result'] or validate(d):raise RuntimeError('계산기 점검 실패')
        with tempfile.TemporaryDirectory() as temp:
            app=App(Store(temp));app.withdraw();app.update_idletasks();app.destroy()
        report={'ok':True,'version':__import__('duoroster').__version__,
                'release_repository':__import__('duoroster').RELEASE_REPOSITORY}
        if args.smoke_report:args.smoke_report.write_text(json.dumps(report),encoding='utf-8')
        print(json.dumps(report))
        return
    if args.install:
        from duoroster.updating import install_application
        from tkinter import messagebox
        import subprocess
        installed=install_application()
        messagebox.showinfo('설치 완료','바탕화면의 두 사람 근무표 아이콘으로 실행할 수 있습니다.')
        subprocess.Popen([str(installed/'DuoRoster.exe')])
        return
    store=Store()
    if os.name=='nt':
        import ctypes,hashlib,atexit
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateMutexW.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        mutex_name='Local\\DuoRoster-'+hashlib.sha256(str(store.directory.resolve()).encode()).hexdigest()[:24]
        handle=kernel.CreateMutexW(None,False,mutex_name)
        if not handle:raise RuntimeError('프로그램 실행 잠금을 만들 수 없습니다.')
        if ctypes.get_last_error()==183:
            kernel.CloseHandle(handle)
            from tkinter import messagebox
            messagebox.showinfo('두 사람 근무표','이미 실행 중입니다. 열려 있는 근무표 창을 사용해 주세요.')
            return
        atexit.register(lambda:kernel.CloseHandle(handle))
    if args.import_xlsx:
        from duoroster.exporting import import_excel
        store.save(import_excel(args.import_xlsx))
    try:loaded=store.load()
    except ValueError as exc:
        import tkinter as tk
        from tkinter import messagebox,filedialog
        recovery=tk.Tk();recovery.withdraw()
        if not messagebox.askyesno('기록 복원',str(exc)+'\n\n백업 파일을 선택해 복원할까요?',parent=recovery):
            recovery.destroy();return
        selected=filedialog.askopenfilename(parent=recovery,title='백업 선택',initialdir=store.directory/'backups',filetypes=[('근무 기록','*.json')])
        if not selected:recovery.destroy();return
        loaded=store.restore(selected);recovery.destroy()
    app=App(store,state=loaded)
    if args.period:
        from duoroster.domain import ensure_month
        app.key=args.period;ensure_month(app.state,app.key);app.render()
    app.mainloop()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        try:
            from duoroster.storage import data_directory
            location=data_directory();location.mkdir(parents=True,exist_ok=True)
            (location/'last-error.log').write_text(traceback.format_exc(),encoding='utf-8')
            if '--smoke-test' not in sys.argv:
                from tkinter import messagebox
                messagebox.showerror('두 사람 근무표',str(exc)+'\n\n자세한 내용: '+str(location/'last-error.log'))
        except Exception:pass
        if sys.stderr:traceback.print_exc()
        sys.exit(1)
