import os
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
from production_ops import OperationsError
from production_ops import windows


def test_shortcut_exit_zero_without_verified_result_is_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(windows.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout=""))
    with pytest.raises(OperationsError, match="SeedLab Launcher.exe"):
        windows.create_shortcut(tmp_path, tmp_path / "old")


@pytest.mark.skipif(os.name != "nt", reason="Windows WScript.Shell shortcut validation")
def test_real_shortcut_target_and_unrelated_link_preserved(tmp_path):
    root = tmp_path / "新部署 根目录"
    desktop = tmp_path / "独立验收桌面"
    root.mkdir()
    desktop.mkdir()
    (root / "SeedLab Launcher.exe").write_bytes(b"isolated placeholder")
    windows.create_shortcut(root, tmp_path / "old", desktop=desktop)
    link = desktop / "SeedLab.lnk"
    assert link.is_file()
    # A different installation must not take over the existing shortcut.
    before = link.read_bytes()
    with pytest.raises(OperationsError):
        windows.create_shortcut(tmp_path / "unrelated", tmp_path / "other", desktop=desktop)
    assert link.read_bytes() == before


def test_bootstrap_entrypoint_failure_is_visible_and_nonfatal(tmp_path, monkeypatch):
    from production_ops import gui
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui, "discover", lambda: [])
    window = gui.UpgradeWindow(bootstrap=True)
    window.executor = SimpleNamespace(store=SimpleNamespace(root=tmp_path), log=Mock())
    monkeypatch.setattr(window, "refresh_state", lambda: None)
    def unavailable(*args):
        raise OperationsError("入口核验未完成")
    monkeypatch.setattr(gui, "connect_startup", unavailable)
    shortcut = Mock(side_effect=unavailable)
    shortcut.__name__ = "create_shortcut"
    monkeypatch.setattr(gui, "create_shortcut", shortcut)
    state = {"current": {"version": "0.6.1"}, "previous": {"program_root": str(tmp_path / "old")}}
    window.completed(state)
    assert shortcut.call_count == 1
    assert "升级完成" in window.status.text() and str(tmp_path / "SeedLab Launcher.exe") in window.status.text()
    assert "原页面可以关闭" in window.status.text()
    assert "桌面快捷方式未能自动创建" in window.status.text()
    assert "Windows 登录启动未能接续" in window.status.text()
    assert window.executor.log.exception.call_count == 2
    window.close()


def test_shared_confirmation_has_chinese_actions_and_safe_default():
    from control_center.dialogs import confirm_action
    app = QApplication.instance() or QApplication([])
    observed = []
    def click():
        box = app.activeModalWidget()
        observed.extend(button.text() for button in box.buttons())
        assert box.defaultButton().text() == "取消"
        next(button for button in box.buttons() if button.text() == "开始升级").click()
    QTimer.singleShot(0, click)
    assert confirm_action(None, "开始升级", "实验数据目录保持不变。", "开始升级")
    assert set(observed) == {"开始升级", "取消"}


def test_long_path_is_elided_but_tooltip_and_copy_keep_full_value():
    from control_center.path_display import PathDisplay
    app = QApplication.instance() or QApplication([])
    path = "E:/" + "长目录/" * 60 + "SeedLab-v0.6.1-upgrade.zip"
    field = PathDisplay(path)
    field.resize(300, 40)
    field.show()
    app.processEvents()
    field.setText(path)
    assert field.text() == field.toolTip() == path
    assert "…" in field.label.text() and len(field.label.text()) < len(path)
    field.findChild(QPushButton).click()
    assert app.clipboard().text() == path
    field.close()


def test_new_page_opens_once_after_owned_server_health():
    from control_center.app import ApplicationController
    from app.version import VERSION
    controller = ApplicationController.__new__(ApplicationController)
    # Avoid constructing a window or starting processes; exercise the health transition.
    controller.open_after_upgrade = True
    controller.window = SimpleNamespace(manager=SimpleNamespace(can_open=False), open_browser=Mock())
    controller.open_upgraded_page()
    assert controller.open_after_upgrade
    controller.window.manager.can_open = True
    controller.open_upgraded_page()
    controller.open_upgraded_page()
    controller.window.open_browser.assert_called_once_with(f"/?seedlab-version={VERSION}")
