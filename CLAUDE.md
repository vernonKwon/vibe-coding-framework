# CLAUDE.md

이 프로젝트는 refactor-agent — 범용 개발 워크스페이스 프레임워크이다.

## 프로젝트 구조

- `projects.json` — 디렉토리 매핑 + 그룹 (중앙 설정, 최소)
- `config.yaml` — 파이프라인 전역 설정 (labels, retry)
- `docker-compose.infra.yml` — 공유 인프라
- `scripts/main.py` — CLI 엔트리포인트 (start/stop/status/refactor)
- `scripts/workspace/` — 워크스페이스 프레임워크 (config, service_manager, port_manager, process_tracker)
- `scripts/consultant/` — Phase 1: 코드 스캔
- `scripts/architect/` — Phase 2: 이슈 리뷰
- `scripts/resolver/` — Phase 3: 코드 수정
- `scripts/utils/` — 공통 유틸 (claude, github, logger)

## 설정 3계층

1. `projects.json` — 어떤 프로젝트가 어디에 있는지 (디렉토리 매핑)
2. 각 프로젝트 레포의 `.workspace.yaml` — 서비스/리팩터링 설정 (분산)
3. `config.yaml` — 파이프라인 전역 설정

## 코딩 컨벤션

- Python 3.12+, pipenv 사용
- 한국어 주석/docstring
- 커밋 메시지: 영문 제목 + 한국어 본문
- 프로젝트 특정 이름을 코드에 하드코딩하지 않는다

## 실행

```bash
pipenv run python -m scripts.main status
pipenv run python -m scripts.main start <project>
pipenv run python -m scripts.main refactor --all
```
