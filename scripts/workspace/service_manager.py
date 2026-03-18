"""
Service Manager

프로젝트 서비스의 시작, 종료, 상태 확인을 관리한다.
인프라 의존성은 docker-compose.infra.yml로 관리.
"""

import os
import subprocess
import time
from pathlib import Path

import requests

from scripts.utils.logger import setup_logger
from scripts.workspace.config import (
    get_project_directory,
    get_project_service_config,
    get_all_project_names,
    resolve_group,
)
from scripts.workspace.port_manager import check_port_conflicts, is_port_available
from scripts.workspace.process_tracker import (
    get_running_services,
    is_service_running,
    kill_service,
    register_service,
    unregister_service,
)

logger = setup_logger("service-manager")

INFRA_COMPOSE_FILE = "docker-compose.infra.yml"


def start_project(config: dict, project_name: str) -> bool:
    """단일 프로젝트 서비스를 시작한다."""
    if is_service_running(project_name):
        logger.info(f"[{project_name}] Already running, skipping.")
        return True

    service_cfg = get_project_service_config(config, project_name)
    if not service_cfg or not service_cfg.get("start"):
        logger.warning(f"[{project_name}] No service config in .workspace.yaml.")
        return False

    # 인프라 의존성 먼저 시작
    deps = service_cfg.get("dependencies", [])
    for dep in deps:
        if not _start_infrastructure(dep):
            logger.error(f"[{project_name}] Failed to start dependency: {dep}")
            return False

    project_dir = get_project_directory(config, project_name)
    start_cmd = service_cfg["start"]
    stop_cmd = service_cfg.get("stop")
    port = service_cfg.get("port")

    # 포트 충돌 검사
    env = None
    actual_port = port
    if port and not is_port_available(port):
        port_env_var = service_cfg.get("port_override_env")
        if port_env_var:
            assignments = check_port_conflicts([{"name": project_name, "port": port}])
            actual_port = assignments.get(project_name, port)
            if actual_port != port:
                logger.info(f"[{project_name}] Port {port} in use, remapping to {actual_port}")
                env = {**os.environ, port_env_var: str(actual_port)}
        else:
            logger.error(f"[{project_name}] Port {port} is in use and no port_override_env defined.")
            return False

    # docker-compose 기반인지 판별
    is_docker_compose = "docker-compose" in start_cmd or "docker compose" in start_cmd

    if is_docker_compose:
        service_type = "docker-compose"
        pid = _run_docker_compose(start_cmd, project_dir, env)
    else:
        service_type = "subprocess"
        pid = _run_background_process(start_cmd, project_dir, env)

    if pid is None and not is_docker_compose:
        logger.error(f"[{project_name}] Failed to start.")
        return False

    register_service(
        name=project_name,
        pid=pid,
        port=actual_port or 0,
        start_command=start_cmd,
        stop_command=stop_cmd,
        service_type=service_type,
    )

    # Health check
    health_url = service_cfg.get("health_check")
    if health_url:
        # 상대 경로면 localhost:port 조합
        if health_url.startswith("/"):
            health_url = f"http://localhost:{actual_port}{health_url}"
        elif actual_port and actual_port != port:
            health_url = health_url.replace(str(port), str(actual_port))

        if _wait_for_health(health_url, project_name):
            logger.info(f"[{project_name}] Started successfully on port {actual_port}.")
        else:
            logger.warning(f"[{project_name}] Started but health check not passing yet.")
    else:
        logger.info(f"[{project_name}] Started (no health check configured).")

    return True


def stop_project(config: dict, project_name: str) -> bool:
    """단일 프로젝트 서비스를 종료한다."""
    if not is_service_running(project_name):
        logger.info(f"[{project_name}] Not running.")
        return True

    service_cfg = get_project_service_config(config, project_name)
    stop_cmd = service_cfg.get("stop") if service_cfg else None

    info = get_running_services().get(project_name, {})
    service_type = info.get("service_type", "subprocess")

    if stop_cmd and service_type == "docker-compose":
        project_dir = get_project_directory(config, project_name)
        try:
            subprocess.run(
                stop_cmd, shell=True, cwd=project_dir,
                timeout=30, capture_output=True,
            )
            unregister_service(project_name)
            logger.info(f"[{project_name}] Stopped via docker-compose.")
            return True
        except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
            logger.error(f"[{project_name}] Stop command failed: {e}")
            return False
    else:
        success = kill_service(project_name)
        if success:
            logger.info(f"[{project_name}] Stopped.")
        else:
            logger.error(f"[{project_name}] Failed to stop.")
        return success


