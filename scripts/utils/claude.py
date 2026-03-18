"""
Claude Code CLI wrapper.
에이전트가 Claude Code를 호출하여 코드 분석/수정을 수행한다.
"""

import subprocess
import logging

logger = logging.getLogger(__name__)


def run_claude_code(
    prompt: str,
    cwd: str,
    allowed_tools: list[str] | None = None,
    max_turns: int = 50,
    timeout: int = 600,
) -> dict:
    """
    Claude Code CLI를 실행한다.

    Args:
        prompt: Claude Code에 전달할 프롬프트
        cwd: 작업 디렉토리 (프로젝트 루트)
        allowed_tools: 허용할 도구 목록 (None이면 기본값)
        max_turns: 최대 대화 턴 수
        timeout: 타임아웃 (초)

    Returns:
        dict with keys: success, stdout, stderr
    """
    cmd = [
        "claude",
        "--print",
        "--output-format", "text",
        "--max-turns", str(max_turns),
    ]

    if allowed_tools:
        for tool in allowed_tools:
            cmd += ["--allowedTools", tool]

    logger.info(f"Running Claude Code in {cwd}")
    logger.debug(f"Prompt length: {len(prompt)} chars")

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    except subprocess.TimeoutExpired:
        logger.error(f"Claude Code timed out after {timeout}s")
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Timed out after {timeout} seconds",
        }
    except FileNotFoundError:
        logger.error("Claude Code CLI not found. Is it installed?")
        return {
            "success": False,
            "stdout": "",
            "stderr": "claude CLI not found in PATH",
        }


def analyze_code(project_path: str, playbook_content: str, scan_patterns: list[str]) -> str:
    """
    Consultant Agent용: 코드베이스를 분석하여 기술 부채를 식별한다.

    Returns:
        Claude Code의 분석 결과 (텍스트)
    """
    prompt = f"""당신은 기술 부채 분석 전문가입니다.
아래 Playbook 규칙에 따라 이 프로젝트의 기술 부채를 식별하세요.

## Playbook
{playbook_content}

## 스캔 대상 패턴
{', '.join(scan_patterns)}

## 출력 형식
각 부채 항목을 다음 JSON 형식으로 출력하세요:
```json
[
  {{
    "title": "간결한 제목",
    "priority": "P1|P2|P3|P4",
    "category": "카테고리",
    "description": "현상 설명",
    "files": ["관련 파일 경로"],
    "violated_rules": ["위반한 playbook 규칙"]
  }}
]
```

코드를 읽고 분석만 하세요. 코드를 수정하지 마세요."""

    result = run_claude_code(
        prompt=prompt,
        cwd=project_path,
        allowed_tools=["Read", "Glob", "Grep"],
        max_turns=30,
    )

    return result["stdout"] if result["success"] else f"ERROR: {result['stderr']}"


def review_issue(project_path: str, issue_body: str, playbook_content: str) -> str:
    """
    Architect Agent용: 이슈를 분석하고 보충 내용을 작성한다.

    Returns:
        Architect의 리뷰 결과 (마크다운)
    """
    prompt = f"""당신은 소프트웨어 아키텍트입니다.
아래 기술 부채 이슈를 분석하고, 누락된 내용을 보충하세요.

## 이슈 내용
{issue_body}

## Playbook
{playbook_content}

## 수행할 작업
1. 이슈에서 언급된 파일과 관련 파일을 모두 읽으세요.
2. 누락된 분석 내용을 보충하세요.
3. 영향 범위 (수정 대상 파일, 영향받는 테스트, 의존성)를 파악하세요.
4. 구체적인 수정 계획을 작성하세요.
5. 선행 작업이 있다면 명시하세요.

## 출력 형식
마크다운으로 작성하되, 다음 섹션을 포함하세요:
- 보충 분석
- 영향 범위
- 수정 계획 (단계별)
- 선행 작업
- 검증 방법 (실행할 테스트 명령어)
- 주의사항

코드를 읽고 분석만 하세요. 코드를 수정하지 마세요."""

    result = run_claude_code(
        prompt=prompt,
        cwd=project_path,
        allowed_tools=["Read", "Glob", "Grep"],
        max_turns=30,
    )

    return result["stdout"] if result["success"] else f"ERROR: {result['stderr']}"


def resolve_issue(project_path: str, issue_body: str, architect_review: str, playbook_content: str) -> str:
    """
    Resolver Agent용: 이슈를 실제로 코드 수정하여 해결한다.

    Returns:
        수정 결과 요약 (텍스트)
    """
    prompt = f"""당신은 리팩터링 전문 개발자입니다.
아래 이슈와 Architect의 수정 계획에 따라 코드를 수정하세요.

## 이슈 내용
{issue_body}

## Architect 수정 계획
{architect_review}

## Playbook (반드시 준수)
{playbook_content}

## 규칙
1. 수정 계획에 명시된 파일만 수정하세요.
2. 기존 코딩 컨벤션을 절대적으로 준수하세요.
3. 기능 동작을 변경하지 마세요.
4. 수정 후 어떤 파일을 어떻게 변경했는지 요약하세요.

## 출력
수정 완료 후, 변경 사항을 요약해주세요."""

    result = run_claude_code(
        prompt=prompt,
        cwd=project_path,
        allowed_tools=["Read", "Glob", "Grep", "Edit", "Write", "Bash"],
        max_turns=50,
        timeout=900,
    )

    return result["stdout"] if result["success"] else f"ERROR: {result['stderr']}"
