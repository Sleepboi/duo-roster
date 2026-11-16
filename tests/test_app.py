import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from duoroster.storage import Store,default_state,validate_state
from duoroster.domain import ensure_month,generate,inspect_month,counts,edit_shift,yearly_counts
from duoroster.exporting import export_excel,import_excel,export_pdf
from duoroster.updating import verify_archive,check_update,update_script,install_application

def sample_state():
    state=default_state()
    nov=ensure_month(state,'2027-02');dec=ensure_month(state,'2027-03')
    dec['off_goal']=10
    for r in nov['days']:
        if r['date']=='2027-02-26':r['fixed'][0]='E'
    for r in dec['days']:
        if r['date'] in {'2027-03-05','2027-03-06','2027-03-07','2027-03-19','2027-03-20','2027-03-21'}:r['fixed'][0]='OFF'
        if r['date'] in {'2027-03-14','2027-03-18'}:r['fixed'][0]='MD'
        if r['date']=='2027-03-17':r['fixed'][0]='D'
    return state

class DomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result=generate(sample_state(),'2027-02',True)
        if not result['ok']:raise AssertionError(result)
        cls.planned=result['state']

    def test_fixed_requests_and_both_months(self):
        state=copy.deepcopy(self.planned)
        for key,target in [('2027-02',8),('2027-03',10)]:
            m=state['months'][key]
            self.assertEqual(inspect_month(state,key)['errors'],[])
            for p in range(2):self.assertEqual(counts(m,p)['OFF'],target);self.assertEqual(counts(m,p)['MD'],target)
            for rec in m['days']:
                for p,fixed in enumerate(rec['fixed']):
                    if fixed:self.assertEqual(m['result'][rec['date']][p],fixed)
        self.assertTrue(inspect_month(state,'2027-03')['boundary_complete'])
        self.assertFalse(inspect_month(state,'2027-02')['boundary_complete'])

    def test_return_d_is_not_a_hard_failure(self):
        report=inspect_month(copy.deepcopy(self.planned),'2027-03')
        self.assertEqual(report['errors'],[])
        self.assertTrue(report['exceptions'])

    def test_edit_pairs_and_partner_fixed_conflict(self):
        state=default_state();m=ensure_month(state,'2026-11')
        edit_shift(state,'2026-11','2026-11-02',0,'OFF',True)
        self.assertEqual(m['result']['2026-11-02'],['OFF','MD'])
        with self.assertRaises(ValueError):edit_shift(state,'2026-11','2026-11-02',1,'E',True)
        self.assertEqual(m['result']['2026-11-02'],['OFF','MD'])

    def test_actual_records_are_distinct_from_plans(self):
        state=copy.deepcopy(self.planned)
        self.assertEqual(yearly_counts(state,2027)[1],0)
        state['months']['2027-02']['status']='actual'
        totals,known=yearly_counts(state,2027)
        self.assertEqual(known,1);self.assertEqual(totals[0]['OFF'],8)

    def test_generation_does_not_mutate_inputs(self):
        state=sample_state();before=copy.deepcopy(state)
        generate(state,'2027-02',True)
        self.assertEqual(state,before)

class StorageTests(unittest.TestCase):
    def test_save_backup_restore_and_future_schema_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);state=default_state();store.save(state)
            state['settings']['names']=['First','Second'];store.save(state)
            self.assertEqual(store.load()['settings']['names'],['First','Second'])
            backups=list((Path(temp)/'backups').glob('*.json'));self.assertEqual(len(backups),1)
            store.restore(backups[0]);self.assertEqual(store.load()['settings']['names'],['직원 1','직원 2'])
            raw='{"schema":99}'
            store.path.write_text(raw,encoding='utf-8')
            with self.assertRaises(ValueError):store.load()
            self.assertEqual(store.path.read_text(encoding='utf-8'),raw)

class ExportTests(unittest.TestCase):
    def test_excel_roundtrip_dates_requests_and_colors(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as temp:
            state=copy.deepcopy(DomainTests.planned)
            path=Path(temp)/'schedule.xlsx'
            export_excel(state,['2027-02','2027-03'],path)
            imported=import_excel(path)
            self.assertEqual(imported['settings'],state['settings'])
            for key in ('2027-02','2027-03'):
                self.assertEqual(imported['months'][key]['result'],state['months'][key]['result'])
                self.assertEqual(imported['months'][key]['days'],state['months'][key]['days'])
            wb=load_workbook(path)
            self.assertEqual(wb['2027-03']['F16'].fill.patternType,'solid')
            self.assertEqual(wb['_DuoRoster'].sheet_state,'hidden');wb.close()

class UpdateTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows shortcut test')
    def test_install_copies_program_and_creates_shortcut_without_touching_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir()
            (source/'DuoRoster.exe').write_bytes(b'test-app')
            desktop=root/'Desktop';desktop.mkdir()
            local=root/'LocalAppData';local.mkdir()
            private=root/'private-state.json';private.write_text('keep-me')
            with patch('sys.frozen',True,create=True),patch('sys.executable',str(source/'DuoRoster.exe')),patch.dict(os.environ,{'LOCALAPPDATA':str(local)}),patch('winreg.QueryValueEx',return_value=(str(desktop),1)):
                installed=install_application()
                self.assertEqual((installed/'DuoRoster.exe').read_bytes(),b'test-app')
                self.assertTrue((desktop/'두 사람 근무표.lnk').is_file())
                with self.assertRaises(ValueError):install_application()
            self.assertEqual(private.read_text(),'keep-me')

    def make_archive(self,path,members):
        with zipfile.ZipFile(path,'w') as zipped:
            for key,value in members.items():zipped.writestr(key,value)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_digest_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'update.zip'
            digest=self.make_archive(path,{'DuoRoster/DuoRoster.exe':b'fake executable'})
            verify_archive(path,digest)
            with self.assertRaises(ValueError):verify_archive(path,'0'*64)
            digest=self.make_archive(path,{'DuoRoster/DuoRoster.exe':b'fake','DuoRoster/../../state.json':b'bad'})
            with self.assertRaises(ValueError):verify_archive(path,digest)

    def test_update_metadata_requires_repository_and_digest(self):
        payload={'tag_name':'v0.2.0','assets':[{'name':'DuoRoster-0.2.0-windows-x64.zip',
                 'browser_download_url':'https://github.com/Sleepboi/duo-roster/releases/download/v0.2.0/app.zip','digest':'sha256:'+'a'*64}]}
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
            self.assertEqual(check_update('Sleepboi/duo-roster')['version'],'0.2.0')
        payload['assets'][0]['browser_download_url']='https://example.org/app.zip'
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
            with self.assertRaises(ValueError):check_update('Sleepboi/duo-roster')

    def test_update_preserves_data_and_keeps_old_app(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);install=root/'DuoRoster';install.mkdir();(install/'DuoRoster.exe').write_bytes(b'app')
            staged=root/'stage'/'DuoRoster';staged.mkdir(parents=True)
            script=update_script(install,staged,123,root/'last-update.log')
            self.assertIn('DuoRoster.previous-',script)
            self.assertNotIn('Remove-Item',script)
            self.assertNotIn('state.json',script)
            self.assertIn('WaitForExit',script)

if __name__=='__main__':unittest.main()