def start_group(config: dict, group_name: str) -> dict[str, bool]:
    """그룹의 모든 프로젝트 서비스를 시작한다."""
    project_names = resolve_group(config, group_name)
    results = {}
    for name in project_names:
        results[name] = start_project(config, name)
    return results


def stop_group(config: dict, group_name: str) -> dict[str, bool]:
    """그룹의 모든 프로젝트 서비스를 종료한다."""
    project_names = resolve_group(config, group_name)
    results = {}
    for name in project_names:
        results[name] = stop_project(config, name)
    return results


def print_status(config: dict) -> None:
    """모든 서비스의 현재 상태를 테이블로 출력한다."""
    running = get_running_services()
    all_projects = get_all_project_names(config)
    project_yamls = config.get("_workspace", {}).get("project_yamls", {})

    print()
    print(f"{'Name':<25} {'Port':<8} {'Status':<12} {'PID':<10} {'Started'}")
    print("-" * 75)

    # 인프라 (running.json에서 infra: 접두사로 식별)
    for tracker_name, info in running.items():
        if tracker_name.startswith("infra:"):
            display_name = tracker_name.removeprefix("infra:")
            print(
                f"{display_name:<25} {info.get('port', '-'):<8} "
                f"{'running':<12} {info.get('pid', '-'):<10} {info.get('started_at', '-')}"
            )

    # 프로젝트 서비스
    for name in all_projects:
        info = running.get(name)
        if info:
            print(
                f"{name:<25} {info.get('port', '-'):<8} "
                f"{'running':<12} {info.get('pid', '-'):<10} {info.get('started_at', '-')}"
            )
        else:
            svc = project_yamls.get(name, {}).get("service", {})
            port = svc.get("port", "-")
            print(f"{name:<25} {port:<8} {'stopped':<12} {'-':<10} -")

    print()


# ---------------------------------------------------------------------------
# Infrastructure (docker-compose.infra.yml)
# ---------------------------------------------------------------------------

def _start_infrastructure(infra_name: str) -> bool:
    """docker-compose.infra.yml의 서비스를 시작한다."""
    tracker_name = f"infra:{infra_name}"
    if is_service_running(tracker_name):
        logger.info(f"[{infra_name}] Infrastructure already running.")
        return True

    if not Path(INFRA_COMPOSE_FILE).exists():
        logger.error(f"[{infra_name}] {INFRA_COMPOSE_FILE} not found.")
        return False

    logger.info(f"[{infra_name}] Starting infrastructure...")
    cmd = f"docker compose -f {INFRA_COMPOSE_FILE} up -d {infra_name}"

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            logger.error(f"[{infra_name}] Start failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"[{infra_name}] Start timed out.")
        return False

    register_service(
        name=tracker_name,
        pid=None,
        port=0,
        start_command=cmd,
        stop_command=f"docker compose -f {INFRA_COMPOSE_FILE} stop {infra_name}",
        service_type="docker-compose",
    )

    logger.info(f"[{infra_name}] Infrastructure started.")
    return True


def stop_infrastructure(infra_name: str) -> bool:
    """docker-compose.infra.yml의 서비스를 종료한다."""
    tracker_name = f"infra:{infra_name}"
    cmd = f"docker compose -f {INFRA_COMPOSE_FILE} stop {infra_name}"

    try:
        subprocess.run(cmd, shell=True, timeout=30, capture_output=True)
        unregister_service(tracker_name)
        logger.info(f"[{infra_name}] Infrastructure stopped.")
        return True
    except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
        logger.error(f"[{infra_name}] Stop failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_docker_compose(cmd: str, cwd: Path, env: dict | None = None) -> int | None:
    """docker-compose 명령어를 실행한다."""
    try:
        subprocess.run(
            cmd, shell=True, cwd=cwd, env=env,
            timeout=120, capture_output=True, text=True,
        )
        return None
    except subprocess.TimeoutExpired:
        return None


def _run_background_process(cmd: str, cwd: Path, env: dict | None = None) -> int | None:
    """백그라운드 프로세스를 시작하고 PID를 반환한다."""
    try:
        proc = subprocess.Popen(
            cmd, shell=True, cwd=cwd, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return proc.pid
    except OSError as e:
        logger.error(f"Failed to start process: {e}")
        return None


def _wait_for_health(url: str, name: str, timeout: int = 60) -> bool:
    """Health check URL에 폴링하여 서비스 준비 상태를 확인한다."""
    logger.info(f"[{name}] Waiting for health check: {url}")
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code < 500:
                logger.info(f"[{name}] Health check passed.")
                return True
        except requests.ConnectionError:
            pass
        time.sleep(2)

    logger.warning(f"[{name}] Health check timed out after {timeout}s.")
    return False
