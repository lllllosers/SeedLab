"""Material measurement paging, lifecycle guards, reset isolation and migration safety."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import os
import sqlite3
import subprocess
import sys
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.session import make_engine
from app.models import (Experiment, ExperimentMaterial, GerminationDish, MeasurementTimepoint,
                        SeedlingSample, SeedlingMeasurement, Taxon, SeedLot, ImportJob, AuditLog)
from app.services import dev_reset, measurement_query
from app.services.local_time import today
from test_seedling_measurement import setup_experiment, observe, payload


def fixture_engine(tmp_path):
    return make_engine(f"sqlite:///{(tmp_path/'test.db').as_posix()}")


def populate(tmp_path, count=3, sample_count=2):
    engine=fixture_engine(tmp_path)
    now=datetime.now(timezone.utc)
    exp_id=str(uuid4())
    material_ids=[]
    with Session(engine) as db:
        db.add(Experiment(id=exp_id,code='EXP-WORKLIST',name='材料连续测定',status='active'))
        db.flush()
        for day in (0, 3, 7): db.add(MeasurementTimepoint(experiment_id=exp_id,day_after_germination=day))
        for n in range(1,count+1):
            taxon=Taxon(code=f'SP-W{n:04d}',scientific_name=f'Aster test {n}',common_name=f'狗娃花{n}')
            db.add(taxon);db.flush()
            lot=SeedLot(code=f'LOT-W{n:04d}',taxon_id=taxon.id)
            db.add(lot);db.flush()
            material=ExperimentMaterial(experiment_id=exp_id,seed_lot_id=lot.id,experiment_number=n,display_order=n-1)
            db.add(material);db.flush(); material_ids.append(material.id)
            dish=GerminationDish(material_id=material.id,code=f'W{n}',replicate_no=1,label='R1',seed_count=20,sown_at=now-timedelta(days=40))
            db.add(dish);db.flush()
            for sn in range(1,sample_count+1):
                # Material 2 has overdue+today tasks; 1 has only today+future.
                db.add(SeedlingSample(dish_id=dish.id,sample_number=sn,germinated_at=now-timedelta(days=0 if n==1 else 3)))
        db.commit()
    engine.dispose()
    return f'/api/experiments/{exp_id}',material_ids


def test_worklist_grouping_counts_search_filters_and_real_pagination(auth_client,tmp_path):
    client,_=auth_client
    base,ids=populate(tmp_path,26)
    result=client.get(base+'/measurement-worklist').json()
    assert result['total_materials']==26 and len(result['materials'])==25 and result['total_pages']==2
    assert result['materials'][0]['experiment_number']=='002' # overdue before today-only 001
    assert result['summary']['due_today_count']==52 and result['summary']['overdue_count']==50
    assert result['summary']['upcoming_count']==54 and result['summary']['material_count']==26
    row=client.get(base+'/measurement-worklist',params={'q':'001'}).json()['materials'][0]
    assert row['material_id']==ids[0] and row['due_today_count']==2 and row['upcoming_count']==4
    assert [d['day_after_germination'] for d in row['dag_counts']]==[0,3,7]
    for q in ('001','狗娃花1','Aster test 1','幼苗 01'):
        assert client.get(base+'/measurement-worklist',params={'q':q}).json()['materials']
    assert client.get(base+'/measurement-worklist',params={'status':'overdue'}).json()['total_materials']==25
    assert client.get(base+'/measurement-worklist',params={'dag':7}).json()['total_materials']==0
    assert client.get(base+'/measurement-worklist',params={'status':'all','dag':7}).json()['total_materials']==26
    second=client.get(base+'/measurement-worklist',params={'page':2}).json()
    assert len(second['materials'])==1 and second['materials'][0]['experiment_number']=='001'
    assert len(client.get(base+'/measurement-worklist',params={'page_size':50}).json()['materials'])==26
    material_tasks=client.get(base+'/measurement-tasks',params={'material_id':ids[0]}).json()['tasks']
    assert len(material_tasks)==6 and {t['material_id'] for t in material_tasks}=={ids[0]}
    assert client.get(base+'/measurement-worklist',params={'page_size':101}).status_code==422


def test_records_query_keeps_zero_na_local_dates_delay_and_patch(auth_client,tmp_path):
    client,headers=auth_client
    base,ids=populate(tmp_path)
    now=datetime.now(timezone.utc)
    tasks=client.get(base+'/measurement-tasks').json()['tasks']
    created=[]
    for task in tasks:
        if task['day_after_germination']==0:
            response=client.post(base+'/measurements',json=payload(task,now,root=0,shoot=None,shoot_na=True),headers=headers)
            assert response.status_code==201,response.text
            created.append(response.json())
    result=client.get(base+'/measurement-records',params={'page_size':2}).json()
    assert result['total']==6 and len(result['items'])==2 and result['total_pages']==3
    assert result['items'][0]['root_length_mm']==0 and result['items'][0]['shoot_unavailable']
    assert result['items'][0]['measured_at'].endswith('Z')
    assert client.get(base+'/measurement-records',params={'material_ids':ids[0]}).json()['total']==2
    assert client.get(base+'/measurement-records',params=[('material_ids',ids[0]),('material_ids',ids[1])]).json()['total']==4
    for q in ('001','狗娃花1','Aster test 1'):
        assert client.get(base+'/measurement-records',params={'q':q}).json()['total']==2
    assert client.get(base+'/measurement-records',params={'dag':3}).json()['total']==0
    assert client.get(base+'/measurement-records',params={'date_from':today().isoformat(),'date_to':today().isoformat()}).json()['total']==6
    assert client.get(base+'/measurement-records',params={'date_to':(today()-timedelta(days=1)).isoformat()}).json()['total']==0
    old=next(row for row in client.get(base+'/measurement-records').json()['items'] if row['material_id']==ids[1])
    assert old['delay_days']==3
    patch={key:value for key,value in payload(tasks[0],now,root=4.2,shoot=2).items() if key not in {'sample_id','timepoint_id'}}
    saved=client.patch(base+'/measurements/'+created[0]['id'],json=patch,headers=headers)
    assert saved.status_code==200 and saved.json()['root_length_mm']==4.2
    assert client.patch(base+'/measurements/'+created[0]['id'],json={'sample_id':tasks[0]['sample_id']},headers=headers).status_code==422
    summary=client.get(base+'/measurement-worklist').json()['summary']
    assert summary['completed_today_count']==6
    audits=client.get('/api/audit-logs',params={'entity_type':'SeedlingMeasurement','q':'EXP-WORKLIST','page_size':2}).json()
    assert audits['total']==7 and len(audits['items'])==2
    assert all('DAG0' in r['subject_label'] and '幼苗' in r['subject_label'] and r['user_display_name']=='管理员' for r in audits['items'])


def test_six_thousand_slots_use_fixed_query_count(auth_client,tmp_path):
    base,_=populate(tmp_path,200,10)
    engine=fixture_engine(tmp_path);queries=[]
    def track(_conn,_cursor,statement,_params,_context,_many):queries.append(statement)
    event.listen(engine,'before_cursor_execute',track)
    with Session(engine) as db:
        result=measurement_query.worklist(db,base.split('/')[-1],page_size=25)
        assert result['total_materials']==200 and len(result['materials'])==25
        assert result['summary']['due_today_count']==2000
        assert len(queries)<=6 # independent of 200 materials/6000 slots
        queries.clear(); dashboard=measurement_query.dashboard(db)
        assert dashboard['due_today_count']==2000 and len(queries)==1
    engine.dispose()


@pytest.mark.parametrize('locked',[False,True])
def test_unused_ready_and_locked_plan_can_be_deleted(auth_client,locked):
    client,headers=auth_client
    taxon=client.post('/api/taxa',json={'scientific_name':'Unused species'},headers=headers).json()
    lot=client.post('/api/seed-lots',json={'taxon_id':taxon['id']},headers=headers).json()
    response=client.post('/api/experiments/configured',json={'name':'未执行的方案','protocol':{'seeds_per_dish':10,'replicate_count':2,'observation_period_days':5,'sampling_rule':'first_germinated','sample_count':2,'sample_scope':'per_dish','germination_criterion':'胚根露出'},'materials':[{'seed_lot_id':lot['id']}],'dag_days':[0,3]},headers=headers)
    base='/api/experiments/'+response.json()['experiment']['id']
    assert client.patch(base,json={'status':'ready'},headers=headers).status_code==200
    if locked: assert client.post(base+'/confirm-numbers',headers=headers).status_code==200
    assert client.delete(base,headers=headers).status_code==204
    assert client.get(base).status_code==404
    log=client.get('/api/audit-logs',params={'action':'delete','entity_type':'Experiment'}).json()['items'][0]
    assert '未执行的方案' in log['subject_label']


def test_termination_requires_reason_preserves_facts_and_is_readonly(auth_client):
    client,headers=auth_client
    base,dish,_,_=setup_experiment(client,headers,days=(0,))
    sample=observe(client,headers,base,dish,datetime.now(timezone.utc)-timedelta(days=1))
    task=client.get(base+'/measurement-tasks').json()['tasks'][0]
    item=client.post(base+'/measurements',json=payload(task,datetime.now(timezone.utc)),headers=headers).json()
    assert client.delete(base,headers=headers).status_code==409
    for data in ({},{'reason':''},{'reason':'   '}):assert client.post(base+'/terminate',json=data,headers=headers).status_code==422
    result=client.post(base+'/terminate',json={'reason':'材料污染'},headers=headers)
    assert result.status_code==200 and result.json()['termination_reason']=='材料污染' and result.json()['status']=='cancelled'
    assert client.patch(base+'/sowing/'+dish['id'],json={'sown_at':(datetime.now(timezone.utc)-timedelta(days=10)).isoformat()},headers=headers).status_code==409
    assert client.patch(base+'/measurements/'+item['id'],json={'notes':'不应保存'},headers=headers).status_code==409
    assert client.delete(base+'/measurements/'+item['id'],headers=headers).status_code==409
    assert client.patch(base+'/samples/'+sample['id']+'/position',json={'position_label':'A1'},headers=headers).status_code==409
    assert client.post(base+'/measurements',json=payload(task,datetime.now(timezone.utc)),headers=headers).status_code==409
    assert len(client.get(base+'/measurement-records').json()['items'])==1
    observation=client.get(base+'/execution').json()['recent_observations'][0]
    assert client.patch(base+'/observations/'+observation['id'],json={'notes':'禁止修改'},headers=headers).status_code==409
    assert client.delete(base+'/observations/'+observation['id'],headers=headers).status_code==409
    assert client.patch(base,json={'status':'active'},headers=headers).status_code==409
    assert any(r['after'] and r['after'].get('termination_reason')=='材料污染' for r in client.get('/api/audit-logs').json()['items'])


def test_completion_preflight_pending_observing_all_dag_and_success(auth_client,tmp_path):
    client,headers=auth_client
    base,dish,_,_=setup_experiment(client,headers,days=(0,21),replicates=2)
    check=client.get(base+'/completion-check').json()
    assert check['pending_dish_count']==1 and check['observing_dish_count']==1 and not check['can_complete']
    assert client.post(base+'/complete',headers=headers).status_code==409
    other=next(d for d in client.get(base+'/execution').json()['dishes'] if d['id']!=dish['id'])
    assert client.post(base+'/sowing/'+other['id']+'/cancel',json={'reason':'材料不足'},headers=headers).status_code==200
    observe(client,headers,base,dish,datetime.now(timezone.utc)-timedelta(days=2))
    check=client.get(base+'/completion-check').json()
    assert check['upcoming_count']==1 and check['overdue_count']==1 and check['measurement_pending_count']==2
    engine=fixture_engine(tmp_path)
    with engine.begin() as c:
        c.execute(text('UPDATE seedling_samples SET germinated_at=NULL'))
    assert client.get(base+'/completion-check').json()['unschedulable_count']==2
    with engine.begin() as c:
        c.execute(text('UPDATE seedling_samples SET germinated_at=:date'),{'date':(datetime.now(timezone.utc)-timedelta(days=25)).replace(tzinfo=None).isoformat()})
        c.execute(text('UPDATE germination_dishes SET sown_at=:date WHERE id=:id'),{'date':(datetime.now(timezone.utc)-timedelta(days=40)).replace(tzinfo=None).isoformat(),'id':dish['id']})
    engine.dispose()
    for task in client.get(base+'/measurement-tasks').json()['tasks']:
        assert client.post(base+'/measurements',json=payload(task,datetime.now(timezone.utc)),headers=headers).status_code==201
    assert client.get(base+'/completion-check').json()['can_complete']
    assert client.post(base+'/complete',headers=headers).status_code==200
    assert client.patch(base,json={'status':'active'},headers=headers).status_code==409
    assert any(r['after'] and r['after'].get('status')=='completed' for r in client.get('/api/audit-logs').json()['items'])


def test_reset_backups_atomicity_preservation_cli_and_login(auth_client,tmp_path,monkeypatch):
    client,headers=auth_client
    base,dish,_,_=setup_experiment(client,headers,days=(0,))
    observe(client,headers,base,dish,datetime.now(timezone.utc)-timedelta(days=1))
    task=client.get(base+'/measurement-tasks').json()['tasks'][0]
    assert client.post(base+'/measurements',json=payload(task,datetime.now(timezone.utc)),headers=headers).status_code==201
    engine=fixture_engine(tmp_path)
    with Session(engine) as db:db.add(ImportJob(filename='临时测试.xlsx'));db.commit()
    monkeypatch.setenv('SEEDLAB_ENV','development');get_settings.cache_clear()
    before=dev_reset.preview(engine)
    assert before['taxa']==1 and before['seedling_measurements']==1
    with engine.connect() as c: revision=c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar(); sessions=c.exec_driver_sql('SELECT COUNT(*) FROM sessions').scalar()
    # A backup error must prevent every delete.
    original_backup=dev_reset.backup
    def fail_backup(_engine):raise OSError('simulated backup failure')
    monkeypatch.setattr(dev_reset,'backup',fail_backup)
    with pytest.raises(OSError):dev_reset.reset(engine)
    assert dev_reset.preview(engine)==before
    monkeypatch.setattr(dev_reset,'backup',original_backup)
    original_delete=dev_reset._delete_business
    def fail_delete(connection):
        connection.exec_driver_sql('DELETE FROM audit_logs')
        raise RuntimeError('simulated delete failure')
    monkeypatch.setattr(dev_reset,'_delete_business',fail_delete)
    with pytest.raises(RuntimeError):dev_reset.reset(engine)
    assert dev_reset.preview(engine)==before
    monkeypatch.setattr(dev_reset,'_delete_business',original_delete)
    token=tmp_path/'bootstrap.token';token.write_text('preserved-token',encoding='utf-8')
    env={**os.environ,'SEEDLAB_ENV':'development','SEEDLAB_DATABASE_URL':f"sqlite:///{(tmp_path/'test.db').as_posix()}",'SEEDLAB_BOOTSTRAP_TOKEN_PATH':str(token),'PYTHONIOENCODING':'utf-8'}
    dry=subprocess.run([sys.executable,'-m','app.cli','reset-dev-data','--dry-run'],env=env,capture_output=True,text=True,encoding='utf-8')
    assert dry.returncode==0 and '仅预览' in dry.stdout and dev_reset.preview(engine)==before
    rejected=subprocess.run([sys.executable,'-m','app.cli','reset-dev-data','--yes'],env={**env,'SEEDLAB_ENV':'production'},capture_output=True,text=True,encoding='utf-8')
    assert rejected.returncode==1 and '正式环境禁止' in rejected.stderr and dev_reset.preview(engine)==before
    done=subprocess.run([sys.executable,'-m','app.cli','reset-dev-data','--yes'],env=env,capture_output=True,text=True,encoding='utf-8')
    assert done.returncode==0,done.stderr
    after=dev_reset.preview(engine)
    assert all(value==0 for table,value in after.items() if table not in dev_reset.PRESERVED)
    assert after['users']==before['users'] and after['sessions']==sessions
    backups=list((tmp_path/'backups').glob('dev-reset-*.db'));assert len(backups)==2
    with sqlite3.connect(backups[-1]) as c:assert c.execute('SELECT COUNT(*) FROM taxa').fetchone()[0]==1
    with engine.connect() as c:
        assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar()==revision
        assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
    assert token.read_text(encoding='utf-8')=='preserved-token'
    assert client.get('/api/auth/me').status_code==200 # retained session
    assert client.post('/api/auth/login',json={'username':'admin','password':'test-password-123'}).status_code==200
    engine.dispose()


def test_termination_migration_existing_and_roundtrip(tmp_path,monkeypatch):
    path=tmp_path/'migration.db'; monkeypatch.setenv('SEEDLAB_DATABASE_URL',f'sqlite:///{path.as_posix()}');get_settings.cache_clear()
    config=Config('alembic.ini');command.upgrade(config,'b742b49a162e')
    engine=make_engine(f'sqlite:///{path.as_posix()}')
    with engine.begin() as c:c.exec_driver_sql("INSERT INTO experiments (id,created_at,code,name,status) VALUES ('exp','2026-09-30','EXP-OLD','旧实验','active')")
    command.upgrade(config,'head');command.check(config)
    with engine.connect() as c:
        assert c.exec_driver_sql('SELECT termination_reason FROM experiments').scalar() is None
        assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
    command.downgrade(config,'-1');command.upgrade(config,'head')
    with engine.connect() as c:
        assert c.exec_driver_sql('SELECT name FROM experiments').scalar()=='旧实验'
        assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar()=='c6d91f28a405'
    with engine.begin() as c:c.exec_driver_sql("UPDATE experiments SET termination_reason='保留原因'")
    with pytest.raises(RuntimeError,match='终止原因'):command.downgrade(config,'-1')
    with engine.connect() as c:assert c.exec_driver_sql('SELECT termination_reason FROM experiments').scalar()=='保留原因'
    engine.dispose();get_settings.cache_clear()


@pytest.mark.parametrize('fact',['sown','observation','sample'])
def test_even_ready_state_with_any_execution_fact_cannot_delete(auth_client,tmp_path,fact):
    client,headers=auth_client
    base,dish,_,_=setup_experiment(client,headers,days=(0,))
    engine=fixture_engine(tmp_path)
    with engine.begin() as c:
        c.execute(text("UPDATE experiments SET status='ready' WHERE id=:id"),{'id':base.split('/')[-1]})
        if fact!='sown':
            c.execute(text('UPDATE germination_dishes SET sown_at=NULL WHERE id=:id'),{'id':dish['id']})
            table='germination_observations' if fact=='observation' else 'seedling_samples'
            columns='observed_at,new_germinated_count' if fact=='observation' else 'germinated_at,sample_number'
            c.execute(text(f"INSERT INTO {table} (id,created_at,dish_id,{columns}) VALUES (:id,'2026-09-30',:dish,'2026-09-30',1)"),{'id':str(uuid4()),'dish':dish['id']})
    assert client.delete(base,headers=headers).status_code==409
    assert client.get(base).status_code==200
    engine.dispose()
