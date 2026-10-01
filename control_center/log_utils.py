import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re


def redact(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    text = re.sub(r'''(?i)((?:bootstrap[ _-]*token|session[ _-]*token|csrf[ _-]*token|password(?:_hash)?|authorization|cookie|sakurafrp[ _-]*token)["']?\s*[=:]\s*)("[^"]*"|'[^']*'|[^\s,;]+)''', r"\1[已隐藏]", text)
    return text


class SecretFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            import traceback
            record.msg += "\n" + redact("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
            record.exc_text = None
        return True


def make_logger(directory: Path, name: str):
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"seedlab.control.{name}.{directory}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(directory / f"{name}.log", maxBytes=5 * 1024 ** 2,
                                      backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        handler.addFilter(SecretFilter())
        logger.addHandler(handler)
    return logger


def user_log_tail(path: Path, limit=35) -> str:
    if not path.is_file():
        return "暂时没有运行记录。启动服务后可在此查看。"
    with path.open("rb") as source:
        source.seek(max(0, path.stat().st_size - 64 * 1024))
        lines = source.read().decode("utf-8", errors="replace").splitlines()
    # Detailed stack traces remain in local files, not in the ordinary UI.
    summaries = [re.sub(r"\s+(?:INFO|WARNING|ERROR)\s+\[事件\]\s*", "  ·  ", redact(line))
                 for line in lines if "[事件]" in line]
    return "\n".join(summaries[-limit:]) or "暂无需要处理的问题。详细运行记录保存在日志目录。"
