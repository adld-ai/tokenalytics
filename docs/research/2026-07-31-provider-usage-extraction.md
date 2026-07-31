# 17개 AI 코딩 구독의 사용량 추출 경로

조사일: 2026-07-31
방법: 1차 자료만 — 벤더 공식 API 레퍼런스, 오픈소스 CLI 소스, 이 머신에 설치된 실제
바이너리·설정·세션 파일. 2차 자료(블로그·포럼)는 그렇게 표시했고, 추론은
`INFERRED — 미검증`으로 남겼다.
설계 문서: `docs/superpowers/specs/2026-07-31-provider-adapter-sync-design.md`

---

## 0. 먼저 알아야 할 것

리서치를 관통하는 결론 세 가지다.

**첫째, 응답 헤더로 구독 잔량을 읽을 수 있는 벤더는 Anthropic 하나뿐이다.**
나머지 벤더의 `x-ratelimit-*`는 전부 API 키/조직 단위 처리율 제한이지 플랜 잔량이
아니다. Gemini·Vertex·xAI·Moonshot·Z.ai·DashScope·GitHub Models는 완성 응답 헤더를
아예 문서화하지 않는다. 헤더 기반 범용 수집기를 만들려던 계획이 있다면 그건 성립하지
않는다.

**둘째, 가장 값싸고 정확한 소스는 대체로 로컬 파일이다.** Codex rollout 파일에는
ChatGPT 구독 창의 사용률·리셋 시각·크레딧 잔액이 그대로 들어 있어 네트워크 호출 0회로
읽힌다. 이 리포가 `local_sync.py`에서 이미 그렇게 하고 있고, 같은 패턴이 다른 CLI에도
적용된다.

**셋째, 벤더가 잔량 API를 아예 제공하지 않는 경우가 생각보다 많다.** 그럴 때 남는 건
(a) 콘솔 웹 UI 스크래핑 — 비공식이고 깨지기 쉬움, (b) 실패 응답의 에러 코드에 실려오는
`next_flush_time`을 사후적으로 읽는 것, (c) 로컬에서 토큰을 세어 벤더의 공개 계수로
직접 계산하는 것뿐이다. 셋 다 근사치다.

---

## 1. 횡단 메커니즘 — 헤더 / 프록시 / 게이트웨이

### 1.1 Anthropic unified 헤더 (구독 잔량이 실제로 나오는 유일한 헤더군)

공개 문서에 없다. 1차 자료는 이 머신의 Claude Code 바이너리
(`~/.local/share/claude/versions/2.1.220`)에서 추출한 문자열과 파싱 코드다.

| 헤더 | 의미 |
|---|---|
| `anthropic-ratelimit-unified-status` | 기본값 `allowed`, 거부 시 `rejected` |
| `anthropic-ratelimit-unified-reset` | **Unix epoch 초 정수** (RFC 3339 아님) |
| `anthropic-ratelimit-unified-fallback` | `available`이면 fallback 모델 사용 가능 |
| `anthropic-ratelimit-unified-representative-claim` | 현재 바인딩된 창. 열거값 `five_hour`, `seven_day`, `seven_day_opus`, `seven_day_sonnet`, `seven_day_overage_included` |
| `anthropic-ratelimit-unified-overage-status` / `-overage-in-use` / `-overage-reset` / `-overage-disabled-reason` | 초과분 과금 상태 |
| `anthropic-ratelimit-unified-overage-period-monthly-utilization` / `-channel-utilization` | 초과분 사용률 |
| `anthropic-ratelimit-unified-grace-status` / `-grace-5h-utilization` / `-grace-7d-utilization` | 유예 구간 |
| `anthropic-ratelimit-unified-upgrade-paths` | 업그레이드 경로 |

바이너리에서 뽑은 파싱 코드가 `Number(o)`로 `-reset`을 읽고 다른 지점에서 `r*1000`으로
ms 변환하므로 epoch 초가 확실하다.

**이 리포에 대한 발견:** `backend/status.py:311-313`이 읽는
`anthropic-ratelimit-unified-5h-status` / `-7d-status` / `-fallback-percentage` 세 이름은
v2.1.220 바이너리에 **존재하지 않는다**(grep 카운트 0). 같은 함수의 `-representative-claim`,
`-overage-status`는 존재한다. 다만 `-grace-*-utilization`은 사용률이지 severity가 아니라
드롭인 대체재가 아니므로, 검증 없이 갈아끼우면 안 된다. 별도 작업으로 분리했다.

