"""
Resolver Agent - Test Verifier
리팩터링 전후로 테스트를 실행하여 검증한다.
"""

import subprocess
import shlex
import logging
from dataclasses import dataclass

logger = logging.getLogger("resolver")


@dataclass
class TestResult:
    success: bool
    log: str
    return_code: int


def _run_command(command: str, cwd: str, timeout: int, label: str) -> TestResult:
    """명령어를 실행하고 결과를 반환하는 내부 함수.

    shell=True 대신 shlex.split을 사용하여 커맨드 인젝션을 방지한다.
    단, 파이프(|)나 리다이렉션(>)이 포함된 명령어는 shell=True로 폴백한다.
    """
    logger.info(f"Running {label}: {command} in {cwd}")

    needs_shell = any(c in command for c in ["|", ">", "<", "&&", "||", ";"])

    try:
        if needs_shell:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=timeout,
            )
        else:
            result = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=timeout,
            )

        combined_log = result.stdout + "\n" + result.stderr
        success = result.returncode == 0

        if success:
            logger.info(f"{label} PASSED")
        else:
            logger.warning(f"{label} FAILED (exit code: {result.returncode})")
            logger.debug(f"{label} output: {combined_log[:1000]}")

        return TestResult(
            success=success,
            log=combined_log,
            return_code=result.returncode,
        )

    except subprocess.TimeoutExpired:
        logger.error(f"{label} timed out after {timeout}s")
        return TestResult(
            success=False,
            log=f"{label} timed out after {timeout} seconds",
            return_code=-1,
        )
    except FileNotFoundError as e:
        logger.error(f"{label} command not found: {e}")
        return TestResult(
            success=False,
            log=f"Command not found: {e}",
            return_code=-1,
        )
    except Exception as e:
        logger.error(f"{label} execution error: {e}")
        return TestResult(
            success=False,
            log=str(e),
            return_code=-1,
        )


def run_test(command: str, cwd: str, timeout: int = 300) -> TestResult:
    """테스트 명령어를 실행한다."""
    return _run_command(command, cwd, timeout, "Test")


def run_build(command: str, cwd: str, timeout: int = 300) -> TestResult:
    """빌드 명령어를 실행한다."""
    return _run_command(command, cwd, timeout, "Build")


def run_lint(command: str, cwd: str, timeout: int = 120) -> TestResult:
    """린트 명령어를 실행한다."""
    return _run_command(command, cwd, timeout, "Lint")
