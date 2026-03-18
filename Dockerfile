# =============================================================================
# Refactor Agent - Multi-runtime Docker Image
# Node.js (frontend builds) + Java (Kotlin/Gradle builds) + Python (orchestrator)
# =============================================================================

FROM eclipse-temurin:17-jdk-jammy AS base

# Node.js 22 설치
RUN apt-get update && apt-get install -y curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# yarn 설치
RUN npm install -g yarn

# 시스템 패키지
RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    python3-venv \
    cron \
    && rm -rf /var/lib/apt/lists/*

# GitHub CLI 설치
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI 설치
RUN npm install -g @anthropic-ai/claude-code

# pipenv 설치
RUN pip3 install --break-system-packages pipenv

# Python 의존성
WORKDIR /app
COPY Pipfile Pipfile.lock ./
RUN PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy

# 에이전트 코드 복사
COPY . .

# 로그 디렉토리
RUN mkdir -p /var/log/refactor-agent

# Cron 설정 (환경변수 포함)
COPY crontab /etc/cron.d/refactor-agent
RUN chmod 0644 /etc/cron.d/refactor-agent \
    && crontab /etc/cron.d/refactor-agent

# 초기화 스크립트
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PATH="/app/.venv/bin:/usr/local/bin:$PATH"

ENTRYPOINT ["/app/entrypoint.sh"]
# 기본: cron 데몬 실행
# 수동: docker run ... python3 -m scripts.main refactor --all
CMD ["cron", "-f"]
