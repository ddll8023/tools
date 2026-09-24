"""日志配置工具"""

import re
import logging


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] [%(filename)s:%(lineno)d] [%(name)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


class ProgressLogHandler(logging.Handler):
    """拦截日志消息匹配阶段关键词，用于更新任务进度"""

    def __init__(self, task_id: str, stage_patterns: list, write_status_fn):
        super().__init__(level=logging.INFO)
        self.task_id = task_id
        self.stage_patterns = stage_patterns
        self._write_status = write_status_fn
        self._reached = set()

    def emit(self, record):
        msg = self.format(record)
        for pattern, progress, stage in self.stage_patterns:
            if re.search(pattern, msg, re.IGNORECASE):
                key = f"{progress}_{stage}"
                if key not in self._reached:
                    self._reached.add(key)
                    self._write_status(self.task_id, progress, stage)
                return
