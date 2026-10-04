"""Opt-in standalone portable rehearsal, in a brand-new non-TEMP/non-repo root."""
from contextlib import closing
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/maintenance'))
from legacy_importer_trial import StandaloneTrial, digest
import legacy_import_core as core


def test_standalone_no_development_environment_full_rehearsal():
    names=('SEEDLAB_REHEARSAL_PARENT','SEEDLAB_PORTABLE_ZIP','SEEDLAB_IMPORTER_EXE','SEEDLAB_LEGACY_SOURCE')
    if not all(os.environ.get(name) for name in names):
        pytest.skip('Explicit standalone rehearsal paths required')
    parent,portable,exe,source=(Path(os.environ[name]) for name in names)
    trial=StandaloneTrial(parent,portable,exe,source)
    result={}
    try:
        help_result=subprocess.run([str(trial.exe),'--help'],cwd=trial.root,env=trial.env,
            capture_output=True,text=True,encoding='utf8',timeout=30)
        assert help_result.returncode==0 and '默认只读' in help_result.stdout
        wrong=trial.root/'wrong.xlsx'; wrong.write_bytes(b'wrong source')
        rejected,_=trial.run_importer(source=wrong)
        assert rejected.returncode==1 and 'SHA256' in rejected.stderr
        rejected,_=trial.run_importer(data_root=trial.root/'unknown-data')
        assert rejected.returncode==1
        trial.start()
        assert not trial.request('/api/setup/status')['initialized']
        trial.bootstrap()
        assert all(n==0 for n in trial.business_counts().values())
        rejected,_=trial.run_importer('--apply','--confirm','LEGACY-200-202608')
        assert rejected.returncode==1 and '停止服务' in rejected.stderr
        trial.stop()
        before=digest(trial.path)
        dry,dry_report=trial.run_importer()
        assert dry.returncode==0, dry.stderr
        assert dry_report['zero_database_writes'] and digest(trial.path)==before
        assert not list((trial.data_root/'backups').rglob('*.db'))
        applied,report=trial.run_importer('--apply','--confirm','LEGACY-200-202608')
        assert applied.returncode==0,applied.stderr
        assert report['database']['value_differences']==report['workbook']['value_differences']==0
        assert report['database']['dag']=={'3':1655,'7':1655,'14':1645}
        assert report['workbook']['wide_rows']==2000 and report['workbook']['long_rows']==6000
        assert report['workbook']['unmeasured_actual_slots']==40 and report['workbook']['absent_sample_measurement_slots']==1005
        assert report['task_semantics_after_commit']['pending_count']==0
        for phase in ('pre_backup','post_backup'):
            assert digest(report[phase]['path'])==report[phase]['sha256']
        with closing(sqlite3.connect(trial.path)) as db:
            experiment_id,code,status,ended=db.execute('SELECT id,code,status,ended_at FROM experiments').fetchone()
            assert (code,status,ended)==('GER-202608-001','completed',None)
        trial.start(); trial.login()
        for _ in range(2):
            assert trial.request('/api/experiments/'+experiment_id+'/measurement-records')['total']==4955
            assert trial.request('/api/experiments/'+experiment_id+'/execution')['today_pending_count']==0
            assert trial.request('/api/dashboard')['measurement']['experiments']==[]
            exported=core.reconcile_workbook(BytesIO(trial.export(experiment_id)),core.read_source(source))
            assert exported['value_differences']==0
            trial.stop()
            if _==0:
                trial.start(); trial.login()
        saved=trial.business_counts()
        repeat,_=trial.run_importer('--apply','--confirm','LEGACY-200-202608')
        assert repeat.returncode==1 and '已经存在业务数据' in repeat.stderr
        assert trial.business_counts()==saved
        result={'result':'PASS','trial_root':str(trial.root),'port':trial.port,'data_root':str(trial.data_root),
            'program_root':str(trial.program),'database':str(trial.path),'experiment_id':experiment_id,
            'counts':saved,'source_sha':digest(source),'exe_sha':digest(exe),'dry_run_zero_writes':True,
            'restart_verified':True,'duplicate_apply_rejected':True,'standalone_without_development_environment':True,
            'portable_workbook_reverse':exported,'import_report':report}
        (trial.root/'rehearsal-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print('STANDALONE_REHEARSAL_ROOT='+str(trial.root))
    finally:
        trial.stop()
