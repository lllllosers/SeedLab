"""Tool state, Windows lock deferral and retry; never opens a business DB."""
import hashlib
import json
from pathlib import Path

import pytest

from production_ops import OperationsError, tool_refresh as refresh
from production_ops.deployment import DeploymentStore, LAUNCHER, UPDATER, atomic_json


@pytest.fixture
def tool_deployment(tmp_path):
    root = tmp_path / 'managed'
    program = root / 'App/v0.6.1/SeedLab'
    folder = program / 'app/upgrade-tools'
    folder.mkdir(parents=True)
    hashes = {}
    for name in refresh.TOOLS:
        (root / name).write_bytes(b'old executable')
        (folder / name).write_bytes(('new ' + name).encode())
        hashes[name] = refresh.digest(folder / name)
    slot = {'version':'0.6.1', 'build_identity':'new-build', 'revision':'d2e7a46b910c','program_root':str(program)}
    atomic_json(folder / 'tools.json', {'version':'0.6.1','build_identity':'new-build','tools':hashes})
    store = DeploymentStore(root)
    store.create(slot, tmp_path / 'data')
    sentinel = tmp_path / 'data/data/seedlab.db'
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'business data must never be opened')
    return store, slot, sentinel


def test_mapped_root_updater_defers_then_promotes_both_tools(tool_deployment):
    store, slot, sentinel = tool_deployment
    before = sentinel.read_bytes()
    refresh.stage_refresh(store.root,slot,version_reader=lambda p:'0.6.1')
    assert (store.root / 'SeedLab Updater.next.exe').exists()
    state = store.path.read_bytes()
    assert not refresh.finish_refresh(store.root,timeout=0,version_reader=lambda p:'0.6.1',
                                       processes=lambda names:[(123, store.root / UPDATER)])
    assert refresh.pending_refresh(store.root)
    assert (store.root / UPDATER).read_bytes() == b'old executable'
    assert refresh.finish_refresh(store.root,timeout=0,version_reader=lambda p:'0.6.1',processes=lambda names:[])
    assert refresh.pending_refresh(store.root) is None
    for name in refresh.TOOLS:
        assert refresh.digest(store.root / name) == refresh.resources(slot)[1]['tools'][name]
    assert store.path.read_bytes() == state and sentinel.read_bytes() == before


def test_locked_launcher_also_defers_and_retry_after_partial_failure(tool_deployment,monkeypatch):
    store, slot, sentinel = tool_deployment
    refresh.stage_refresh(store.root,slot,version_reader=lambda p:'0.6.1')
    assert not refresh.finish_refresh(store.root,timeout=0,version_reader=lambda p:'0.6.1',
        processes=lambda names:[(45,store.root/LAUNCHER)])
    original = refresh.os.replace
    def locked(source,target):
        if Path(target).name == UPDATER: raise PermissionError('isolated lock')
        return original(source,target)
    monkeypatch.setattr(refresh.os,'replace',locked)
    assert not refresh.finish_refresh(store.root,timeout=0,version_reader=lambda p:'0.6.1',processes=lambda names:[])
    assert refresh.pending_refresh(store.root)
    monkeypatch.setattr(refresh.os,'replace',original)
    assert refresh.finish_refresh(store.root,timeout=0,version_reader=lambda p:'0.6.1',processes=lambda names:[])


def test_corrupt_tool_or_wrong_build_never_promotes(tool_deployment):
    store, slot, _ = tool_deployment
    refresh.stage_refresh(store.root,slot,version_reader=lambda p:'0.6.1')
    (store.root / 'SeedLab Updater.next.exe').write_bytes(b'corrupt')
    assert not refresh.finish_refresh(store.root,timeout=0,version_reader=lambda p:'0.6.1',processes=lambda names:[])
    assert refresh.pending_refresh(store.root)
    # Explicit retry re-stages validated carried resources, without touching DB.
    refresh.stage_refresh(store.root,slot,version_reader=lambda p:'0.6.1')
    assert refresh.finish_refresh(store.root,timeout=0,version_reader=lambda p:'0.6.1',processes=lambda names:[])


def test_candidate_tools_cannot_promote_before_app_commit(tool_deployment):
    store, slot, _ = tool_deployment
    refresh.stage_refresh(store.root,slot,version_reader=lambda p:'0.6.1')
    state=store.load();state['current']['build_identity']='different-build';store.save(state)
    assert not refresh.finish_refresh(store.root,timeout=0,version_reader=lambda p:'0.6.1',processes=lambda names:[])
    assert (store.root/UPDATER).read_bytes() == b'old executable'


def test_staging_failure_retains_visible_intent(tool_deployment,monkeypatch):
    store, slot, _ = tool_deployment
    monkeypatch.setattr(refresh.shutil,'copyfile',lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):refresh.stage_refresh(store.root,slot,version_reader=lambda p:'0.6.1')
    assert '升级工具更新未完成' in refresh.pending_refresh(store.root)['message']


def test_incomplete_staging_intent_remains_pending_until_explicit_retry(tool_deployment):
    store, slot, _ = tool_deployment
    atomic_json(refresh.state_path(store), {'tool_refresh_pending': {**slot, 'message': refresh.MESSAGE}})
    assert not refresh.finish_refresh(store.root, timeout=0, processes=lambda names: [])
    assert refresh.pending_refresh(store.root)
    assert (store.root / UPDATER).read_bytes() == b'old executable'
    refresh.stage_refresh(store.root, slot, version_reader=lambda path: '0.6.1')
    assert refresh.finish_refresh(store.root, timeout=0, version_reader=lambda path: '0.6.1', processes=lambda names: [])


@pytest.mark.parametrize('invalid', [{'unexpected': None}, {'tool_refresh_pending': {}}])
def test_invalid_tool_state_fails_closed(tool_deployment, invalid):
    store, _, _ = tool_deployment
    atomic_json(refresh.state_path(store), invalid)
    with pytest.raises(OperationsError):
        refresh.updater_command(store.root)
