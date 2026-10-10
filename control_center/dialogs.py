"""Small shared confirmation with explicit Chinese actions on every Windows locale."""
from PySide6.QtWidgets import QMessageBox


def confirm_action(parent, title, message, action):
    box = QMessageBox(QMessageBox.Icon.Question, title, message, parent=parent)
    proceed = box.addButton(action, QMessageBox.ButtonRole.YesRole)
    cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() == proceed
