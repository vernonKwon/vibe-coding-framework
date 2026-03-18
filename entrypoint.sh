#!/bin/bash
set -e

# =============================================================================
# 범용 초기화 스크립트
# projects.json을 읽어서 프로젝트별 의존성을 자동으로 설정한다.
# =============================================================================

# 환경변수를 /etc/environment로 내보내기 (cron 환경용)
printenv | grep -E '^(GITHUB_TOKEN|ANTHROPIC_API_KEY|GIT_|PATH|HOME|JAVA_HOME|NODE_|REFACTOR_)' \
    >> /etc/environment

# Git 설정
git config --global user.name "${GIT_AUTHOR_NAME:-refactor-agent}"
git config --global user.email "${GIT_AUTHOR_EMAIL:-refactor-agent@local}"
git config --global --add safe.directory '*'

# gh CLI 인증 확인
if [ -n "$GITHUB_TOKEN" ]; then
    echo "$GITHUB_TOKEN" | gh auth login --with-token 2>/dev/null || true
    echo "GitHub CLI authenticated."
else
    echo "WARNING: GITHUB_TOKEN not set. gh commands will fail."
fi

# ---------------------------------------------------------------------------
# projects.json 기반 자동 의존성 설치
# ---------------------------------------------------------------------------
PROJECTS_FILE="${PROJECTS_FILE:-/app/projects.json}"
WORKSPACE_ROOT="/workspace"

if [ -f "$PROJECTS_FILE" ]; then
    echo "Initializing projects from $PROJECTS_FILE..."

    # jq가 없으면 python으로 파싱
    if command -v jq &>/dev/null; then
        PARSER="jq"
    else
        PARSER="python3"
    fi

    # 각 프로젝트 디렉토리를 순회하며 의존성 설치
    if [ "$PARSER" = "jq" ]; then
        DIRS=$(jq -r '.projects | to_entries[] | .value.directory' "$PROJECTS_FILE")
    else
        DIRS=$(python3 -c "
import json
with open('$PROJECTS_FILE') as f:
    data = json.load(f)
for p in data.get('projects', {}).values():
    print(p['directory'])
")
    fi

    for DIR in $DIRS; do
        PROJECT_PATH="${WORKSPACE_ROOT}/${DIR}"

        if [ ! -d "$PROJECT_PATH" ]; then
            echo "  SKIP: $DIR (directory not found)"
            continue
        fi

        # Gradle 프로젝트
        if [ -f "${PROJECT_PATH}/gradlew" ]; then
            chmod +x "${PROJECT_PATH}/gradlew"
            echo "  $DIR: gradlew ready"
        fi

        # Node.js 프로젝트 (yarn)
        if [ -f "${PROJECT_PATH}/yarn.lock" ]; then
            if [ ! -d "${PROJECT_PATH}/node_modules" ]; then
                echo "  $DIR: installing yarn dependencies..."
                (cd "$PROJECT_PATH" && yarn install --frozen-lockfile 2>/dev/null) || true
            fi
            echo "  $DIR: yarn dependencies ready"
        # Node.js 프로젝트 (npm)
        elif [ -f "${PROJECT_PATH}/package-lock.json" ]; then
            if [ ! -d "${PROJECT_PATH}/node_modules" ]; then
                echo "  $DIR: installing npm dependencies..."
                (cd "$PROJECT_PATH" && npm ci 2>/dev/null) || true
            fi
            echo "  $DIR: npm dependencies ready"
        fi
    done
else
    echo "WARNING: $PROJECTS_FILE not found. Skipping project init."
fi

echo "Entrypoint complete. Starting: $@"
exec "$@"
