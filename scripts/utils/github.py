"""
GitHub CLI (gh) wrapper utilities.
GitHub Issues와 PR을 생성/조회/업데이트하는 함수들.
"""

import subprocess
import json
import logging

logger = logging.getLogger(__name__)


def run_gh(args: list[str], repo: str | None = None, cwd: str | None = None) -> str:
    """gh CLI 명령어를 실행하고 stdout을 반환한다."""
    cmd = ["gh"] + args
    if repo:
        cmd += ["--repo", repo]

    logger.debug(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)

    if result.returncode != 0:
        logger.error(f"gh command failed: {result.stderr}")
        raise RuntimeError(f"gh failed: {result.stderr}")

    return result.stdout.strip()


# =============================================================================
# Issue 관련
# =============================================================================

def list_issues(repo: str, labels: str, state: str = "open") -> list[dict]:
    """특정 라벨의 이슈 목록을 조회한다."""
    output = run_gh([
        "issue", "list",
        "--label", labels,
        "--state", state,
        "--json", "number,title,labels,body,assignees",
        "--limit", "100"
    ], repo=repo)

    return json.loads(output) if output else []


def create_issue(repo: str, title: str, body: str, labels: list[str]) -> int:
    """GitHub Issue를 생성하고 이슈 번호를 반환한다.

    중복 체크는 tech-debt 라벨 기준으로 열린 이슈의 제목만 비교한다.
    (모든 라벨의 AND 조건이 아닌, 기본 라벨로만 검색)
    """
    # 중복 체크: tech-debt 라벨만으로 검색 (상태 라벨은 변할 수 있으므로)
    base_label = labels[0] if labels else ""
    existing = list_issues(repo, labels=base_label)
    for issue in existing:
        if issue["title"] == title:
            logger.info(f"Issue already exists: #{issue['number']} - {title}")
            return issue["number"]

    output = run_gh([
        "issue", "create",
        "--title", title,
        "--body", body,
        "--label", ",".join(labels),
    ], repo=repo)

    # gh issue create는 URL을 반환한다. 번호를 추출.
    issue_url = output.strip()
    issue_number = int(issue_url.rstrip("/").split("/")[-1])
    logger.info(f"Created issue #{issue_number}: {title}")
    return issue_number


def get_issue_comments(repo: str, issue_number: int) -> list[dict]:
    """이슈의 코멘트 목록을 조회한다."""
    output = run_gh([
        "api",
        f"repos/{repo}/issues/{issue_number}/comments",
        "--jq", ".[].body",
    ])

    # gh api --jq는 각 코멘트 body를 줄바꿈으로 구분해 반환
    # 빈 결과면 빈 리스트
    if not output:
        return []

    # JSON array로 다시 조회 (body만 추출하면 구분이 어려우므로)
    raw = run_gh([
        "api",
        f"repos/{repo}/issues/{issue_number}/comments",
    ])
    return json.loads(raw) if raw else []


def find_architect_review(repo: str, issue_number: int) -> str | None:
    """이슈 코멘트에서 Architect Review를 찾아 반환한다."""
    comments = get_issue_comments(repo, issue_number)
    for comment in comments:
        body = comment.get("body", "")
        if body.startswith("## Architect Review"):
            return body
    return None


def add_comment(repo: str, issue_number: int, body: str) -> None:
    """이슈에 코멘트를 추가한다."""
    run_gh([
        "issue", "comment", str(issue_number),
        "--body", body,
    ], repo=repo)
    logger.info(f"Added comment to issue #{issue_number}")


def update_labels(repo: str, issue_number: int, add: list[str] = None, remove: list[str] = None) -> None:
    """이슈의 라벨을 업데이트한다. 하나의 gh edit 호출로 원자적 처리."""
    args = ["issue", "edit", str(issue_number)]
    has_change = False

    if add:
        args += ["--add-label", ",".join(add)]
        has_change = True
    if remove:
        args += ["--remove-label", ",".join(remove)]
        has_change = True

    if not has_change:
        return

    run_gh(args, repo=repo)
    logger.info(f"Updated labels on issue #{issue_number}: +{add} -{remove}")


# =============================================================================
# PR 관련
# =============================================================================

def create_pr(
    repo: str,
    title: str,
    body: str,
    head_branch: str,
    base_branch: str,
    draft: bool = True,
    cwd: str | None = None,
) -> str:
    """Draft PR을 생성하고 PR URL을 반환한다."""
    args = [
        "pr", "create",
        "--title", title,
        "--body", body,
        "--head", head_branch,
        "--base", base_branch,
    ]
    if draft:
        args.append("--draft")

    output = run_gh(args, repo=repo, cwd=cwd)
    logger.info(f"Created PR: {output}")
    return output.strip()
