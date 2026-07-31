<p align="center">
  <img src="./public/assets/readme/token-status-bar-icon.png" alt="투명 배경의 토큰 상태 표시줄 앱 아이콘" width="140">
</p>

<h1 align="center">TokenBar</h1>

<p align="center">
  <em>모든 AI 사용자를 위한 토큰 상태. macOS 메뉴 막대에서 바로.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.0.2-111111?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/macOS-14%2B-111111?style=flat-square" alt="macOS 14+">
  <img src="https://img.shields.io/badge/Swift-menu%20bar-111111?style=flat-square" alt="Swift menu bar">
  <img src="https://img.shields.io/badge/Python-3.9%2B-111111?style=flat-square" alt="Python 3.9+">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-111111?style=flat-square" alt="License: MIT"></a>
</p>

<p align="center">
  <sub><a href="./README.md">English</a> &middot; <a href="./README.ko.md">한국어</a></sub>
</p>

<p align="center">
  <a href="https://github.com/bytonylee/token-status-bar/releases/latest/download/TokenStatusBar.dmg"><img src="./public/assets/readme/download-macos.png" alt="Mac OS용 TokenStatusBar.dmg 다운로드" width="270"></a>
</p>

<p align="center">
  <img src="./public/assets/readme/token-status-bar-hero.png" alt="macOS 메뉴 막대에서 여러 AI 제공자의 토큰 쿼터 상태를 보여주는 토큰 상태 표시줄 히어로 배너" width="720">
</p>

---

> *TokenBar는 보유한 모든 AI 코딩 에이전트 계정 — OpenAI Codex, Anthropic
> Claude, xAI / Grok, Google Antigravity, GitHub Copilot, Devin — 을 하나의
> macOS 메뉴 막대에서 관리합니다. 매 폴링마다 각 계정의 정확한 구독 상태
> (유료 / 무료 / 만료 / 곧 갱신)와 쿼터 상태(정상 / 경고 / 소진)를 판정하고,
> 리셋된 윈도우는 그 즉시 롤포워드하며, 활성 계정이 소진되면 사용 가능한
> 계정으로 자격증명을 자동 스왑합니다 — 작업 도중 죽은 토큰에 발목 잡힐
> 일이 없습니다.*

메뉴를 열면 제공자별로 묶인 초록 / 노랑 / 빨강 가용성 점을 볼 수 있고,
계정별 하위 메뉴로 들어가거나 **Poll Now**로 즉시 갱신할 수 있습니다.

> 여러 에이전트 계정을 함께 쓰면서, 어떤 계정에 아직 쿼터가 남았는지, 언제
> 리셋되는지, 어떤 토큰이 곧 만료하는지 한눈에 보고 싶은 사람을 위해
> 만들었습니다 — 대시보드를 따로 열 필요 없이.

**Python 백엔드는 각 제공자를 폴링해 `secrets/status.json`을 기록합니다 —
기본 5분 주기에, 사용량이 많은(hot) 계정은 60초, 로컬 세션 동기화는 약
15초의 적응형 주기입니다. Swift 앱은 이를 30초마다 읽습니다. 온보딩은
`Add New Agent` 메뉴 한 번으로 실행됩니다: 브라우저 OAuth 제공자는 바로
OAuth 플로우를 열고, GitHub Copilot은 디바이스 코드를 보여주기 위해
터미널을 열며, Devin은 앱 안의 프롬프트로 API 키를 입력받습니다. 진짜
API가 있으면 스크래핑하지 않습니다.**

## 기능

- 제공자별로 묶인 드롭다운 메뉴와 계정마다 초록 / 노랑 / 빨강 가용성 점 표시.
- 계정별 하위 메뉴에 요금제, 상태, 토큰 만료, 쿼터 윈도우 표시.
- 지원하는 모든 제공자의 실시간 쿼터 조회(API가 있는 경우 스크래핑하지 않음).
- 백그라운드 폴러(기본 5분 주기, hot 계정 60초, 로컬 동기화 약 15초)와 즉시 실행용 **Poll Now**.
- **Add New Agent** 한 번으로 온보딩 — 브라우저 OAuth는 백그라운드에서,
  Copilot 디바이스 코드 플로우는 터미널에서, Devin은 앱 내 API 키 입력으로 실행.
- 매 폴링마다 정확한 구독/쿼터 상태 판정 — 리셋된 윈도우는 그 즉시 롤포워드되어
  점 표시가 절대 거짓말하지 않음.
- 무개입 계정 자동 스왑 — 활성 Codex 계정의 쿼터가 소진되면 같은 제공자의
  사용 가능한 계정으로 자동 전환(가드레일: 쿨다운, stale 데이터·세션 중 스왑
  방지, 매번 알림).
- 전체 lifecycle 감사 로그 — 모든 리셋, 유료화/만료 전환, 스왑 이력을 기록하고
  조회 가능.

## 지원 제공자

