"""
Consultant Agent - Code Scanner
코드베이스를 스캔하여 기술 부채를 식별하고 GitHub Issue를 생성한다.
"""

import json
import logging
from pathlib import Path

from scripts.utils.claude import analyze_code
from scripts.utils.github import create_issue

logger = logging.getLogger("consultant")


def load_playbooks(playbook_paths: list[str], project_path: str) -> str:
    """여러 playbook 파일을 하나로 합쳐 반환한다.

    하나도 로드되지 않으면 ValueError를 발생시킨다.
    """
    combined = []
    for path in playbook_paths:
        resolved = path.replace("${project_path}", project_path)
        p = Path(resolved)
        if p.exists():
            combined.append(f"# --- {p.name} ---\n{p.read_text(encoding='utf-8')}")
        else:
            logger.warning(f"Playbook not found: {resolved}")

    if not combined:
        raise ValueError(f"No playbook files found. Checked: {playbook_paths}")

    return "\n\n".join(combined)


def parse_analysis_result(raw_output: str) -> list[dict]:
    """Claude Code의 분석 결과에서 JSON 부분을 추출한다."""
    start = raw_output.find("[")
    end = raw_output.rfind("]") + 1

    if start == -1 or end == 0:
        logger.error("No JSON array found in analysis output")
        return []

    try:
        items = json.loads(raw_output[start:end])
        # 기본 필드 검증
        validated = []
        for item in items:
            if "title" not in item or "description" not in item:
                logger.warning(f"Skipping malformed item: {item}")
                continue
            validated.append(item)
        return validated
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse analysis JSON: {e}")
        return []


def scan_project(project_config: dict, global_config: dict) -> list[int]:
    """
    단일 프로젝트를 스캔하여 기술 부채 이슈를 생성한다.

    Returns:
        생성된 이슈 번호 리스트
    """
    project_path = project_config["path"]
    repo = project_config["repo"]
    labels = global_config["labels"]

    logger.info(f"Scanning project: {repo} at {project_path}")

    # 1. Playbook 로드
    playbook_content = load_playbooks(
        project_config["playbooks"],
        project_path,
    )

    # 2. Claude Code로 코드 분석
    scan_patterns = project_config.get("scan", {}).get("include", ["src/**"])
    raw_result = analyze_code(project_path, playbook_content, scan_patterns)

    if raw_result.startswith("ERROR:"):
        logger.error(f"Code analysis failed: {raw_result}")
        return []

    # 3. 분석 결과 파싱
    debt_items = parse_analysis_result(raw_result)
    logger.info(f"Found {len(debt_items)} tech debt items")

    # 4. 각 항목에 대해 GitHub Issue 생성 (개별 에러 처리)
    created_issues = []
    for item in debt_items:
        try:
            title = f"[Tech Debt] {item['title']}"
            body = _format_issue_body(item)
            issue_labels = [
                labels["consultant_created"],
                labels["needs_architect_review"],
            ]

            issue_number = create_issue(repo, title, body, issue_labels)
            created_issues.append(issue_number)
        except RuntimeError as e:
            logger.error(f"Failed to create issue for '{item.get('title', '?')}': {e}")
            continue

    logger.info(f"Created {len(created_issues)} issues for {repo}")
    return created_issues


def _format_issue_body(item: dict) -> str:
    """분석 결과 항목을 이슈 본문으로 포맷팅한다."""
    files = "\n".join(f"- `{f}`" for f in item.get("files", []))
    rules = "\n".join(f"- {r}" for r in item.get("violated_rules", []))

    return f"""## 분석 결과

**우선순위**: {item.get('priority', 'P3')}
**카테고리**: {item.get('category', 'unknown')}

### 현상
{item.get('description', '')}

### 관련 파일
{files}

### Playbook 위반 항목
{rules}

---
_이 이슈는 Consultant Agent에 의해 자동 생성되었습니다._
_Architect Agent의 리뷰를 기다립니다._"""