한편 이 리포의 주 경로는 헤더가 아니라 `GET https://api.anthropic.com/api/oauth/usage`
(`backend/poller.py:209`)이고, 이쪽이 쿼터를 소모하지 않으면서 5h/7d 사용률을 준다.
헤더 경로는 지금도 폴백일 뿐이다.

### 1.2 나머지 벤더 — 전부 negative

| 벤더 | 완성 응답 헤더 | 스코프 |
|---|---|---|
| Anthropic 공개 API | `anthropic-ratelimit-{requests,tokens,input-tokens,output-tokens}-{limit,remaining,reset}` | 조직 단위 API 한도. **구독 잔량 아님** |
| OpenAI | `x-ratelimit-{limit,remaining,reset}-{requests,tokens}`, `-project-tokens` | 조직/프로젝트 단위. ChatGPT 구독과 무관 |
| OpenRouter | 플랫폼 제한 **에러 응답에만** `X-RateLimit-*` | 키 단위 크레딧 캡 |
| Gemini / Vertex | **문서화 없음** | 프로젝트 단위 |
| xAI | **문서화 없음** (본문에 `usage.cost_in_usd_ticks`) | 팀×모델×티어 |
| Moonshot / Kimi | **문서화 없음** | 계정 Tier0~5 |
| Z.ai / BigModel | **문서화 없음** (267개 문서 전수 grep, 히트 0) | 계정×모델×티어 |
| Alibaba DashScope | **문서화 없음** (`X-DashScope-Wait-Timeout`은 *요청* 헤더) | 루트 계정 |
| GitHub Models | 추론 호스트 `models.github.ai`는 **문서화 없음** | 플랜별 RPM/RPD |

`api.github.com`(코어 REST)은 `x-ratelimit-{limit,remaining,used,reset,resource}`가 완전히
문서화돼 있지만, 이게 `models.github.ai`에도 붙는지는 `INFERRED — 미검증`이다.

### 1.3 저비용 프로브는 대체로 함정

Anthropic `count_tokens`는 무료지만 문서가 "Token counting and message creation have
separate and independent rate limits"라고 명시한다. 즉 그 응답의 헤더는 count_tokens
자신의 버킷이지 Messages 잔량이 아니다. **프로브로 쓸 수 없다.**

나머지 벤더는 헤더가 없으니 프로브 자체가 무의미하다. 실제 대안은 본문 조회
엔드포인트뿐이다(§1.5).

### 1.4 프록시 인터셉션 — 가능하지만 대가가 있다

**Claude Code는 인증서를 핀닝하지 않는다.** `HTTPS_PROXY`/`HTTP_PROXY`/`NO_PROXY`
표준 변수를 따르고(SOCKS 미지원), `NODE_EXTRA_CA_CERTS`로 커스텀 CA를 신뢰하며,
`CLAUDE_CODE_CERT_STORE`가 `bundled,system`을 기본으로 쓴다. 공식 문서가 기업
TLS-inspection 프록시를 "추가 설정 없이 동작"한다고 명시한다. 로컬 CA MITM은 공식
지원 시나리오다.

**단, 결정적 함정이 있다.** `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` /
`apiKeyHelper` 중 하나라도 세우면 claude.ai 구독 로그인이 밀려난다. 문서 원문:
"A gateway credential variable takes precedence over a saved claude.ai login or Console
key." **구독 사용량을 재려고 프록시를 끼우면서 자격증명 변수를 쓰면, 그 순간 구독이
아니라 그 키로 과금된다.** `ANTHROPIC_BASE_URL`만 바꾸고 자격증명 변수는 두는 조합이
실제로 동작하는지는 문서에 명시가 없다 — `INFERRED — 미검증`.

**Codex CLI는 `OPENAI_BASE_URL`을 읽지 않는다.** 이 머신의 v0.146.0 바이너리에서
문자열 카운트 0. 대신 `~/.codex/config.toml`의 `openai_base_url` 키를 쓴다. 그리고 이
머신에는 실제로 `openai_base_url = "http://127.0.0.1:10100/v1"`가 설정돼 있고 해당
포트에 프록시가 리슨 중이다 — **이 방식은 검증된 동작이다.**

이미 이걸 하는 OSS: LiteLLM proxy(`LiteLLM_SpendLogs` 테이블에 `spend`/`total_tokens`,
`/spend/logs` 조회), claude-code-router, ccflare, Helicone, Portkey. 프록시가 아닌
로컬 로그 파서로는 ccusage가 Claude Code·Codex·OpenCode·Droid·Kimi·Qwen 등을 지원한다.

### 1.5 스트리밍 토큰 집계 — 누적 vs 합산

프록시로 토큰을 세려면 이 구분이 중요하다.