| 제공자             | 키            | 인증 방식        |
|--------------------|---------------|------------------|
| OpenAI Codex       | `codex`       | OAuth (브라우저) |
| Anthropic Claude   | `claude`      | OAuth (브라우저) |
| xAI / Grok         | `xai`         | OAuth (브라우저) |
| Google Antigravity | `antigravity` | OAuth (브라우저) |
| GitHub Copilot     | `copilot`     | OAuth (디바이스 플로우) |
| Devin              | `devin`       | API 키           |

### 현재 상태 표시 범위

| 제공자 | 사용량 / 쿼터 상태 | 구독 기간 상태 |
|--------|--------------------|----------------|
| OpenAI Codex | 요금제, 5시간 / 주간 사용량, 리셋 크레딧 | 현재 인증된 `wham/usage` 응답에서 제공되지 않음 |
| Anthropic Claude | 요금제, 5시간 / 주간 사용량 | 구독 시작일만 제공(`subscription_created_at`) |
| xAI / Grok | 월간 크레딧, 일일 요청/토큰 제한 | billing API에서 시작일과 종료일 제공 |
| Google Antigravity | 티어와 모델 쿼터 | 현재 Code Assist 엔드포인트에서 제공되지 않음 |
| GitHub Copilot | 프리미엄/채팅 쿼터와 월간 리셋 | 리셋/종료일만 제공(`quota_reset_date`) |
| Devin | 일일/주간 쿼터와 크레딧 잔액 | `GetUserStatus`에서 시작일과 종료일 제공 |

## 동작 방식

두 파이프라인은 하나의 어댑터 레지스트리를 함께 사용합니다. **온보딩**은
제공자 어댑터가 선언한 인증 방식과 로그인 훅을 따라 계정을 `pool.db`에
저장합니다. **폴링**도 같은 어댑터를 호출하고, 어댑터는 제공자에 상관없이
같은 형식의 쿼터 윈도우를 반환합니다. 백엔드는 이 윈도우를
`secrets/status.json`에 기록하며, 여러 파일로 나뉜 Swift 앱은 제공자별
분기 없이 이를 메뉴에 표시합니다.

### 흐름도

```mermaid
flowchart TD
    A["Add New Agent<br/>(메뉴 또는 CLI)"] --> B[providers.load 레지스트리]
    B --> C{어댑터 인증 경로?}
    C -->|OAuth 브라우저| D[PKCE 플로우]
    C -->|OAuth 디바이스 플로우| E[디바이스 코드]
    C -->|API 키| F[Devin API 키]
    C -->|로컬 파일| V[제공자 CLI 자격증명]
    C -->|인증 불필요| X[자격증명 없음]
    D --> G[계정 식별 정보 + 요금제]
    E --> G
    F --> G
    V --> G
    X --> G
    G --> H[(pool.db)]

    I[poll-loop 데몬<br/>기본 5분, hot 60초] --> J[poller.run_loop]
    K["Poll Now<br/>(즉시 실행)"] --> L[poller.run_once]
    J --> M[각 계정마다]
    L --> M
    M --> N[제공자 어댑터 조회]
    N --> O{토큰 만료 임박?}
    O -->|예| P[어댑터 갱신 훅]
    P --> H
    O -->|아니오 또는 토큰 불필요| Q[어댑터 폴링]
    Q --> R[선언형 쿼터 윈도우]
    R --> S[(pool.db 스냅샷)]
    S --> T[status.json]
    T --> U["TokenStatusBar.app<br/>30초마다 읽기"]
    U --> W[메뉴 막대 드롭다운 + 점]
```

### 온보딩 — 계정 연결

```mermaid
flowchart TD
    A["Add New Agent (메뉴) /<br/>pool.py add &lt;provider&gt; (CLI)"] --> B[providers.load]
    B --> C[어댑터 AUTH + 로그인 훅]
    C -->|OAuth 브라우저| D1["어댑터 브라우저 플로우<br/>PKCE 콜백 → 사용자 승인"]
    C -->|디바이스 플로우| D2["어댑터 로그인 훅<br/>디바이스 코드 → 토큰 폴링"]
    C -->|API 키| D3["보안 입력창<br/>어댑터가 키 검증"]
    C -->|로컬 파일| D4["어댑터가 제공자 CLI 자격증명 읽기"]
    C -->|인증 불필요| D5[별도 자격증명 설정 없음]
    D1 --> E["access + refresh token"]
    D2 --> E
    D3 --> E
    D4 --> E
    D5 --> E
    E --> F["계정 식별 정보 + 요금제"]
    F --> G["store.upsert_account<br/>필요한 경우에만 토큰 저장"]
    G --> H[(pool.db)]
```

### 폴링 — 쿼터 정보 가져오기

