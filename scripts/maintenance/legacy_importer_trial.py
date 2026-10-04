"""Disposable portable rehearsal harness, never accepts an existing Data Root.

Only the harness needs development Python. Both tested executables run with a
minimal Windows environment, isolated cwd, and no Python/Node/source on PATH.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import time
from urllib.request import build_opener, HTTPCookieProcessor, Request
from uuid import uuid4
import zipfile

PORTABLE_SHA = "8e59e50ff8cfe39ef13ac54e453b9b1ec9505eef1a1ae21f09c2ea1435c70ac8"


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def isolated_environment():
    environment = {key: value for key, value in os.environ.items() if key.upper() in
        {'SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','USERNAME','USERDOMAIN','COMSPEC'}}
    environment['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    environment['PYTHONUTF8'] = '1'
    return environment


class StandaloneTrial:
    def __init__(self, parent, portable, importer, source):
        parent = Path(parent).resolve()
        assert parent.is_absolute()
        self.root = parent / ('run-' + uuid4().hex)
        assert not self.root.exists()
        self.root.mkdir(parents=True)
        (self.root / 'DISPOSABLE-REHEARSAL.txt').write_text('一次性仿生产演练；不是正式业务数据；验收后可清理。',encoding='utf8')
        assert digest(portable) == PORTABLE_SHA
        with zipfile.ZipFile(portable) as archive:
            for member in archive.infolist():
                target = (self.root / member.filename).resolve()
                assert target.is_relative_to(self.root)
            archive.extractall(self.root)
        self.program = self.root / 'SeedLab'
        self.data_root = self.root / 'ProductionData'
        for relative in ('data','config','logs','backups/manual','backups/auto','backups/before-upgrade'):
            (self.data_root / relative).mkdir(parents=True,exist_ok=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            self.port = sock.getsockname()[1]
        # The portable server performs real migration/identity/bootstrap startup.
        # These are the same v0.5.1 persisted deployment settings/locator layout.
        config = {'schema_version':1,'access_mode':'local','port':self.port,'lan_address':None,'remote_url':None,
                  'auto_backup_enabled':False,'auto_backup_retention':14,'auto_start_server':False}
        (self.data_root / 'config/seedlab.json').write_text(json.dumps(config),encoding='utf8')
        (self.program / 'config/installation.json').write_text(json.dumps({'schema_version':1,'data_root':str(self.data_root)}),encoding='utf8')
        self.exe = self.root / 'SeedLabLegacyImport-v1.0.0.exe'
        shutil.copyfile(importer,self.exe)
        self.source = Path(source)
        self.path = self.data_root / 'data/seedlab.db'
        self.stop_file = self.data_root / 'data/control/trial.stop'
        self.stop_file.parent.mkdir()
        self.process = None
        self.server_output = None
        self.http = build_opener(HTTPCookieProcessor())
        self.password = secrets.token_urlsafe(24)
        self.username = 'trial-admin'
        self.env = isolated_environment()

    def start(self):
        self.server_output = (self.root / ('server-' + uuid4().hex + '.log')).open('w',encoding='utf8')
        command = [str(self.program/'SeedLabServer.exe'),'--host','127.0.0.1','--port',str(self.port),
            '--database',str(self.path),'--data-root',str(self.data_root),'--bootstrap-token',str(self.data_root/'data/bootstrap.token'),
            '--web-root',str(self.program/'app/web'),'--migration-root',str(self.program/'app/migrations'),
            '--access-mode','local','--cookie-secure','false','--stop-file',str(self.stop_file)]
        self.process = subprocess.Popen(command,cwd=self.root,env=self.env,stdout=self.server_output,
            stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            assert self.process.poll() is None, 'portable server exited'
            try:
                if self.request('/api/health')['status']=='ok':
                    return
            except Exception:
                time.sleep(.25)
        raise AssertionError('portable startup timed out')

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.stop_file.touch()
            self.process.wait(timeout=30)
            assert self.process.returncode == 0
        if self.server_output:
            self.server_output.close()

    def request(self,path,payload=None,*,binary=False):
        headers={'Content-Type':'application/json'}
        if getattr(self,'csrf',None):
            headers['X-CSRF-Token']=self.csrf
        request=Request(f'http://127.0.0.1:{self.port}'+path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers)
        with self.http.open(request,timeout=30) as response:
            value=response.read()
            return value if binary else json.loads(value)

    def bootstrap(self):
        token=(self.data_root/'data/bootstrap.token').read_text(encoding='utf8').strip()
        result=self.request('/api/setup/bootstrap',{'bootstrap_token':token,'username':self.username,
            'display_name':'仿生产测试管理员','password':self.password,'confirm_password':self.password})
        self.csrf=result['csrf_token']
        return result

    def login(self):
        result=self.request('/api/auth/login',{'username':self.username,'password':self.password})
        self.csrf=result['csrf_token']
        return result

    def run_importer(self,*additional,source=None,data_root=None):
        report=self.root/('report-'+uuid4().hex)
        command=[str(self.exe),'--source',str(source or self.source),'--data-root',str(data_root or self.data_root),
                 '--owner',self.username,'--output-dir',str(report),*additional]
        result=subprocess.run(command,cwd=self.root,env=self.env,capture_output=True,text=True,encoding='utf8',timeout=120)
        report_path=report/'legacy-import-report.json'
        return result, json.loads(report_path.read_text(encoding='utf8')) if report_path.exists() else None

    def export(self,experiment_id):
        return self.request('/api/export/experiments/workbook.xlsx',{'experiment_ids':[experiment_id]},binary=True)

    def business_counts(self):
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
            return {table:db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in
                ('taxa','seed_lots','experiments','experiment_materials','germination_dishes','germination_observations','seedling_samples','seedling_measurements')}