- **Anthropic SSE**: `message_delta.usage.output_tokens`. 문서 원문 "The token counts
  shown in the `usage` field of the `message_delta` event are **cumulative**" — 마지막
  이벤트를 취해야 하고 **합산하면 안 된다**. `message_stop`에는 usage가 없다.
- **OpenAI SSE**: `stream_options: {"include_usage": true}` 필요. `choices`가 `[]`인
  추가 최종 청크에 `usage.{prompt_tokens, completion_tokens, total_tokens}`가 실린다.
  문서화된 실패 모드: 스트림이 중단되면 최종 usage 청크를 못 받을 수 있다.
- **Gemini**: `usageMetadata.{promptTokenCount, candidatesTokenCount, totalTokenCount, ...}`.
  청크마다 실리는지, 누적인지는 공식 문서에 없다 — `INFERRED — 미검증`.

### 1.6 본문으로 잔량을 주는 엔드포인트

| 벤더 | URL | 인증 | 관리자 키 |
|---|---|---|---|
| OpenRouter 키 정보 | `GET openrouter.ai/api/v1/key` | `Bearer <API_KEY>` | 아니오 |
| OpenRouter 크레딧 | `GET openrouter.ai/api/v1/credits` | Management 키 | **예** |
| DeepSeek | `GET api.deepseek.com/user/balance` | `Bearer <API_KEY>` | 아니오 |
| Moonshot/Kimi | `GET api.moonshot.ai/v1/users/me/balance` | `Bearer <API_KEY>` | 아니오 |
| OpenAI 사용량/비용 | `GET api.openai.com/v1/organization/{usage/completions,costs}` | Admin 키 | **예** |
| Anthropic 사용량/비용 | `GET api.anthropic.com/v1/organizations/{usage_report/messages,cost_report}` | Admin 키 (`sk-ant-admin01-`) | **예** |
| xAI | `GET /v1/billing/teams/{id}/prepaid/balance` | Management 키 | **예** |
| Z.ai / BigModel | **없음** | — | — |
| Alibaba DashScope | **없음** | — | — |

Admin 키가 필요한 것들은 개인 계정에서 쓸 수 없다(Anthropic Admin API는 조직 필요).
Token Bar가 개인 구독을 대상으로 한다면 실질적으로 OpenRouter·DeepSeek·Moonshot 셋만
바로 쓸 수 있다.

### 1.7 로컬 디스크 아티팩트 (이 머신에서 실측)

**Codex — `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`**
`type=="event_msg"` && `payload.type=="token_count"` 라인에 두 가지가 함께 들어 있다.

```
payload.info.total_token_usage.{input_tokens, cached_input_tokens,
                                cache_write_input_tokens, output_tokens,
                                reasoning_output_tokens, total_tokens}   ← 세션 누적
payload.info.last_token_usage.{동일}                                      ← 직전 턴
payload.info.model_context_window
payload.rate_limits.primary.{used_percent, window_minutes, resets_at}     ← 구독 창 ★
payload.rate_limits.secondary.{동일}
payload.rate_limits.credits.{has_credits, unlimited, balance}
```

`rate_limits`가 **ChatGPT 구독 창 사용률과 리셋 시각을 그대로 준다.** 네트워크 호출 0회.
`resets_at`은 Unix epoch 초. 함정은 `primary`/`secondary`가 `null`인 라인이 흔하다는 것
— 최근 파일부터 역순으로 populated 라인을 찾아야 한다. `total_token_usage`는 이미
누적값이라 라인마다 더하면 안 된다.

이 리포의 `backend/local_sync.py:127`(`codex_snap`)이 정확히 이 필드들을 읽고 있어
구현이 리서치와 일치한다.

**Claude Code — `~/.claude/projects/<cwd를 -로 치환>/<sessionId>.jsonl`**
`type=="assistant"` 라인의 `message.usage`에
`{input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens,
server_tool_use, cache_creation, iterations[]}`.

함정 두 개:
1. `iterations[]`가 생겼다. **최상위 usage와 iterations를 둘 다 더하면 이중 계산**이다.
   반대로 fallback이 일어난 턴은 `iterations[0]`의 cache_creation 토큰이 최상위에
   반영되지 않아, 최상위만 쓰면 누락된다. (`iterations` 의미론의 공식 문서는 못 찾음 —
   실측 해석이다.)
2. **rate-limit 헤더는 jsonl에 저장되지 않는다.** 로컬 파일만으로는 5h/7d 구독 잔량을
   알 수 없고 `oauth/usage`나 헤더가 필요하다.

