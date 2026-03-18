"""
Workspace Config Loader

projects.json(디렉토리 매핑 + 그룹) + 각 프로젝트의 .workspace.yaml + config.yaml(전역)을
병합하여 파이프라인이 기대하는 dict 형태로 변환한다.

기존 scanner.py, reviewer.py, executor.py는 수정 없이 동작한다.
"""

import json
from pathlib import Path

import yaml

WORKSPACE_YAML = ".workspace.yaml"


def load_projects(projects_path: str = "projects.json") -> dict:
    """projects.json을 로드한다."""
    path = Path(projects_path)
    if not path.exists():
        raise FileNotFoundError(f"projects.json not found: {path.resolve()}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_global_config(config_path: str = "config.yaml") -> dict:
    """config.yaml에서 global 섹션만 로드한다."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"config.yaml not found: {path.resolve()}")

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if "global" not in config:
        raise ValueError("config.yaml: 'global' section is required")

    return config["global"]


def resolve_workspace_root(projects_data: dict, base_dir: Path | None = None) -> Path:
    """workspace_root를 projects.json 위치 기준으로 절대 경로로 해소한다."""
    if base_dir is None:
        base_dir = Path.cwd()

    root = projects_data.get("workspace_root", "..")
    return (base_dir / root).resolve()


def _load_workspace_yaml(project_dir: Path) -> dict:
    """프로젝트 디렉토리의 .workspace.yaml을 로드한다. 없으면 빈 dict."""
    ws_file = project_dir / WORKSPACE_YAML
    if not ws_file.exists():
        return {}

    with open(ws_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _auto_discover_playbooks(project_name: str, project_path: str) -> list[str]:
    """플레이북을 컨벤션 기반으로 자동 탐색한다.

    각 프로젝트 레포에서 CLAUDE.md + PLAYBOOK.md를 찾는다.
    존재하는 파일만 반환.
    """
    candidates = [
        f"{project_path}/CLAUDE.md",
        f"{project_path}/PLAYBOOK.md",
    ]
    return [p for p in candidates if Path(p).exists()]


def _convert_project_for_pipeline(
    name: str,
    project_dir: Path,
    ws_yaml: dict,
) -> dict:
    """프로젝트의 .workspace.yaml을 기존 파이프라인이 기대하는 dict로 변환한다."""
    project_path = str(project_dir)
    refactor = ws_yaml.get("refactor", {})
    playbooks = refactor.get("playbooks") or _auto_discover_playbooks(name, project_path)

    return {
        "enabled": refactor.get("enabled", True),
        "path": project_path,
        "repo": ws_yaml.get("repo", ""),
        "base_branch": ws_yaml.get("base_branch", "main"),
        "language": ws_yaml.get("language", ""),
        "framework": ws_yaml.get("framework", ""),
        "playbooks": playbooks,
        "commands": refactor.get("commands", {}),
        "scan": refactor.get("scan", {}),
    }


def load_config(
    projects_path: str = "projects.json",
    config_path: str = "config.yaml",
    base_dir: Path | None = None,
) -> dict:
    """projects.json + 각 프로젝트의 .workspace.yaml + config.yaml을 병합한다.

    Returns:
        {
            "global": { ... },
            "projects": {
                "<name>": { "enabled": ..., "path": ..., ... },
                ...
            },
            "_workspace": {
                "project_dirs": { "<name>": Path(...), ... },
                "project_yamls": { "<name>": { ... }, ... },
                "groups": { "<group>": [...], ... },
                "workspace_root": Path(...)
            }
        }
    """
    projects_data = load_projects(projects_path)
    global_config = load_global_config(config_path)
    workspace_root = resolve_workspace_root(projects_data, base_dir)

    project_dirs: dict[str, Path] = {}
    project_yamls: dict[str, dict] = {}
    pipeline_projects: dict[str, dict] = {}

    for name, directory in projects_data.get("projects", {}).items():
        project_dir = (workspace_root / directory).resolve()
        project_dirs[name] = project_dir

        ws_yaml = _load_workspace_yaml(project_dir)
        project_yamls[name] = ws_yaml

        pipeline_projects[name] = _convert_project_for_pipeline(
            name, project_dir, ws_yaml
        )

    return {
        "global": global_config,
        "projects": pipeline_projects,
        "_workspace": {
            "project_dirs": project_dirs,
            "project_yamls": project_yamls,
            "groups": projects_data.get("groups", {}),
            "workspace_root": workspace_root,
        },
    }


def resolve_group(config: dict, group_name: str) -> list[str]:
    """그룹 이름을 프로젝트 이름 목록으로 해소한다."""
    groups = config.get("_workspace", {}).get("groups", {})
    if group_name not in groups:
        raise ValueError(f"Unknown group: {group_name}")
    return groups[group_name]


def get_project_service_config(config: dict, project_name: str) -> dict:
    """프로젝트의 서비스 설정을 반환한다 (.workspace.yaml의 service 섹션)."""
    yamls = config.get("_workspace", {}).get("project_yamls", {})
    if project_name not in yamls:
        raise ValueError(f"Unknown project: {project_name}")
    return yamls[project_name].get("service", {})


def get_project_directory(config: dict, project_name: str) -> Path:
    """프로젝트의 절대 경로를 반환한다."""
    dirs = config.get("_workspace", {}).get("project_dirs", {})
    if project_name not in dirs:
        raise ValueError(f"Unknown project: {project_name}")
    return dirs[project_name]


def get_all_project_names(config: dict) -> list[str]:
    """등록된 모든 프로젝트 이름을 반환한다."""
    return list(config.get("_workspace", {}).get("project_dirs", {}).keys())


def validate_config(config: dict) -> None:
    """설정의 필수 필드를 검증한다."""
    global_cfg = config.get("global", {})

    if "labels" not in global_cfg:
        raise ValueError("config.yaml: 'global.labels' section is required")

    required_labels = [
        "consultant_created", "needs_architect_review",
        "ready_to_fix", "in_progress", "fix_failed", "completed",
    ]
    for label in required_labels:
        if label not in global_cfg["labels"]:
            raise ValueError(f"config.yaml: 'global.labels.{label}' is required")

    # 리팩터링 활성화된 프로젝트의 필수 필드 검증
    # .workspace.yaml이 없는 프로젝트는 스킵 (서비스/리팩터링 대상이 아님)
    for name, proj in config["projects"].items():
        if not proj.get("enabled", True):
            continue
        # .workspace.yaml이 없으면 검증 스킵
        ws_yaml = config.get("_workspace", {}).get("project_yamls", {}).get(name, {})
        if not ws_yaml:
            continue
        for field in ["path", "repo", "base_branch", "commands"]:
            if not proj.get(field):
                raise ValueError(
                    f"Project '{name}': missing '{field}' in .workspace.yaml"
                )
        if "test" not in proj.get("commands", {}):
            raise ValueError(
                f"Project '{name}': missing 'commands.test' in .workspace.yaml"
            )
