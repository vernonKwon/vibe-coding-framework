"""
Process Tracker

실행 중인 서비스의 상태를 .workspace/running.json에 기록하고 조회한다.
"""

import json
import os
import signal
from datetime import datetime
from pathlib import Path
from typing import Any


WORKSPACE_DIR = Path(".workspace")
RUNNING_FILE = WORKSPACE_DIR / "running.json"


def _ensure_workspace_dir() -> None:
    """워크스페이스 디렉토리를 생성한다."""
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)


def _load_running() -> dict[str, Any]:
    """running.json을 로드한다. 없으면 빈 dict."""
    if not RUNNING_FILE.exists():
        return {}
    try:
        with open(RUNNING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_running(data: dict[str, Any]) -> None:
    """running.json에 저장한다."""
    _ensure_workspace_dir()
    with open(RUNNING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def register_service(
    name: str,
    pid: int | None,
    port: int,
    start_command: str,
    stop_command: str | None = None,
    service_type: str = "subprocess",
) -> None:
    """서비스를 실행 중 목록에 등록한다."""
    data = _load_running()
    data[name] = {
        "pid": pid,
        "port": port,
        "start_command": start_command,
        "stop_command": stop_command,
        "service_type": service_type,
        "started_at": datetime.now().isoformat(),
    }
    _save_running(data)


def unregister_service(name: str) -> None:
    """서비스를 실행 중 목록에서 제거한다."""
    data = _load_running()
    data.pop(name, None)
    _save_running(data)


def get_running_services() -> dict[str, Any]:
    """실행 중인 서비스 목록을 반환한다. 죽은 프로세스는 자동 정리."""
    data = _load_running()
    alive = {}
    changed = False

    for name, info in data.items():
        if _is_alive(info):
            alive[name] = info
        else:
            changed = True

    if changed:
        _save_running(alive)

    return alive


def is_service_running(name: str) -> bool:
    """특정 서비스가 실행 중인지 확인한다."""
    services = get_running_services()
    return name in services


def get_service_info(name: str) -> dict | None:
    """특정 서비스의 정보를 반환한다."""
    services = get_running_services()
    return services.get(name)


def _is_alive(info: dict) -> bool:
    """프로세스가 살아있는지 확인한다."""
    service_type = info.get("service_type", "subprocess")

    if service_type == "docker-compose":
        # docker-compose 기반은 포트로 확인
        port = info.get("port")
        if port:
            return _is_port_in_use(port)
        return True  # 포트 정보 없으면 alive로 간주

    # subprocess 기반은 PID로 확인
    pid = info.get("pid")
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _is_port_in_use(port: int) -> bool:
    """포트가 사용 중인지 확인한다."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def kill_service(name: str) -> bool:
    """서비스를 강제 종료한다. PID 기반."""
    info = get_service_info(name)
    if not info:
        return False

    pid = info.get("pid")
    if pid is None:
        unregister_service(name)
        return True

    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass

    # 5초 대기 후 여전히 살아있으면 SIGKILL
    import time
    for _ in range(10):
        try:
            os.kill(pid, 0)
            time.sleep(0.5)
        except (OSError, ProcessLookupError):
            break
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass

    unregister_service(name)
    return True