`backend/local_sync.py:214`(`claude_usage_totals`)는 최상위 3개 필드만 더하므로 위 1번의
이중 계산은 없지만, fallback 턴 누락은 그대로 있다.

---

## 2. 프로바이더별 추출 경로

### 2.0 한눈에

`잔여 쿼터`는 "지금 얼마나 남았는가"를 폴링으로 알 수 있는지다. 누적 사용량만
읽히는 건 `누적만`으로 적었다.

| 프로바이더 | 잔여 쿼터 | 최선 경로 | 근거 강도 |
|---|---|---|---|
| **Kimi Code** | ✅ 최상 | `GET api.kimi.com/coding/v1/usages` + `~/.kimi-code/credentials/kimi-code.json` | **실측 200** |
| **Kiro** | ✅ | `GET management.us-east-1.kiro.dev/getUsageLimits?profileArn=` + `~/.aws/sso/cache/kiro-auth-token.json` | **실측 200 + 실데이터** |
| **Cursor** | ✅ | `POST api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage` + Keychain | **실측 200** |
| **Factory Droid** | ✅ | `GET api.factory.ai/api/billing/limits` + `FACTORY_API_KEY` | 바이너리 역추출, 401만 확인 |
| **Z.ai GLM** | ✅ | `GET api.z.ai/api/monitor/usage/quota/limit` + `~/.claude/settings.json` | 서드파티 역산(2차), 미호출 |
| **Kilo Code** | ✅ 잔액 | `kilo profile --json` | 소스 확인, 미호출 |
| **Cline** | ✅ 잔액 | `GET api.cline.bot/api/v1/users/{uid}/balance` | 소스 확인, 미호출 |
| **Hermes** | ⚠️ 부분 | `~/.hermes/state.db` (누적) + Nous `/api/billing/state` | 스키마만, DB 부재 |
| **OpenCode** | ❌ 누적만 | `~/.local/share/opencode/opencode.db` `session` 테이블 | **실측 검증** |
| **Alibaba Qwen** | ❌ 불가 | `~/.qwen/usage/token-usage-*.jsonl` (누적) + 429 문자열 | 1차 (부정 확인) |
| **Ollama** | ❌ 불가 | `POST /api/me` (플랜 등급만) | 1차 (부정 확인) |

기존 6개(codex, claude, xai, antigravity, copilot, devin)는 이미 연동돼 있어 이
표에서 뺐다. 관련 발견은 §1.1과 §1.7에 있다.

### 2.1 Kimi Code — 가장 깔끔한 사례

단일 GET 한 번으로 메뉴바에 필요한 게 전부 나온다. 실측 응답:

```
usage.{limit, used, remaining, resetTime}        ← 주간 창 (문자열 숫자!)
limits[].window.{duration, timeUnit}             ← 300 + TIME_UNIT_MINUTE = 5시간
limits[].detail.{limit, remaining, resetTime}    ← 5시간 창
user.membership.level                            ← 플랜 티어
parallel.limit                                   ← 동시 요청 한도
```

`GET https://api.kimi.com/coding/v1/usages`, 헤더 `Authorization: Bearer <access_token>`.
토큰은 `~/.kimi-code/credentials/kimi-code.json`에 평문으로 있다.

구현 함정이 여럿이다.
- `limit`/`used`/`remaining`이 **JSON 문자열**이다. 캐스팅 필수.
- proto3 zero-omission — 값이 0이면 **키가 아예 없다**. 공식 CLI도 `used ?? 0`으로 방어한다.
- `access_token` 수명이 **900초**뿐이다. 폴링마다 `expires_at`을 보고 갱신해야 한다.
- `refresh_token`이 **회전**한다. 갱신 응답의 새 값을 파일에 되쓰지 않으면 사용자의
  CLI 로그인이 깨진다. 공식 CLI와 파일을 공유하므로 쓰기 경합에 주의.
- 카운트 단위가 토큰이 아니라 **요청 수**라서 probe 요청은 순손실이다.

갱신은 `POST https://auth.kimi.com/api/oauth/token`,
`client_id=17e5f671-d194-4dfb-9706-5516cb48c098`, `grant_type=refresh_token`.

문서화된 API가 아니다(공식 CLI 바이너리 + 실측 200이 근거). CN 리전용 호스트는 미확인.

### 2.2 Kiro — 토큰 획득이 가장 쉽다

`GET https://management.us-east-1.kiro.dev/getUsageLimits?profileArn=<arn>`,
헤더 `Authorization: Bearer <accessToken>`. 실측 200 + 실데이터 확인.

