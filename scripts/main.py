"""
Refactor Agent - Main Orchestrator
범용 개발 워크스페이스 프레임워크.

Usage:
    # 서비스 관리
    python -m scripts.main start <project>
    python -m scripts.main start --group <group>
    python -m scripts.main stop <project>
    python -m scripts.main stop --group <group>
    python -m scripts.main status

    # 리팩터링 파이프라인
    python -m scripts.main refactor --all
    python -m scripts.main refactor --consultant --project <project>
    python -m scripts.main refactor --resolver

    # 하위 호환: --all/--consultant 등 직접 사용 시 refactor로 자동 라우팅
    python -m scripts.main --all
"""

import argparse
import fcntl
import sys
from pathlib import Path

from scripts.utils.logger import setup_logger
from scripts.workspace.config import load_config, validate_config, get_all_project_names
from scripts.consultant.scanner import scan_project
from scripts.architect.reviewer import review_pending_issues
from scripts.resolver.executor import resolve_pending_issues

LOCK_FILE = "/tmp/refactor-agent.lock"

main_logger = setup_logger("main")


def get_enabled_projects(config: dict, target_project: str | None = None) -> dict:
    """활성화된 프로젝트 목록을 반환한다."""
    projects = {}
    for name, proj in config["projects"].items():
        if not proj.get("enabled", True):
            continue
        if target_project and name != target_project:
            continue
        projects[name] = proj
    return projects


def acquire_lock() -> object:
    """파일 기반 잠금을 획득한다. 동시 실행을 방지."""
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(sys.argv))
        lock_fd.flush()
        return lock_fd
    except BlockingIOError:
        lock_fd.close()
        main_logger.error("Another refactor-agent instance is already running. Exiting.")
        sys.exit(1)


def release_lock(lock_fd) -> None:
    """파일 잠금을 해제한다."""
    if lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _run_consultant(config: dict, projects: dict) -> None:
    """Consultant Agent: 코드 스캔 → 이슈 생성"""
    logger = setup_logger("consultant")
    logger.info("=" * 60)
    logger.info("PHASE 1: Consultant Agent - Code Scanning")
    logger.info("=" * 60)

    for name, proj in projects.items():
        logger.info(f"\n--- Project: {name} ---")
        try:
            created = scan_project(proj, config["global"])
            logger.info(f"Created {len(created)} issues for {name}")
        except Exception as e:
            logger.error(f"Failed to scan {name}: {e}")


def _run_architect(config: dict, projects: dict) -> None:
    """Architect Agent: 이슈 리뷰 → 보충 → ready-to-fix"""
    logger = setup_logger("architect")
    logger.info("=" * 60)
    logger.info("PHASE 2: Architect Agent - Issue Review")
    logger.info("=" * 60)

    for name, proj in projects.items():
        logger.info(f"\n--- Project: {name} ---")
        try:
            reviewed = review_pending_issues(proj, config["global"])
            logger.info(f"Reviewed {len(reviewed)} issues for {name}")
        except Exception as e:
            logger.error(f"Failed to review {name}: {e}")


def _run_resolver(config: dict, projects: dict) -> None:
    """Resolver Agent: 코드 수정 → 테스트 → PR 생성"""
    logger = setup_logger("resolver")
    logger.info("=" * 60)
    logger.info("PHASE 3: Resolver Agent - Code Fix & PR")
    logger.info("=" * 60)

    for name, proj in projects.items():
        logger.info(f"\n--- Project: {name} ---")
        try:
            results = resolve_pending_issues(proj, config["global"])
            success = sum(1 for r in results if r["status"] == "success")
            failed = sum(1 for r in results if r["status"] != "success")
            logger.info(f"Results for {name}: {success} success, {failed} failed")

            for r in results:
                if r.get("pr_url"):
                    logger.info(f"  PR: {r['pr_url']}")
        except Exception as e:
            logger.error(f"Failed to resolve {name}: {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refactor Agent - Development Workspace Framework",
    )
    parser.add_argument("--config", type=str, default="config.yaml", help="Global config path")
    parser.add_argument("--projects-file", type=str, default="projects.json", help="Projects file path")

    # 하위 호환 플래그 (refactor subcommand 없이 직접 사용)
    parser.add_argument("--all", action="store_true", help="(compat) Run full refactor pipeline")
    parser.add_argument("--consultant", action="store_true", help="(compat) Run Consultant only")
    parser.add_argument("--architect", action="store_true", help="(compat) Run Architect only")
    parser.add_argument("--resolver", action="store_true", help="(compat) Run Resolver only")
    parser.add_argument("--project", type=str, help="(compat) Target specific project")

    subparsers = parser.add_subparsers(dest="command")

    # --- start ---
    start_parser = subparsers.add_parser("start", help="Start project services")
    start_parser.add_argument("project_name", nargs="?", help="Project name")
    start_parser.add_argument("--group", type=str, help="Start all projects in a group")

    # --- stop ---
    stop_parser = subparsers.add_parser("stop", help="Stop project services")
    stop_parser.add_argument("project_name", nargs="?", help="Project name")
    stop_parser.add_argument("--group", type=str, help="Stop all projects in a group")

    # --- status ---
    subparsers.add_parser("status", help="Show service status")

    # --- refactor ---
    refactor_parser = subparsers.add_parser("refactor", help="Run refactor pipeline")
    refactor_parser.add_argument("--all", action="store_true", dest="refactor_all", help="Run full pipeline")
    refactor_parser.add_argument("--consultant", action="store_true", help="Run Consultant only")
    refactor_parser.add_argument("--architect", action="store_true", help="Run Architect only")
    refactor_parser.add_argument("--resolver", action="store_true", help="Run Resolver only")
    refactor_parser.add_argument("--project", type=str, help="Target specific project")

    return parser