```mermaid
flowchart TD
    A["poll-loop 데몬 (기본 5분, hot 60초)"] --> B[pool.py poll-loop → poller.run_loop]
    C["Poll Now (즉시 실행)"] --> D[pool.py poll → poller.run_once]
    B --> E[store.list_accounts 각 계정마다]
    D --> E
    E --> F[providers.get account.provider]
    F --> G{어댑터에 토큰이 필요한가?}
    G -->|예| H["토큰 읽기; 필요하면 adapter REFRESH 실행"]
    G -->|아니오| J[어댑터가 로컬 소스 읽기]
    H --> K[어댑터 poll]
    J --> K
    K --> L["util.snapshot(windows[])"]
    L --> I[(pool.db)]
    I --> M["status.cmd_export → status.json"]
    M --> N["TokenStatusBar.app 30초마다 읽기 → 드롭다운 UI + 점"]
```

## 요구 사항

- macOS 14 (Sonoma) 이상 — 앱의 `LSMinimumSystemVersion`은 14.0입니다.
- 앱 빌드를 위한 Xcode 커맨드라인 도구(`swiftc`).
- 폴링 백엔드용 Python 3.9 이상.

## 구성

| 경로                 | 용도 |
|----------------------|------|
| `app/*.swift`        | `swiftc`로 직접 컴파일하는 다중 파일 Swift 메뉴 막대 UI. |
| `app/Tests/`         | Swift 동작 고정용 fixture와 계정 하위 메뉴 golden 테스트. |
| `build.sh`           | 앱을 컴파일하고 번들링하며, `--dmg`로 배포 이미지를 생성. |
| `test.sh`            | Swift 파일 크기 제한을 검사하고 테스트 하네스를 컴파일·실행. |
| `backend/providers/*.py` | 자동 탐색 레지스트리. 제공자별 어댑터 하나가 인증, 폴링, 기능, 윈도우 변환을 담당. |
| `backend/pool.py`    | CLI: 온보딩, 폴링, 상태 내보내기. |
| `backend/poller.py`  | 레지스트리 기반 폴링 주기와 스냅샷 처리. |
| `backend/status.py`  | 앱이 읽을 `status.json` 생성. |
| `backend/store.py`   | SQLite 저장소 (`pool.db`). |
| `backend/oauth.py`   | 어댑터가 선언한 로그인·갱신 훅을 실행하는 공통 OAuth 처리 계층. |
| `secrets/status.json` | 메뉴 막대 앱이 사용하는 스냅샷 (git 무시). |
| `secrets/pool.db`    | SQLite 계정/쿼터 저장소 (git 무시). |

데이터는 기본적으로 `~/solo/token-status-bar/secrets/` 아래에 저장됩니다(`pool.db`,
`status.json`). `AGENT_POOL_DB`, `AGENT_POOL_STATUS_JSON` 환경 변수로 경로를
바꿀 수 있습니다.

## 앱 빌드 및 실행

```bash
./test.sh
./build.sh
./build.sh --dmg
open /Applications/TokenStatusBar.app
```

앱은 30초마다 `secrets/status.json`을 읽고 메뉴 막대에 차트 아이콘을 표시합니다.

## CLI 사용법

```bash
python3 backend/pool.py add <provider> [label]   # OAuth 온보딩 (codex|claude|xai|antigravity|copilot)
python3 backend/pool.py add-devin <api_key> [label]
python3 backend/pool.py list                     # 모든 계정 목록
python3 backend/pool.py remove <account_id>
python3 backend/pool.py status                   # 계정 + 최신 한도 상태
python3 backend/pool.py poll                     # 1회 폴링 (모든 API 호출)
python3 backend/pool.py poll-loop                # 폴러 데몬 실행 (기본 5분 주기)
python3 backend/pool.py refresh <account_id>     # 토큰 1개 갱신
python3 backend/pool.py refresh-all              # 만료 예정 토큰 전체 갱신
python3 backend/pool.py export-status            # status.json 작성
```

## 백그라운드 폴러 (launchd, 수동 설정)

이 저장소에는 launchd plist가 포함되어 있지 않습니다 — 백그라운드 폴러는
직접 설정해야 합니다. `secrets/status.json`을 최신 상태로 유지하려면
`~/Library/LaunchAgents/com.tonye.agentpool-poller.plist`를 직접 만들어
`ProgramArguments`에 `python3 <repo>/backend/pool.py poll-loop`를 지정하고
`RunAtLoad`/`KeepAlive`를 true로 설정한 뒤 로드하세요:

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.tonye.agentpool-poller.plist
```

`poller.py`를 수정한 뒤에는 새 코드를 반영하도록 데몬을 다시 시작하세요:

```bash
launchctl kickstart -k "gui/$(id -u)/com.tonye.agentpool-poller"
```

launchd 대신 아무 터미널 세션에서 `python3 backend/pool.py poll-loop`를
실행하거나, 메뉴의 **Poll Now**만 사용해도 됩니다.

## Poll Now vs Refresh Display

- **Poll Now** — 모든 제공자의 API를 직접 호출해 `pool.db`와 `status.json`을
  갱신한 뒤 다시 불러옵니다. 느리지만 최신 수치를 가져옵니다.
- **Refresh Display** — 디스크에 저장된 `status.json`만 다시 읽습니다.
  즉시 반영되며 네트워크를 사용하지 않습니다.

## 라이선스

[MIT](./LICENSE)