`~/.aws/sso/cache/kiro-auth-token.json`이 **평문 JSON**이고 `accessToken`과
`profileArn`이 한 파일에 다 있다. 네 제품 중 토큰 획득이 가장 쉽다.

읽는 법:
- `usageBreakdownList[].{currentUsageWithPrecision, usageLimitWithPrecision}` — 퍼센트는 직접 계산
- `nextDateReset` — **epoch 초 float, 지수표기**(`1.7855424E9`). 순진한 정수 파서는 깨진다
- `subscriptionInfo.subscriptionTitle` — 플랜명
- `daysUntilReset`과 `limits`(단수)는 **null로 온다.** 쓰지 말 것

리셋은 **UTC 달력 월 경계**이지 결제 기념일이 아니다. 크레딧 소비량은 IDE 문서상
"최소 5분마다 갱신"이라 실시간이 아니다.

리스크: `accessToken` 수명이 몇 시간이고, IDE가 꺼져 있으면 갱신이 안 돼 401이 난다.
매 폴링마다 파일을 다시 읽어야 한다. social 로그인의 갱신 엔드포인트는 미확인.

### 2.3 Cursor — CLI가 하는 일을 그대로

`POST https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage`,
헤더 `Authorization: Bearer <token>`, `connect-protocol-version: 1`, 바디 `{}`.

핵심 필드: `planUsage.totalPercentUsed`(그대로 % 사용 가능),
`billingCycleStart`/`billingCycleEnd`(epoch ms 문자열), `planUsage.{remaining, limit}`(센트),
`autoPercentUsed`/`apiPercentUsed`(Auto 풀 vs 지정 모델 풀).
`GetUsageLimitStatusAndActiveGrants`가 `isInSlowPool`/`resetAtMs`를 준다.

토큰은 macOS Keychain: `security find-generic-password -s cursor-access-token -a cursor-user -w`.
JWT 수명이 정확히 60일이다.

**이건 "웹 대시보드 백엔드 남용"이 아니다** — CLI의 `/usage` 슬래시 커맨드가
`Promise.all([getCurrentPeriodUsage, getHardLimit, getPlanInfo])`로 정확히 같은 RPC를
호출한다(바이너리 오프셋 966157에서 확인). 그래도 계약 없는 사설 API다.

주의: `/usage`가 서버 피처 게이트 뒤에 있어 Cursor가 계정별로 끌 수 있다.
헤드리스 usage 출력은 없다(`--format json`은 인증 상태만 준다).
공식 Admin API(`api.cursor.com/teams/*`)는 **Team/Enterprise 전용**이라 개인 Pro는 403이다.

### 2.4 Factory Droid — API 키를 쓰는 게 맞다

`GET https://api.factory.ai/api/billing/limits`, `Authorization: Bearer <fk-… 또는 access_token>`.
쿼터가 **3중 슬라이딩 윈도우 × 2개 풀**이다.

```
limits.standard.{fiveHour, weekly, monthly}.{usedPercent, windowEnd}
limits.core.{fiveHour, weekly, monthly}.{usedPercent, windowEnd}
extraUsageBalanceCents, overagePreference, extraUsageAllowed
usesTokenRateLimitsBilling   ← false면 레거시 빌링이라 사용량을 못 준다
```

자격증명 파일(`~/.factory/auth.v2.file`)이 **암호화**돼 있고 복호화 알고리즘을
특정하지 못했다. 사용자가 `FACTORY_API_KEY`(`fk-…`)를 직접 발급해 넣는 쪽이
훨씬 견고하다. 검증은 `GET /api/cli/whoami`.

미검증: 이 머신이 droid 미로그인이라 **실제 응답 JSON을 못 봤다.** 스키마는 전부
바이너리 역추출이고, `windowEnd`가 ISO8601인지 epoch ms인지 확정 못 했다
(`new Date(...)`가 둘 다 받으므로 코드만으로는 구분 불가).

### 2.5 Z.ai GLM Coding Plan — 근거가 약한 게 유일한 문제

`GET https://api.z.ai/api/monitor/usage/quota/limit` (CN은 `open.bigmodel.cn`),
`Authorization: Bearer <apikey>`.

`data.limits[]`의 각 엔트리가 `percentage`, `usage`, `currentValue`, `remaining`,
`nextResetTime`(**epoch ms**), `usageDetails[]`(모델별)를 준다. 윈도우 길이는
`unit`+`number`로 인코딩(`unit:3, number:5` = 5시간, `unit:6, number:1` = 주간).

토큰은 `~/.claude/settings.json`의 `env.ANTHROPIC_AUTH_TOKEN`에서 얻되,
`env.ANTHROPIC_BASE_URL`이 `api.z.ai/api/anthropic` 또는
`open.bigmodel.cn/api/anthropic`일 때만 GLM 키다(리전 판별도 겸함).

