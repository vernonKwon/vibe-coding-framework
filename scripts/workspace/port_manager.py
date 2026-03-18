"""
Port Manager

포트 충돌을 감지하고, 충돌 시 대체 포트를 자동 할당한다.
"""

import socket
from scripts.workspace.process_tracker import get_running_services


def is_port_available(port: int) -> bool:
    """포트가 사용 가능한지 확인한다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) != 0


def find_available_port(start_port: int, max_attempts: int = 100) -> int:
    """start_port부터 사용 가능한 포트를 찾는다."""
    for offset in range(max_attempts):
        port = start_port + offset
        if is_port_available(port):
            return port
    raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_attempts}")


def check_port_conflicts(projects_to_start: list[dict]) -> dict[str, int]:
    """시작할 프로젝트들의 포트 충돌을 검사하고 할당 결과를 반환한다.

    Args:
        projects_to_start: [{"name": str, "port": int}, ...]

    Returns:
        {"project_name": assigned_port, ...}
    """
    assigned: dict[str, int] = {}
    used_ports: set[int] = set()

    # 이미 실행 중인 서비스의 포트 수집
    running = get_running_services()
    for info in running.values():
        port = info.get("port")
        if port:
            used_ports.add(port)

    for proj in projects_to_start:
        name = proj["name"]
        desired_port = proj["port"]

        if desired_port not in used_ports and is_port_available(desired_port):
            assigned[name] = desired_port
            used_ports.add(desired_port)
        else:
            # 충돌 → 대체 포트 찾기
            new_port = find_available_port(desired_port + 1)
            assigned[name] = new_port
            used_ports.add(new_port)

    return assigned
