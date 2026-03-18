# Refactor Agent

기술 부채를 자동으로 식별, 분석, 해결하는 3-Agent 파이프라인 + 개발 서비스 관리 프레임워크.

## 요구 사항

- Python 3.12+
- pipenv
- Docker & Docker Compose
- GitHub CLI (`gh`)
- Claude Code CLI (`@anthropic-ai/claude-code`)

## 설치

```bash
# 1. 환경변수 설정
cp .env.example .env
# .env에 GITHUB_TOKEN 입력
# Claude Code는 OAuth(Max 구독) 또는 ANTHROPIC_API_KEY 중 선택

# 2. Python 의존성
pipenv install
```

## 초기 셋업 순서

모든 설정 파일은 Claude에게 프롬프트를 주면 자동 생성할 수 있다. 권장 순서:

| 순서 | 파일 | 위치 | 설명 |
|------|------|------|------|
| 1 | `projects.json` | refactor-agent/ | 워크스페이스 디렉토리 매핑 + 그룹 |
| 2 | `docker-compose.infra.yml` | refactor-agent/ | 공유 인프라 서비스 |
| 3 | `.workspace.yaml` | 각 프로젝트 레포/ | 서비스 시작/종료 + 리팩터링 설정 |
| 4 | `PLAYBOOK.md` | 각 프로젝트 레포/ | 리팩터링 규칙 (선택) |

각 파일의 자동 생성 프롬프트는 아래 해당 섹션에 있다.

## projects.json 생성

Claude에게 아래 프롬프트를 주면 현재 워크스페이스를 분석해서 `projects.json`을 자동 생성한다:

```
이 워크스페이스의 프로젝트 구조를 분석해서 refactor-agent용 projects.json을 작성해줘.

refactor-agent는 이 디렉토리의 형제 디렉토리에 있어.
projects.json은 refactor-agent가 관리할 프로젝트의 디렉토리 매핑과 그룹을 정의하는 파일이야.

아래 규칙을 따라 작성해:

1. 형제 디렉토리(또는 하위)에 있는 git 레포지토리를 찾아서 projects에 등록해
2. 각 프로젝트의 별칭은 짧고 직관적인 이름으로 (예: "api-server", "web-client")
3. 값은 workspace_root 기준 상대 경로 (예: "my-api-repo", "services/auth")
4. 연관된 프로젝트끼리 groups로 묶어 (예: backend+frontend = fullstack)
5. workspace_root는 ".." (refactor-agent의 부모 디렉토리)

출력 형식 (JSON):
{
  "workspace_root": "..",
  "projects": {
    "<별칭>": "<디렉토리 경로>",
    ...
  },
  "groups": {
    "<그룹명>": ["<별칭>", ...],
    ...
  }
}

주의:
- refactor-agent 자체는 projects에 포함하지 마
- node_modules, .git 같은 비프로젝트 디렉토리는 제외해
- 하나의 프로젝트가 여러 그룹에 속할 수 있어
```

## 설정 구조

설정은 3계층으로 분리된다:

```
projects.json              ← 디렉토리 매핑 + 그룹
각 프로젝트/.workspace.yaml ← 서비스/리팩터링 설정 (프로젝트 자율)
config.yaml                ← 파이프라인 전역 설정
docker-compose.infra.yml   ← 공유 인프라
```

### 1. projects.json — 디렉토리 매핑 + 그룹

```json
{
  "workspace_root": "..",
  "projects": {
    "my-backend": "my-backend-repo",
    "my-frontend": "my-frontend-repo"
  },
  "groups": {
    "fullstack": ["my-backend", "my-frontend"]
  }
}
```

- `workspace_root` — projects.json 위치 기준 상대 경로 (형제 디렉토리는 `".."`)
- `projects` — `"별칭": "디렉토리명"` 매핑
- `groups` — 여러 프로젝트를 묶어서 한번에 시작/종료

프로젝트를 추가하려면 한 줄만 추가하면 된다.

### 2. .workspace.yaml — 각 프로젝트 레포에 배치

각 프로젝트의 루트에 `.workspace.yaml`을 생성한다. Claude에게 아래 프롬프트를 주면 자동 생성 가능:

```
이 프로젝트를 분석해서 .workspace.yaml을 작성해줘.

.workspace.yaml은 refactor-agent가 이 프로젝트의 서비스를 관리하고 리팩터링을 수행할 때
참조하는 설정 파일이야. 프로젝트 루트에 배치해.

아래 파일들을 분석해서 각 필드를 채워줘:
- package.json / build.gradle / pom.xml → 빌드/테스트/린트 명령어
- docker-compose*.yml → 서비스 시작/종료 명령어
- .git/config 또는 git remote → GitHub repo 주소
- git branch → 기본 브랜치 (main/dev/master)
- 소스 디렉토리 구조 → scan include/exclude 패턴

출력 형식 (YAML):
repo: "owner/repo-name"           # GitHub owner/repo
base_branch: "dev"                 # PR 대상 브랜치
language: "typescript"             # 주 언어
framework: "nestjs"                # 프레임워크

service:
  start: "<서비스 시작 명령어>"      # docker-compose up 또는 npm run dev 등
  stop: "<서비스 종료 명령어>"       # 없으면 null (프로세스 kill로 종료)
  port: <포트번호>                  # 서비스가 리스닝하는 포트
  health_check: "<경로>"           # 상대경로 (예: "/health") 또는 전체 URL
  port_override_env: "<환경변수>"   # 포트 충돌 시 리매핑용 (예: "PORT", "VITE_PORT")
  dependencies: ["<인프라명>"]      # docker-compose.infra.yml의 서비스 이름

refactor:
  enabled: true
  commands:
    build: "<빌드 명령어>"
    test: "<테스트 명령어>"          # 필수
    lint: "<린트 명령어>"
    type_check: "<타입체크>"        # 없으면 null
  scan:
    include: ["<소스 glob 패턴>"]   # 스캔 대상
    exclude: ["<제외 glob 패턴>"]   # 테스트, 빌드산출물, node_modules 등

규칙:
- 실제로 존재하는 스크립트/명령어만 적어. 추측하지 마.
- docker-compose 파일이 있으면 service.start에 docker-compose 명령어 사용
- 없으면 package.json scripts나 gradle task를 직접 사용
- service 섹션과 refactor 섹션 중 해당 없는 건 생략 가능
```

`.workspace.yaml`이 없는 프로젝트는 서비스 관리/리팩터링 대상에서 제외된다.

**플레이북 자동 탐색**: 각 프로젝트 레포에서 자동으로 찾는다:
- `{프로젝트}/CLAUDE.md` — 코딩 컨벤션
- `{프로젝트}/PLAYBOOK.md` — 리팩터링 규칙

### 3. docker-compose.infra.yml — 공유 인프라

프로젝트들이 공유하는 인프라(DB, 메시지 브로커 등)를 정의한다. Claude에게 아래 프롬프트를 주면 자동 생성 가능:

```
워크스페이스의 프로젝트들을 분석해서 docker-compose.infra.yml을 작성해줘.

각 프로젝트의 docker-compose*.yml, .env, 설정 파일 등을 확인해서
공통으로 의존하는 외부 서비스(DB, Redis, RabbitMQ 등)를 찾아줘.

출력 형식:
services:
  <서비스명>:
    image: <이미지:태그>
    ports:
      - "<호스트포트>:<컨테이너포트>"

규칙:
- 각 프로젝트의 docker-compose에 이미 정의된 외부 서비스를 추출
- 여러 프로젝트가 같은 서비스를 사용하면 하나로 통합
- 프로젝트 자체의 애플리케이션 서비스는 포함하지 마 (인프라만)
- 서비스명은 .workspace.yaml의 dependencies에서 참조할 이름이야
```

`.workspace.yaml`의 `service.dependencies`에 서비스 이름을 적으면 프로젝트 시작 시 자동으로 함께 시작된다.

### 경로 규칙

```
workspace/                 ← workspace_root (..)
├── refactor-agent/        ← projects.json 위치
├── my-backend-repo/       ← .workspace.yaml 포함
└── my-frontend-repo/      ← .workspace.yaml 포함
```

## 서비스 관리

### 시작

```bash
# 단일 프로젝트
pipenv run python -m scripts.main start <project>

# 그룹 (인프라 의존성 자동 시작)
pipenv run python -m scripts.main start --group <group>
```