**공식 문서로 직접 확인한 것**: 티어 표(Lite 2,000/10,000 · Pro 12,000/60,000 ·
Max 28,000/140,000 크레딧), 5시간 창이 소비 시점 기준 롤링이라는 것, 5시간과 주간
창이 병존한다는 것(에러 코드 1316/1317이 분리돼 있는 게 근거), raw Bearer 키가
통한다는 것(JWT 강제는 해제됨).

**공식 문서에 없는 것**: `/api/monitor/usage/*` 엔드포인트 자체와 그 응답 스키마.
서드파티 구현체 4종(CodexBar, openusage, openclaw, opencode-glm-quota)의 파싱
코드에서 역산했고 **실제 호출 검증을 못 했다.**

구현 시 주의:
- `percentage`를 **Double로 받을 것.** 구현체마다 Int/소수가 갈리고 실제로 `40.5`가 온다
- `Bearer` 접두사 여부가 구현체마다 갈린다. **401 시 반대 형식으로 재시도**하는 폴백을 넣을 것
- 공식 FAQ가 자기모순이다(한 곳은 7일, 다른 곳은 5시간). **문서가 아니라 응답을 신뢰할 것**
- 플랜 모델이 **2026-07-30에 prompt 개수 → credit 기반으로 바뀌었다.** 기존 prompt 기반 로직은 전부 stale

리셋 시각을 실어 주는 429 에러 코드: 1308(창 소진), 1310(주간/월간),
1316/1317(5시간/7일 + 잔액 부족), 1309(플랜 만료), 1113(잔액 부족).
전부 `{next_flush_time}`을 포함하지만 **실패한 호출에만 온다.**

### 2.6 Kilo Code — CLI가 JSON을 준다

**전제 정정: Kilo Code는 더 이상 Cline/Roo 포크가 아니다.** HEAD 시점에서
**OpenCode(sst/opencode) 포크**다. Roo 계열 코드는 `legacy-migration/`에만 남아 있다.
그리고 도메인이 `kilocode.ai` → **`api.kilo.ai`**로 리브랜딩됐다.

**리셋 시각까지 주는 유일한 경로**는 `GET https://api.kilo.ai/api/trpc/kiloPass.getState`
→ `{currentPeriodBaseCreditsUsd, currentPeriodUsageUsd, currentPeriodBonusCreditsUsd,
nextBillingAt}` (`packages/kilo-gateway/src/api/kilo-pass.ts:29-40`). 조사한 OSS 4종
중 사용량·잔액·리셋을 한꺼번에 주는 건 이것뿐이다.

잔액만 필요하면 `kilo profile --json` →
`{name, email, team, organizationId, balance}`. 안정적인 JSON 스키마에 인증 처리가
내장돼 있다. 직접 호출은 `GET https://api.kilo.ai/api/profile/balance` +
`Bearer`(+ 조직이면 `x-kilocode-organizationid`), 토큰은
`~/.local/share/kilo/auth.json`(평문 0600 — Cline과 달리 SecretStorage 벽이 없다).

누적 토큰은 `~/.local/share/kilo/kilo.db`의 `session` 테이블 — OpenCode와 **동일
스키마**라 코드 재사용이 된다.

미검증: 로컬 설치본이 미사용 상태라 엔드포인트를 한 건도 실호출 검증하지 못했다.
잔액 단위가 달러라는 근거는 포맷터의 `$${balance.toFixed(2)}` 하나뿐이다.
v5(Roo 포크) → v7(OpenCode 포크) 전환 중이라 사용자 버전에 따라 저장 위치가 완전히
다르고, 마이그레이션 중인 설치본은 양쪽에 데이터가 걸쳐 있을 수 있다.

### 2.7 Cline — 잔액 API는 있는데 토큰을 못 얻는다

`GET https://api.cline.bot/api/v1/users/{uid}/balance` → `{balance, userId}`.
`/usages`, `/payments`, 조직용 엔드포인트도 있다. 인증은 WorkOS 기반 Bearer.

누적 사용량은 `state/taskHistory.json`이 가장 깔끔하다 —
`{tokensIn, tokensOut, cacheWrites, cacheReads, totalCost}` 배열. 이건 VS Code
globalState(`state.vscdb`)가 아니라 **별도 JSON 파일**이라 읽기 쉽다.

**단 경로가 둘로 갈린다.** CLI/JetBrains는 `~/.cline/data/`,
VS Code 확장은 `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/state/taskHistory.json`
(Cursor면 `Cursor/User/...`). 둘 다 봐야 한다.

