"""
Resolver Agent - Code Executor
ready-to-fix 라벨이 붙은 이슈를 코드로 해결하고 Draft PR을 생성한다.

각 이슈는 git worktree로 격리된 환경에서 처리된다.
"""

import subprocess
import logging
import tempfile
import shutil
from pathlib import Path

from scripts.utils.claude import resolve_issue
from scripts.utils.github import (
    list_issues, add_comment, update_labels, create_pr, find_architect_review,
)
from scripts.resolver.verifier import run_test, run_build, run_lint, TestResult
from scripts.consultant.scanner import load_playbooks

logger = logging.getLogger("resolver")


class GitError(Exception):
    """git 명령어 실패 시 발생하는 예외."""
    pass


def _run_git(args: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    """git 명령어를 실행한다.

    Args:
        check: True이면 실패 시 GitError를 발생시킨다.
    """
    cmd = ["git"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)

    if check and result.returncode != 0:
        error_msg = f"git {' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}"
        logger.error(error_msg)
        raise GitError(error_msg)

    return result


def resolve_pending_issues(project_config: dict, global_config: dict) -> list[dict]:
    """
    ready-to-fix 라벨이 붙은 이슈를 가져와 해결한다.

    Returns:
        결과 리스트 [{"issue": number, "status": "success"|"failed", "pr_url": str|None}]
    """
    repo = project_config["repo"]
    project_path = project_config["path"]
    base_branch = project_config["base_branch"]
    labels = global_config["labels"]
    max_retries = global_config["max_retry_on_test_fail"]

    # 1. ready-to-fix 이슈 조회
    try:
        issues = list_issues(repo, labels=labels["ready_to_fix"])
    except RuntimeError as e:
        logger.error(f"Failed to fetch issues from {repo}: {e}")
        return []

    if not issues:
        logger.info(f"No issues ready to fix in {repo}")
        return []

    logger.info(f"Found {len(issues)} issues to resolve in {repo}")

    # 2. Playbook 로드
    playbook_content = load_playbooks(
        project_config["playbooks"],
        project_path,
    )

    results = []
    for issue in issues:
        result = _resolve_single_issue(
            repo=repo,
            issue=issue,
            project_path=project_path,
            base_branch=base_branch,
            playbook_content=playbook_content,
            commands=project_config["commands"],
            labels=labels,
            max_retries=max_retries,
        )
        results.append(result)

    return results


def _resolve_single_issue(
    repo: str,
    issue: dict,
    project_path: str,
    base_branch: str,
    playbook_content: str,
    commands: dict,
    labels: dict,
    max_retries: int,
) -> dict:
    """단일 이슈를 해결한다. git worktree로 격리된 환경에서 작업."""
    issue_number = issue["number"]
    branch_name = f"fix/issue-{issue_number}"
    worktree_dir = None

    logger.info(f"Resolving issue #{issue_number}: {issue['title']}")

    try:
        # ---- Step 1: 라벨을 in-progress로 전환 ----
        update_labels(repo, issue_number, add=[labels["in_progress"]], remove=[labels["ready_to_fix"]])

        # ---- Step 2: git worktree로 격리 환경 생성 ----
        _run_git(["fetch", "origin"], cwd=project_path)

        # 이전에 남은 동일 브랜치 정리 (멱등성)
        existing_branch = _run_git(["branch", "--list", branch_name], cwd=project_path, check=False)
        if existing_branch.stdout.strip():
            _run_git(["branch", "-D", branch_name], cwd=project_path, check=False)

        # 브랜치 생성 + worktree
        _run_git(["branch", branch_name, f"origin/{base_branch}"], cwd=project_path)
        worktree_dir = tempfile.mkdtemp(prefix=f"refactor-{issue_number}-")
        _run_git(["worktree", "add", worktree_dir, branch_name], cwd=project_path)

        logger.info(f"Working in isolated worktree: {worktree_dir}")

        # ---- Step 3: Pre-test (현재 코드가 Green인지 확인) ----
        test_cmd = commands["test"]
        logger.info(f"Running pre-test: {test_cmd}")
        pre_test = run_test(test_cmd, cwd=worktree_dir)

        if not pre_test.success:
            logger.error(f"Pre-test failed for issue #{issue_number}")
            add_comment(repo, issue_number,
                f"## Pre-test Failed\n\n"
                f"기존 테스트가 실패하여 작업을 중단합니다.\n\n"
                f"```\n{pre_test.log[:2000]}\n```")
            update_labels(repo, issue_number, add=[labels["fix_failed"]], remove=[labels["in_progress"]])
            return {"issue": issue_number, "status": "pre_test_failed", "pr_url": None}

        # ---- Step 4: Architect Review 가져오기 ----
        architect_review = find_architect_review(repo, issue_number)
        if not architect_review:
            logger.warning(f"No Architect Review found for issue #{issue_number}, using issue body")
            architect_review = issue.get("body", "")

        # ---- Step 5: Claude Code로 코드 수정 (재시도 루프) ----
        for attempt in range(1, max_retries + 1):
            logger.info(f"Attempt {attempt}/{max_retries} for issue #{issue_number}")

            resolve_result = resolve_issue(
                project_path=worktree_dir,
                issue_body=issue["body"],
                architect_review=architect_review,
                playbook_content=playbook_content,
            )

            if resolve_result.startswith("ERROR:"):
                logger.error(f"Claude Code failed: {resolve_result}")
                continue

            # ---- Step 6: 빌드 + 린트 + 타입체크 + 테스트 ----
            # 6a. 빌드
            build_cmd = commands.get("build")
            if build_cmd:
                logger.info(f"Running build: {build_cmd}")
                build_result = run_build(build_cmd, cwd=worktree_dir)
                if not build_result.success:
                    logger.warning(f"Build failed (attempt {attempt}): {build_result.log[:500]}")
                    _run_git(["checkout", "."], cwd=worktree_dir, check=False)
                    _run_git(["clean", "-fd"], cwd=worktree_dir, check=False)
                    continue

            # 6b. 린트
            lint_cmd = commands.get("lint")
            if lint_cmd:
                logger.info(f"Running lint: {lint_cmd}")
                lint_result = run_lint(lint_cmd, cwd=worktree_dir)
                if not lint_result.success:
                    logger.warning(f"Lint failed (attempt {attempt}): {lint_result.log[:500]}")
                    _run_git(["checkout", "."], cwd=worktree_dir, check=False)
                    _run_git(["clean", "-fd"], cwd=worktree_dir, check=False)
                    continue

            # 6c. 타입 체크
            type_check_cmd = commands.get("type_check")
            if type_check_cmd:
                logger.info(f"Running type check: {type_check_cmd}")
                type_result = run_test(type_check_cmd, cwd=worktree_dir)
                if not type_result.success:
                    logger.warning(f"Type check failed (attempt {attempt}): {type_result.log[:500]}")
                    _run_git(["checkout", "."], cwd=worktree_dir, check=False)
                    _run_git(["clean", "-fd"], cwd=worktree_dir, check=False)
                    continue

            # 6d. 테스트
            logger.info(f"Running post-test: {test_cmd}")
            post_test = run_test(test_cmd, cwd=worktree_dir)

            if post_test.success:
                # ---- Step 7: Commit & Push & PR ----
                _run_git(["add", "."], cwd=worktree_dir)

                # 변경사항이 있는지 확인
                diff_check = _run_git(["diff", "--cached", "--quiet"], cwd=worktree_dir, check=False)
                if diff_check.returncode == 0:
                    logger.warning(f"No changes made for issue #{issue_number}")
                    add_comment(repo, issue_number, "## No Changes\n\nClaude Code가 코드를 수정하지 않았습니다.")
                    update_labels(repo, issue_number, add=[labels["fix_failed"]], remove=[labels["in_progress"]])
                    return {"issue": issue_number, "status": "no_changes", "pr_url": None}

                _run_git([
                    "commit", "-m",
                    f"refactor: resolve issue #{issue_number}\n\n{issue['title']}"
                ], cwd=worktree_dir)
                _run_git(["push", "-u", "origin", branch_name], cwd=worktree_dir)

                pr_body = _format_pr_body(issue_number, issue["title"], resolve_result, pre_test, post_test, commands)
                pr_url = create_pr(
                    repo=repo,
                    title=f"refactor: {issue['title']}",
                    body=pr_body,
                    head_branch=branch_name,
                    base_branch=base_branch,
                    draft=True,
                    cwd=worktree_dir,
                )

                update_labels(repo, issue_number, add=[labels["completed"]], remove=[labels["in_progress"]])
                logger.info(f"Issue #{issue_number} resolved! PR: {pr_url}")
                return {"issue": issue_number, "status": "success", "pr_url": pr_url}
            else:
                logger.warning(f"Post-test failed (attempt {attempt}): {post_test.log[:500]}")
                _run_git(["checkout", "."], cwd=worktree_dir, check=False)
                _run_git(["clean", "-fd"], cwd=worktree_dir, check=False)

        # 모든 재시도 실패
        logger.error(f"All {max_retries} attempts failed for issue #{issue_number}")
        add_comment(repo, issue_number,
            f"## Resolution Failed\n\n{max_retries}회 시도 모두 실패했습니다. 수동 확인이 필요합니다.")
        update_labels(repo, issue_number, add=[labels["fix_failed"]], remove=[labels["in_progress"]])
        return {"issue": issue_number, "status": "failed", "pr_url": None}

    except GitError as e:
        logger.error(f"Git error resolving issue #{issue_number}: {e}")
        _safe_update_labels(repo, issue_number, labels, "fix_failed", "in_progress")
        add_comment(repo, issue_number, f"## Git Error\n\n```\n{str(e)[:2000]}\n```")
        return {"issue": issue_number, "status": "git_error", "pr_url": None}

    except Exception as e:
        logger.error(f"Unexpected error resolving issue #{issue_number}: {e}")
        _safe_update_labels(repo, issue_number, labels, "fix_failed", "in_progress")
        return {"issue": issue_number, "status": "error", "pr_url": None}

    finally:
        # worktree 정리 (항상 실행)
        if worktree_dir:
            try:
                _run_git(["worktree", "remove", "--force", worktree_dir], cwd=project_path, check=False)
            except Exception:
                pass
            # worktree remove가 실패해도 디렉토리는 정리
            if Path(worktree_dir).exists():
                shutil.rmtree(worktree_dir, ignore_errors=True)


def _safe_update_labels(repo: str, issue_number: int, labels: dict, add_key: str, remove_key: str) -> None:
    """라벨 업데이트 실패 시에도 크래시하지 않는 안전한 업데이트."""
    try:
        update_labels(repo, issue_number, add=[labels[add_key]], remove=[labels[remove_key]])
    except Exception as e:
        logger.error(f"Failed to update labels on #{issue_number}: {e}")


def _format_pr_body(
    issue_number: int,
    title: str,
    change_summary: str,
    pre_test: TestResult,
    post_test: TestResult,
    commands: dict,
) -> str:
    """PR 본문을 포맷팅한다."""
    verification_steps = []
    for step_name, cmd_key in [("Build", "build"), ("Lint", "lint"), ("Type Check", "type_check"), ("Test", "test")]:
        cmd = commands.get(cmd_key)
        if cmd:
            verification_steps.append(f"- `{cmd}`")

    return f"""## Summary

Resolves #{issue_number}

{change_summary[:3000]}

## Verification Steps
{chr(10).join(verification_steps)}

## Test Result
- **Pre-test**: PASS
- **Post-test**: {'PASS' if post_test.success else 'FAIL'}

```
{post_test.log[:2000]}
```

---
_이 PR은 Resolver Agent에 의해 자동 생성되었습니다._
_반드시 사람이 리뷰 후 머지해주세요._"""
