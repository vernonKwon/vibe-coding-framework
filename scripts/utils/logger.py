"""
Logging configuration.
파일 + 콘솔 출력, 에이전트별 로그 분리.
"""

import logging
import os
from datetime import datetime

DEFAULT_LOG_DIR = "/var/log/refactor-agent"


def _resolve_log_dir(log_dir: str | None = None) -> str:
    """로그 디렉토리를 환경변수/인자/기본값 순으로 결정한다."""
    if log_dir:
        return log_dir
    return os.environ.get("REFACTOR_AGENT_LOG_DIR", DEFAULT_LOG_DIR)


def setup_logger(agent_name: str, log_dir: str | None = None) -> logging.Logger:
    """에이전트별 로거를 설정한다."""
    resolved_dir = _resolve_log_dir(log_dir)

    logger = logging.getLogger(agent_name)

    # 이미 핸들러가 설정된 경우 중복 방지
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # 포맷
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 파일 핸들러 (날짜별) — 디렉토리 생성 실패 시 파일 로깅 스킵
    try:
        os.makedirs(resolved_dir, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        file_handler = logging.FileHandler(
            os.path.join(resolved_dir, f"{agent_name}_{today}.log"),
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        logger.warning(f"Cannot create log directory: {resolved_dir}. File logging disabled.")

    return logger