**최대 제약: VS Code 확장의 인증 토큰은 SecretStorage(OS 키체인)에 있어 디스크에서
읽을 수 없다.** 잔액 API 경로는 `~/.cline/data/secrets.json`(평문 0600)이 있는
CLI 사용자에게만 실용적이다.

미검증: 로컬 미설치라 실파일 검증을 한 건도 못 했다. 크레딧 단위 배수가 소스 내에서
모순된다 — 포맷터는 "microcredits, 1 credit = 10,000"이라는데 다른 두 경로는
`balance / 100`을 쓴다. 실측 없이는 확정 불가.

### 2.8 Hermes Agent — 계측 설계는 가장 좋은데 데이터가 없다

프로젝트 확정: `NousResearch/hermes-agent` v0.18.2 (로컬 git remote가 직접 증거).

`~/.hermes/state.db`에 전용 원장이 있다. `sessions` 테이블이 토큰 5종 +
`estimated_cost_usd`/`actual_cost_usd`를 분리해 담고 `cost_status`/`cost_source`로
출처까지 표기한다. `session_model_usage`는 (세션 × 모델 × 빌링경로)로 분해한다.
쓰기가 **가산 upsert**라 폴링 친화적이다.

`x-ratelimit-*` 헤더를 파싱하는 유일한 도구이기도 하다
(`agent/rate_limit_tracker.py`). **그러나 in-memory 전용이라 디스크에 남지 않는다** —
Hermes가 실행 중이 아니면 쿼터를 알 수 없다. Token Bar에는 구조적 문제다.

Nous 크레딧은 `GET /api/billing/state` (`portal.nousresearch.com`), 토큰은
`~/.hermes/auth.json`(평문). 응답 스키마는 미검증.

**미검증 폭이 크다:** 이 머신에 `state.db`가 **존재하지 않고**(세션을 완료한 적이
없음), CLI는 venv의 Python 3.11 인터프리터가 삭제돼 **실행 자체가 안 된다**
(`bad interpreter`). 모든 CLI 정보가 argparse 소스 기반이다.

기계 판독용으로 가장 깔끔한 훅은 `hermes -z … --usage-file PATH`로, 실패해도
16개 필드의 JSON 리포트를 쓴다. 다만 사후적이고 one-shot 전용이다.

### 2.9 OpenCode — 쿼터가 없다, 원장만 있다

로컬 계측은 조사한 도구 중 가장 좋다. `~/.local/share/opencode/opencode.db`의
`session` 테이블이 `cost`, `tokens_input/output/reasoning/cache_read/cache_write`를
**비정규화 컬럼**으로 갖고 있어 SQL 한 번에 읽힌다. 실측 212 세션 집계 확인.

**그런데 "남은 할당량"을 어디에도 저장하지 않는다.** Zen 프로바이더의 백엔드 소스가
레포에 통째로 들어 있는데 라우트가 추론 4종뿐이고 **balance/credits/usage 조회
엔드포인트가 아예 없다.** 클라이언트에도 잔액 fetch가 0건이다.

쿼터 신호는 4xx가 터져야만 온다 — `GoUsageLimitError` 바디 + `retry-after` 헤더.
`packages/llm`이 `x-ratelimit-*`와 `anthropic-ratelimit-*`를 파싱하긴 하는데
`if (response.status < 400) return response`로 막혀 있어 **정상 응답에서는
읽지도 저장하지도 않는다.** 사전 폴링 불가.

실질적으로 사용자가 OpenRouter 키를 쓰면 **OpenRouter의 `/api/v1/key`가 진짜
잔액 소스**다. 이건 OpenCode 밖이라 Token Bar가 직접 호출해야 한다.
키는 `~/.local/share/opencode/auth.json`(평문)에 있다.

주의: 이 머신의 `opencode.db`가 **454MB**다. 폴링마다 여는 건 부담이고
`time_updated` 인덱스가 없어 전체 스캔 위험이 있다. WAL 모드라 `?immutable=1` 금지,
`mode=ro` 권장. 스키마가 drizzle 마이그레이션으로 계속 바뀌므로 컬럼 부재를 방어해야 한다.

`opencode stats`는 `--json`이 없고 ASCII 박스 표라 파싱이 취약하다.

### 2.10 Alibaba Qwen — 공식적으로 불가

**Qwen OAuth 무료 티어는 2026-04-15부로 종료됐다.** `chat.qwen.ai` device flow는
`/auth` 선택지에서 사라졌다. "하루 2,000 요청 무료" 전제는 이제 유효하지 않다.

