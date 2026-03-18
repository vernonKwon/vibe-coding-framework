"""
Architect Agent - Issue Reviewer
needs-review 라벨이 붙은 이슈를 분석하여 보충하고,
ready-to-fix 라벨로 전환한다.
"""

import logging

from scripts.utils.claude import review_issue
from scripts.utils.github import list_issues, add_comment, update_labels
from scripts.consultant.scanner import load_playbooks

logger = logging.getLogger("architect")


def review_pending_issues(project_config: dict, global_config: dict) -> list[int]:
    """
    needs-review 라벨이 붙은 이슈를 가져와 Architect 리뷰를 수행한다.

    Returns:
        리뷰 완료된 이슈 번호 리스트
    """
    repo = project_config["repo"]
    project_path = project_config["path"]
    labels = global_config["labels"]

    # 1. needs-review 이슈 조회
    issues = list_issues(repo, labels=labels["needs_architect_review"])
    if not issues:
        logger.info(f"No pending issues for review in {repo}")
        return []

    logger.info(f"Found {len(issues)} issues to review in {repo}")

    # 2. Playbook 로드
    playbook_content = load_playbooks(
        project_config["playbooks"],
        project_path,
    )

    # 3. 각 이슈에 대해 Architect 리뷰 수행
    reviewed = []
    for issue in issues:
        issue_number = issue["number"]
        logger.info(f"Reviewing issue #{issue_number}: {issue['title']}")

        try:
            # Claude Code로 이슈 분석 + 보충
            review_result = review_issue(
                project_path=project_path,
                issue_body=issue["body"],
                playbook_content=playbook_content,
            )

            if review_result.startswith("ERROR:"):
                logger.error(f"Review failed for #{issue_number}: {review_result}")
                continue

            # 리뷰 결과를 이슈 코멘트로 추가
            comment_body = f"## Architect Review\n\n{review_result}"
            add_comment(repo, issue_number, comment_body)

            # 라벨 전환: needs-review → ready-to-fix
            update_labels(
                repo,
                issue_number,
                add=[labels["ready_to_fix"]],
                remove=[labels["needs_architect_review"]],
            )

            reviewed.append(issue_number)
            logger.info(f"Review completed for issue #{issue_number}")

        except Exception as e:
            logger.error(f"Failed to review issue #{issue_number}: {e}")

    return reviewed
