QSS = """
QWidget { font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; color: #263649; }
QMainWindow, QStackedWidget, QScrollArea, QWidget#page { background: #f5f7fb; }
QScrollArea#navScroll { background: #ffffff; }
QFrame#header, QWidget#sidebar { background: #ffffff; }
QFrame#header { border-bottom: 1px solid #e7ecf3; }
QWidget#sidebar { border-right: 1px solid #e7ecf3; }
QFrame#card { background: #ffffff; border: 1px solid #e7ecf3; border-radius: 14px; }
QLabel { background: transparent; border: none; }
QLabel#brand { font-size: 21px; font-weight: 600; }
QLabel#title { font-size: 23px; font-weight: 600; }
QLabel#cardTitle { font-size: 16px; font-weight: 600; }
QLabel#fieldLabel { color: #7c8999; font-size: 12px; }
QLabel#fieldValue { color: #263649; font-size: 14px; }
QLabel#sectionTitle { color: #66768a; font-size: 14px; font-weight: 600; }
QLabel#value { font-size: 19px; font-weight: 600; }
QLabel#muted { color: #7c8999; font-size: 12px; }
QLabel#kicker { color: #6692bf; font-size: 12px; }
QLabel#state { background: #eaf3ff; color: #487fb6; border-radius: 12px; padding: 6px 12px; }
QLabel#state[tone='good'] { background: #eaf6ef; color: #43886a; }
QLabel#state[tone='error'] { background: #fff0ed; color: #b76859; }
QLabel#state[tone='neutral'] { background: #f0f3f7; color: #7c8999; }
QPushButton { background: #ffffff; border: 1px solid #dbe4ef; border-radius: 8px; padding: 9px 16px; }
QPushButton:hover { background: #f1f6fd; border-color: #b8cde5; }
QPushButton:pressed { background: #e7f0fc; }
QPushButton:disabled { color: #a6b0bd; background: #f7f9fc; border-color: #e9edf3; }
QPushButton#primary { background: #568ed0; border-color: #568ed0; color: white; }
QPushButton#primary:hover { background: #477fbe; }
QPushButton#primary:disabled { background: #dbe6f4; border-color: #dbe6f4; color: #99afc8; }
QPushButton#nav { text-align: left; border: none; border-left: 3px solid transparent; border-radius: 8px; padding: 13px 14px; color: #66768a; }
QPushButton#nav:hover { background: #f5f8fc; }
QPushButton#nav:checked { background: #edf4fe; color: #447db9; border-left-color: #6ba0de; font-weight: 600; }
QLineEdit { background: #f7f9fc; border: 1px solid #e5ebf3; border-radius: 7px; padding: 9px; }
QPlainTextEdit#eventLog { background: #fcfdff; border: 1px solid #eef2f7; border-radius: 8px; padding: 10px; font-size: 13px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 4px 0; }
QScrollBar::handle:vertical { background: #dce4ee; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QMenu { background: white; border: 1px solid #e3e9f1; padding: 5px; }
QMenu::item { padding: 8px 24px; }
QMenu::item:selected { background: #edf4fe; color: #447db9; }
"""


def window_dimensions(available_width, available_height):
    # QScreen dimensions are logical pixels, including Windows display scaling.
    width = max(320, min(1180, available_width - 48))
    height = max(300, min(720, available_height - 48))
    return (width, height), (min(980, width), min(620, height))