동작 순서:
1. `.workspace.yaml`에서 `dependencies` 확인 → `docker-compose.infra.yml`로 인프라 시작
2. 포트 충돌 검사 (충돌 시 `port_override_env`로 자동 리매핑)
3. 서비스 시작 (docker-compose 또는 subprocess)
4. Health check 폴링 (최대 60초)
5. 상태 테이블 출력

### 종료

```bash
pipenv run python -m scripts.main stop <project>
pipenv run python -m scripts.main stop --group <group>
```

### 상태 확인

```bash
pipenv run python -m scripts.main status
```

```
Name                      Port     Status       PID        Started
---------------------------------------------------------------------------
redis                     6379     running      -          2026-03-18T10:00:00
my-backend                8080     running      -          2026-03-18T10:00:05
my-frontend               3000     stopped      -          -
```

## 리팩터링 파이프라인

```bash
# 전체 파이프라인
pipenv run python -m scripts.main refactor --all

# 개별 에이전트
pipenv run python -m scripts.main refactor --consultant
pipenv run python -m scripts.main refactor --architect
pipenv run python -m scripts.main refactor --resolver

# 특정 프로젝트
pipenv run python -m scripts.main refactor --consultant --project <project>

# 하위 호환
pipenv run python -m scripts.main --all
```

1. **Consultant** — 코드 스캔 후 GitHub Issue 생성 (`tech-debt` + `needs-review`)
2. **Architect** — 이슈 리뷰, 수정 계획 작성 → `ready-to-fix`
3. **Resolver** — 코드 수정, 테스트, Draft PR 생성

## PLAYBOOK.md 작성

각 프로젝트 레포에 `PLAYBOOK.md`를 생성하면 Consultant가 프로젝트에 맞는 기술 부채를 식별한다.

Claude에게 아래 프롬프트를 주면 자동 생성 가능:

```
이 프로젝트의 코드베이스를 분석해서 PLAYBOOK.md를 작성해줘.

PLAYBOOK.md는 자동화된 리팩터링 에이전트가 참조하는 파일이야.
에이전트는 이 파일을 읽고 기술 부채를 식별 → GitHub Issue 생성 → 코드 수정 → Draft PR을 만든다.

다음 섹션을 포함해줘:
1. 프로젝트 컨텍스트 — 기술 스택, 아키텍처 패턴, 도메인 요약
2. 식별 규칙 — 우선순위별(Critical/High/Medium/Low), 코드 패턴 예시 포함
3. 금지 사항 — 에이전트가 절대 수정하면 안 되는 것
4. 테스트 방법 — 수정 후 검증 명령어

CLAUDE.md에 이미 있는 컨벤션은 반복하지 말고, 이 프로젝트 고유의 규칙에 집중해.
```

상세 템플릿은 `playbooks/GUIDE.md` 참조.

## Docker 실행

```bash
# Cron 모드 (매일 22:00 전체, 06:00 Architect)
docker compose up -d

# 수동 실행
docker compose run --rm refactor-agent pipenv run python -m scripts.main refactor --all
```

## 로그

```bash
# 로그 디렉토리 변경 (기본: /var/log/refactor-agent)
export REFACTOR_AGENT_LOG_DIR=./logs
```

## 프로젝트 구조

```
refactor-agent/
├── projects.json              # 디렉토리 매핑 + 그룹
├── projects.example.json      # projects.json 예시
├── config.yaml                # 전역 설정 (labels, retry)
├── docker-compose.infra.yml   # 공유 인프라
├── scripts/
│   ├── main.py                # CLI 엔트리포인트
│   ├── workspace/             # 워크스페이스 프레임워크
│   │   ├── config.py          #   설정 로더 (projects.json + .workspace.yaml 병합)
│   │   ├── service_manager.py #   서비스 시작/종료/상태
│   │   ├── port_manager.py    #   포트 충돌 감지
│   │   └── process_tracker.py #   프로세스 추적
│   ├── consultant/            # Phase 1: 코드 스캔
│   ├── architect/             # Phase 2: 이슈 리뷰
│   ├── resolver/              # Phase 3: 코드 수정
│   └── utils/                 # 공통 유틸
├── playbooks/GUIDE.md         # PLAYBOOK.md 작성 가이드 + 템플릿
├── docker-compose.yml         # 에이전트 컨테이너
├── Dockerfile
└── entrypoint.sh
```