def _handle_start(args, config: dict) -> None:
    from scripts.workspace.service_manager import start_project, start_group, print_status

    if args.group:
        results = start_group(config, args.group)
        for name, ok in results.items():
            status = "OK" if ok else "FAILED"
            main_logger.info(f"  {name}: {status}")
    elif args.project_name:
        ok = start_project(config, args.project_name)
        status = "OK" if ok else "FAILED"
        main_logger.info(f"  {args.project_name}: {status}")
    else:
        main_logger.error("Specify a project name or --group.")
        sys.exit(1)

    print_status(config)


def _handle_stop(args, config: dict) -> None:
    from scripts.workspace.service_manager import stop_project, stop_group, print_status

    if args.group:
        results = stop_group(config, args.group)
        for name, ok in results.items():
            status = "OK" if ok else "FAILED"
            main_logger.info(f"  {name}: {status}")
    elif args.project_name:
        ok = stop_project(config, args.project_name)
        status = "OK" if ok else "FAILED"
        main_logger.info(f"  {args.project_name}: {status}")
    else:
        main_logger.error("Specify a project name or --group.")
        sys.exit(1)

    print_status(config)


def _handle_status(config: dict) -> None:
    from scripts.workspace.service_manager import print_status
    print_status(config)


def _handle_refactor(args, config: dict) -> None:
    run_all = getattr(args, "refactor_all", False)
    do_consultant = args.consultant
    do_architect = args.architect
    do_resolver = args.resolver
    target_project = args.project

    if not any([run_all, do_consultant, do_architect, do_resolver]):
        main_logger.error("Specify --all, --consultant, --architect, or --resolver.")
        sys.exit(1)

    lock_fd = acquire_lock()
    try:
        projects = get_enabled_projects(config, target_project)
        if not projects:
            main_logger.error("No enabled projects found.")
            sys.exit(1)

        main_logger.info(f"Target projects: {list(projects.keys())}")

        if run_all or do_consultant:
            _run_consultant(config, projects)
        if run_all or do_architect:
            _run_architect(config, projects)
        if run_all or do_resolver:
            _run_resolver(config, projects)

        main_logger.info("Pipeline completed.")
    finally:
        release_lock(lock_fd)


def main():
    parser = _build_parser()
    args = parser.parse_args()

    # 설정 로드
    config = load_config(
        projects_path=args.projects_file,
        config_path=args.config,
        base_dir=Path.cwd(),
    )
    validate_config(config)

    # 하위 호환: --all, --consultant, --architect, --resolver 직접 사용
    if any([args.all, args.consultant, args.architect, args.resolver]):
        class CompatArgs:
            refactor_all = args.all
            consultant = args.consultant
            architect = args.architect
            resolver = args.resolver
            project = args.project

        _handle_refactor(CompatArgs(), config)
        return

    # subcommand 처리
    if args.command == "start":
        _handle_start(args, config)
    elif args.command == "stop":
        _handle_stop(args, config)
    elif args.command == "status":
        _handle_status(config)
    elif args.command == "refactor":
        _handle_refactor(args, config)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
