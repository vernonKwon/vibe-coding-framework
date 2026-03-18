# Refactor Agent - System Architecture

## Overview

**범용 개발 워크스페이스 프레임워크** — 프로젝트 레포에 `.workspace.yaml`만 추가하면 서비스 관리와 리팩터링 파이프라인을 사용할 수 있다.

## 설정 3계층

```
projects.json              ← 디렉토리 매핑 + 그룹 정의 (중앙, 최소)
각 레포/.workspace.yaml    ← 서비스/리팩터링 설정 (분산, 프로젝트 자율)
config.yaml                ← 파이프라인 전역 설정 (labels, retry)
docker-compose.infra.yml   ← 공유 인프라 서비스 (RabbitMQ 등)
```

### 설정 로딩 흐름

```
config.py
  ├─ projects.json 로드 → { "<name>": "<directory>" }
  ├─ workspace_root 해소 → ../<directory>
  ├─ .workspace.yaml 로드 → repo, service, refactor 설정
  ├─ config.yaml 로드 → global labels, retry 설정
  └─ 파이프라인 호환 dict 생성 → scanner/reviewer/executor 무변경 동작
```

## CLI 구조

```bash
# 서비스 관리
python -m scripts.main start <project>
python -m scripts.main start --group <group>
python -m scripts.main stop <project>
python -m scripts.main stop --group <group>
python -m scripts.main status

# 리팩터링 파이프라인
python -m scripts.main refactor --all
python -m scripts.main refactor --consultant --project <project>

# 하위 호환
python -m scripts.main --all           # → refactor --all
```

## Agent 구조

```
┌─────────────────────────────────────────────────────────────────┐
│                        Strategy Hub                             │
│                     (GitHub Issues)                              │
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │tech-debt │───>│needs-    │───>│ready-to- │───>│completed │  │
│  │          │    │review    │    │fix       │    │          │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       ▲               ▲               ▲               ▲        │
│       │               │               │               │        │
└───────┼───────────────┼───────────────┼───────────────┼────────┘
        │               │               │               │
   ┌────┴────┐    ┌─────┴─────┐   ┌────┴─────┐   ┌────┴────┐
   │Consultant│    │ Architect │   │ Resolver  │   │  Human  │
   │  Agent   │    │   Agent   │   │  Agent    │   │ (You)   │
   └─────────┘    └───────────┘   └──────────┘   └─────────┘
```

## 서비스 관리 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                Service Manager                       │
│  .workspace.yaml 읽기 → 인프라 시작 → 서비스 시작     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────────┐  ┌──────────┐  ┌───────────────┐ │
│  │docker-compose│  │  Port    │  │   Process     │ │
│  │  .infra.yml  │  │ Manager  │  │   Tracker     │ │
│  └──────────────┘  └──────────┘  └───────────────┘ │
└─────────────────────────────────────────────────────┘
```

### start --group 흐름
1. `projects.json`에서 그룹 해소 → 프로젝트 목록
2. 각 프로젝트의 `.workspace.yaml`에서 `dependencies` 수집
3. `docker compose -f docker-compose.infra.yml up -d <dep>` 실행
4. 포트 충돌 검사 및 자동 리매핑
5. 서비스 순서대로 시작
6. Health check 폴링 (최대 60초)
7. `.workspace/running.json`에 기록

### 포트 충돌 해결
- 동일 포트 사용 프로젝트 동시 시작 시 자동 리매핑
- `.workspace.yaml`의 `port_override_env` 필드로 프레임워크별 환경변수 지정

## 라벨 상태 머신

```
[생성] ─── tech-debt + needs-review ──── Consultant이 생성
                    │
                    ▼ (Architect 리뷰 완료)
          tech-debt + ready-to-fix ────── Resolver 대기
                    │
                    ▼ (Resolver 작업 시작)
          tech-debt + in-progress ─────── 작업 중
                    │
             ┌──────┴──────┐
             ▼              ▼
       completed       fix-failed ─────── 수동 확인 필요
```

## 설정 호환 레이어

`scripts/workspace/config.py`가 `projects.json` + 각 프로젝트의 `.workspace.yaml`을 읽어서
기존 파이프라인이 기대하는 dict로 변환. scanner.py, reviewer.py, executor.py는 **무변경**.

```python
config["projects"]["<name>"] = {
    "enabled": True,
    "path": "/workspace/<directory>",
    "repo": "owner/repo-name",
    "commands": { "build": "...", "test": "..." },
    ...
}
```

## 모듈 구조

```
refactor-agent/
├── projects.json                    ← 디렉토리 매핑 + 그룹
├── config.yaml                      ← 전역 설정 (labels, retry)
├── docker-compose.infra.yml         ← 공유 인프라
├── scripts/
│   ├── main.py                      ← CLI 엔트리포인트
│   ├── workspace/
│   │   ├── config.py                ← projects.json + .workspace.yaml 병합
│   │   ├── service_manager.py       ← 서비스 시작/종료/상태
│   │   ├── port_manager.py          ← 포트 충돌 감지
│   │   └── process_tracker.py       ← 프로세스 추적
│   ├── consultant/scanner.py
│   ├── architect/reviewer.py
│   ├── resolver/{executor,verifier}.py
│   └── utils/{logger,claude,github}.py
├── playbooks/                       ← 프로젝트별 리팩터링 규칙
├── docker-compose.yml               ← 에이전트 컨테이너
└── entrypoint.sh                    ← projects.json 기반 자동 초기화

각 프로젝트 레포/
└── .workspace.yaml                  ← 서비스/리팩터링 설정
```

## 안전 장치

1. **머지는 항상 수동** - 에이전트는 Draft PR까지만 생성
2. **브랜치 보호** - main/dev 직접 푸시 불가
3. **수정 범위 제한** - 이슈에 명시된 파일만 수정 가능
4. **테스트 필수** - Pre-test 실패 시 작업 중단
5. **재시도 제한** - 최대 3회, 이후 사람에게 에스컬레이션
6. **시크릿 보호** - .env, 인증 파일 수정 절대 금지
7. **git worktree 격리** - 이슈 간 변경사항 간섭 방지
8. **파일 잠금** - 동시 실행 방지