Coding Plan 잔여 쿼터 조회는 공식 FAQ가 **"暂无法查看"**(현재 조회 불가)라고 못
박았다. 쿼터 단위는 토큰이 아니라 **모델 호출 횟수**다(Pro 기준 5시간 6,000회 /
주 45,000회 / 월 90,000회).

남는 경로는 둘.
1. **로컬 원장** `~/.qwen/usage/token-usage-YYYY-MM.jsonl` — 호출 1건당 1줄,
   `{inputTokens, outputTokens, cachedTokens, thoughtsTokens, totalTokens, model,
   authType, sessionId, apiDurationMs}`. 실물 확인됨. 단 **qwen-code CLI를 쓸 때만**
   쌓이므로, 사용자가 Coding Plan 키를 Claude Code에 꽂아 쓰면 안 잡힌다.
2. **429 에러 문자열** — `hour/week/month allocated quota exceeded`가 소진된 창을
   특정한다. Token Plan은 리셋 시각까지 포함하지만 **연도가 없어**(`"07-27 09:25:00 UTC"`)
   연말 경계에서 깨진다.

CN vs 국제 분기가 크다: Coding Plan(`coding.` vs `coding-intl.`),
Token Plan(`cn-beijing.maas` vs `ap-southeast-1.maas`), Standard(`dashscope` vs
`dashscope-intl` vs `cn-hongkong.dashscope`) 전부 호스트가 다르다.

자원팩 잔량은 BssOpenApi `QueryResourcePackageInstances`로 읽을 수 있으나
AccessKey(AK/SK) 서명이 필요해 메뉴바 앱에는 자격증명 부담이 크고, Bailian용
`ProductCode` 값도 확정하지 못했다.

### 2.11 Ollama — 쿼터 API가 없다

로컬 런타임은 과금 대상이 아니라 "잔여 쿼터" 개념 자체가 없다. 얻을 수 있는 건
`GET /api/ps`의 로드된 모델·VRAM 점유·언로드 예정 시각, `GET /api/tags`의 모델 목록,
그리고 호출별 `eval_count`/`prompt_eval_count`뿐이다.

클라우드는 `POST http://localhost:11434/api/me`가 **플랜 등급**(`free`/`pro`/`max`)을
준다. 그게 전부다. 사용량/쿼터 엔드포인트는 라우트 테이블에 없고, 이를 요청한
이슈 2건(#15663, #16448)이 모두 중복 종결됐다. 이슈 본문이 "현재 이 한도를
모니터링할 유일한 방법은 웹 UI"라고 적고 있다.

인증이 특이하다. `ollama signin`은 **베어러 토큰 파일을 만들지 않는다.**
ollama.com에 로컬 공개키를 등록할 뿐이고 이후 인증은 `~/.ollama/id_ed25519`로
**요청마다 서명**한다. 데몬을 거치지 않고 직접 붙으려면 ed25519 서명을 구현해야
하는데, 민감 자격증명 접근이라 권장하지 않는다. **로컬 데몬 경유가 압도적으로 안전하다.**

결론: Token Bar에서 Ollama는 잔여 쿼터 표시가 불가능하다. 표시 가능한 건 플랜 등급,
로드된 모델/VRAM, 그리고 앱이 직접 집계한 누적 토큰이다. **이 제약을 UI에 명시하는
편이 낫다.**

---

## 3. 검증하지 못한 것

§1 범위에서 확정하지 못한 항목:

1. Anthropic `anthropic-fast-*` 헤더의 정확한 이름 목록
2. `anthropic-ratelimit-unified-*`의 **공식** 문서 — 존재하지 않는다. 근거가 바이너리
   문자열뿐이라 버전 업그레이드 시 조용히 바뀔 수 있다
3. `status.py`가 쓰는 세 헤더 이름의 원래 출처
4. OpenAI/Anthropic rate-limit 헤더가 저비용 호출에도 붙는지
5. Vertex AI 응답 헤더 (문서 fetch가 네비게이션 셸만 반환 — 부분 검증)
6. GitHub `x-ratelimit-*`가 `models.github.ai`에도 붙는지
7. Gemini 스트리밍 `usageMetadata`의 청크별 존재/누적 여부
8. Codex CLI의 `HTTP_PROXY` 실제 처리 방식
9. `ANTHROPIC_BASE_URL`만 바꿔 **구독 인증을 유지한 채** 프록시를 태울 수 있는지
10. xAI Management API의 정확한 호스트
11. OpenAI usage API의 bucket 봉투 정확한 형태 (403으로 원문 미확인)
