# AI 코딩 에이전트 / 토큰 플랜 가격표 총정리

- 조사일: 2026-07-31
- 통화: 명시 없으면 USD, 월 결제 기준
- CNY → USD 환산은 ¥7.2/$1 기준 근사치 (참고용)
- 출처: 각 절 하단. 공식 페이지가 크롤링 불가(403/429/JS 렌더링)한 경우 2차 출처임을 표기

---

## 0. 한눈에 보기 (개인 유료 티어 기준)

| 제품 | 진입가 | 중간 티어 | 상위 티어 | 과금 단위 |
|---|---|---|---|---|
| Codex (ChatGPT) | Go $8 / Plus $20 | Pro $100 | Pro $200 | 크레딧(토큰 환산) + 5시간 롤링 |
| Claude (Claude Code) | Pro $20 | Max 5x $100 | Max 20x $200 | 세션/주간 사용량 |
| Google Antigravity | 무료(일 20 요청) | AI Pro $20 / Ultra $100 | AI Ultra $200 | 쿼터 + AI 크레딧 $0.01/개 |
| Grok (xAI) | SuperGrok Lite $10 | SuperGrok $30 | Heavy $300 | 구독 rate limit / API 토큰 |
| Cursor | Pro $20 | Pro+ $60 | Ultra $200 | 달러 표시 크레딧 풀 |
| Devin | Pro $20 | Max $200 | Teams $80 + $40/seat | ACU (구 플랜 $2.25/ACU) |
| Factory Droid | Pro $20 | Plus $100 | Max $200 | 5h/7d/30d 롤링 rate limit |
| opencode | Zen PAYG (마크업 0) | Go $10 | — | 토큰 실비 / 5시간 요청수 |
| Ollama | 무료 | Pro $20 | Max $100 (신규 중단) | GPU 시간 |
| Kilo Code | 무료(OSS) | Pass $19 / $49 | Pass $199, Teams $15/seat | 크레딧(보너스 최대 +40%) |
| Cline | 무료(OSS, BYOK) | Teams(소액) | Enterprise 별도 | 마크업 0, 모델사 직접 과금 |
| GitHub Copilot | Pro $10 | Pro+ $39 | Max $100 | AI 크레딧 1 = $0.01 |
| Kiro (AWS) | Pro $20 | Pro+ $40 / Pro Max $100 | Power $200 | 크레딧, 초과 $0.04/크레딧 |
| Kimi Code | Moderato $19 | Allegretto $39 / Allegro $99 | Vivace $199 | 공용 크레딧 풀, 5시간 롤링 |
| Z.ai GLM Coding | Lite $18 | Pro $72 | Max $160 | 프롬프트 수 (5시간/주) |
| Alibaba Token Plan | Standard $30/seat | Pro $100/seat | Max $200/seat | 크레딧(월 리셋) |
| Alibaba Coding Plan | Pro ¥200 (≈$28) | — | — | 요청 수 (5h/주/월) |
| Hermes (Nous Portal) | Plus $20 | Super $100 | Ultra $200 | 달러 크레딧 |
| MiniMax Token Plan | Plus $20 | Max $50 | Ultra $120 | 쿼터 + 동시 에이전트 수 |
| Xiaomi MiMo | Lite $6 | Standard $16 / Pro $50 | Max $100 | 크레딧(4.1B~82B) |
| StepFun Step Plan | Mini ¥49 (≈$7) | Plus ¥99 / Pro ¥199 | Max ¥699 (≈$97) | 크레딧 (1M credit = ¥1) |

---

## 1. Codex (OpenAI / ChatGPT)

Codex는 별도 구독이 아니라 ChatGPT 플랜에 포함된다.

| 플랜 | 가격 | 비고 |
|---|---|---|
| Free | $0 | 제한적 |
| Go | $8/월 | |
| Plus | $20/월 | Codex, Work 에이전트, 커스텀 GPT 포함 |
| Pro | $100/월 | Plus 대비 5x |
| Pro | $200/월 | Plus 대비 20x |
| Business | $20/user/월 (2인 이상, 연간 결제) | |
| Enterprise / Edu | 별도 견적 | |

과금 구조

- 로컬 메시지 + 클라우드 채팅이 **5시간 롤링 윈도우**를 공유
- 크레딧 소모율(1M 토큰당): GPT-5.6 Sol 입력 125 / 출력 750, Terra 50 / 300, Luna 5 / 30
- 메시지당 평균 5~40 크레딧
- 한도 소진 시 플랜 업그레이드 없이 크레딧 추가 구매 가능
- 2026년 7월 초, Plus·Business·Pro의 5시간 리셋 윈도우가 고정 간격 리셋으로 변경
- API 참고가: GPT-5.6 Sol $5/$30, Terra $2.50/$15, Luna $1/$6 (1M 토큰)

출처: [learn.chatgpt.com/docs/pricing](https://learn.chatgpt.com/docs/pricing), [tokenkarma](https://tokenkarma.app/blog/openai-rate-limits-july-2026/) — openai.com/chatgpt/pricing 및 chatgpt.com/pricing은 403으로 직접 확인 불가

## 2. Claude (Anthropic / Claude Code)

| 플랜 | 월 결제 | 연 결제 | 비고 |
|---|---|---|---|
| Free | $0 | — | Claude Code 포함 |
| Pro | $20 | $17/월 ($200 선불) | |
| Max 5x | $100~ | — | |
| Max 20x | $200~ | — | 공식 페이지 표기는 "from $100" |
| Team (Standard seat) | $25/seat | $20/seat | 최소 2석, 최대 150석 |
| Team (Premium seat) | $125/seat | $100/seat | |
| Enterprise | $20/seat + API 요율 사용량 | — | 셀프서브 / 영업 지원 모두 |

모든 티어에 Claude Code가 포함된다.

출처: [claude.com/pricing](https://claude.com/pricing)

## 3. Google Antigravity

Antigravity 자체 구독이 아니라 **Google AI 플랜 쿼터**를 사용한다.

| 플랜 | 가격 | 쿼터 |
|---|---|---|
| 무료 | $0 | 일 20 에이전트 요청, 주 단위 리셋 (2025-12 기준 250 → 20으로 축소) |
| Google AI Pro | $20/월 | 5시간마다 쿼터 갱신 + 주간 한도 |
| Google AI Ultra | $100/월 | Pro 대비 5x 토큰 |
| Google AI Ultra | $200/월 | Pro 대비 20x (기존 $250에서 인하) |

- AI 크레딧: 개당 **$0.01**, 벌크 $199 = 20,000 크레딧
- 크레딧은 기본 플랜에서 제거되어 **초과분 전용**으로만 동작. Pro/Ultra만 구매·사용 가능
- Gemini Flash / Pro는 단일 통합 rate limit(API 가격 비율 기준), 서드파티 모델은 별도 고정 한도
- 크레딧 1개가 몇 토큰인지 Google이 공개하지 않아 예산 예측이 어렵다는 지적이 있음

출처: [antigravity.google/docs/plans](https://antigravity.google/docs/plans), [Changes to Antigravity Plans](https://antigravity.google/blog/changes-to-antigravity-plans), [agentpedia](https://agentpedia.codes/blog/antigravity-credits-pricing-explained), [devclass](https://www.devclass.com/ai-ml/2026/03/13/users-protest-as-google-antigravity-price-floats-upward/5209219)

## 4. Grok (xAI)

전용 "코딩 플랜"은 없고 소비자 구독 + API로 나뉜다.

소비자 구독 (2026년 7월 기준)

| 플랜 | 가격 |
|---|---|
| X Premium | $8/월 |
| SuperGrok Lite | $10/월 |
| SuperGrok | $30/월 ($300/년 = 실질 $25/월) |
| X Premium+ | $40/월 |
| SuperGrok Heavy | $300/월 |

API (1M 토큰, 입력/출력)

| 모델 | 표준 | 롱컨텍스트(≥200k) |
|---|---|---|
| Grok 4.5 (코딩 권장) | $2.00 / $6.00 (캐시 $0.30~0.50) | $4.00 / $12.00 |
| Grok 4.3 | $1.25 / $2.50 | $2.50 / $5.00 |
| Grok 4.20 (reasoning/non) | $1.25 / $2.50 | $2.50 / $5.00 |
| Grok-build-0.1 | $1.00 / $2.00 | $2.00 / $4.00 |

- 데이터 공유 프로그램 참여 시 월 최대 **$175 무료 API 크레딧**

출처: [docs.x.ai/docs/models](https://docs.x.ai/docs/models), [felloai](https://felloai.com/grok-pricing/), [aipricing.guru](https://www.aipricing.guru/xai-pricing/)

## 5. Cursor

| 플랜 | 가격 | 포함 사용량 |
|---|---|---|
| Hobby | $0 | 제한적 에이전트 요청 |
| Pro | $20/월 | 서드파티 모델 사용액 $20 |
| Pro+ | $60/월 | $70 (Pro 대비 3x 에이전트 한도) |
| Ultra | $200/월 | $400 (Pro 대비 20x) |
| Start (인도 한정) | ₹649/월 | — |
| Teams Standard | $40/user/월 | 팀 관리, SSO, 분석 |
| Teams Premium | $120/user/월 | Standard 대비 5x |
| Enterprise | 별도 견적 | 풀링 사용량, SCIM, 감사 로그 |

- 사용량 풀이 **두 개로 분리**: Cursor 자체 모델(Grok 4.5, Composer 2.5)은 넉넉한 별도 풀, 그 외 모델은 각 API 요율로 차감
- 모델 선택에 따라 크레딧 소모 속도가 크게 달라짐 (Claude Sonnet이 Gemini 대비 약 2.4x)

출처: [cursor.com/docs/account/pricing](https://cursor.com/docs/account/pricing), [cursor.com/pricing](https://cursor.com/pricing)

## 6. Devin (Cognition)

현행 플랜 (공식 페이지)

| 플랜 | 가격 | 비고 |
|---|---|---|
| Free | $0 | 가벼운 쿼터, 모델 제한 |
| Pro | $20/월 | 프런티어 모델 전체, 초과분은 API 요율 구매 |
| Max | $200/월 | 대폭 상향된 쿼터 |
| Teams | $80/월 + $40/월 per 개발자 seat | 플렉스 시팅 |
| Enterprise | 별도 견적 | |

ACU (Agentic Computing Unit) 참고

- 1 ACU ≈ Devin이 실제로 15분 작업하는 분량 (VM 시간 + 추론 + 네트워크)
- 구 Core 플랜: $20 + **$2.25/ACU**, Team 플랜 $500/월에 250 ACU 포함 시 $2.00/ACU
- 단순 버그픽스 1~5 ACU, 중간 난이도 작업 10~25 ACU
- ⚠️ 현행 공식 가격 페이지는 ACU 단가를 명시하지 않고 "API pricing"이라고만 표기 — ACU 수치는 2차 출처 기준이며 구 체계일 가능성

출처: [devin.ai/pricing](https://devin.ai/pricing), [usecarly](https://www.usecarly.com/blog/devin-pricing/), [lindy](https://www.lindy.ai/blog/devin-pricing)

## 7. Factory Droid

| 플랜 | 가격 | 사용량 |
|---|---|---|
| Pro | $20/월 | 기준 |
| Plus | $100/월 | Pro 대비 약 5x, Managed Droid Computers 포함 |
| Max | $200/월 | Pro 대비 약 10x, 얼리 액세스 |

- **3중 롤링 윈도우**(5시간 / 7일 / 30일)로 rate limit 관리
- 소진 순서: Standard Usage → Droid Core 전용 무료 풀 → Extra Usage(선불 크레딧)
- 선불 크레딧 최소 $10, 만료 없음
- BYOK도 동일한 rate limit 프레임워크를 따르며 전 티어에 무료 허용량 존재
- 커뮤니티 보고: $100 플랜에서 약 100M 토큰 (Codex 5.5 / Opus 4.7은 2x 차감) — 공식 문서에는 토큰 수치 미기재

출처: [docs.factory.ai/pricing](https://docs.factory.ai/pricing), [X @Ra1kshit](https://x.com/Ra1kshit/status/2050551221627523202)

## 8. opencode (Zen / Go)

| 옵션 | 가격 | 내용 |
|---|---|---|
| BYOK | $0 | 본인 API 키 사용 |
| Zen Pay-As-You-Go | 선불 잔액 $20부터 | **마크업 0**, 모델별 실비 |
| Go | 첫 달 $5, 이후 $10/월 | 16개 모델, 5시간 단위 요청 한도 |

Go 플랜 5시간당 요청 한도 예시: Grok 4.5 120회, Kimi K3 220회(2x 차감), GLM-5.2 880회, DeepSeek V4 Flash 31,650회, Hy3 30,100회

Zen 토큰 단가 예시 (1M 토큰, 입력/출력)

| 모델 | 가격 |
|---|---|
| GPT 5.4 Nano | $0.20 / $1.25 |
| Gemini 3.5 Flash Lite | $0.30 / $2.50 |
| Claude Haiku 4.5 | $1.00 / $5.00 |
| Claude Opus 5 | $5.00 / $25.00 |
| GPT 5.5 Pro | $30.00 / $180.00 |

- 무료 모델 상시 제공: DeepSeek V4 Flash Free, MiMo-V2.5 Free, Laguna S 2.1 Free, Ling-3.0-flash Free, North Mini Code Free, Nemotron 3 Ultra Free, Big Pickle
- 잔액 $5 미만 시 $20 자동 충전(변경/해제 가능), 카드 수수료 4.4% + $0.30 원가 전가

출처: [opencode.ai/docs/zen](https://opencode.ai/docs/zen/), [opencode.ai/go](https://opencode.ai/go)

## 9. Ollama

| 플랜 | 가격 | 클라우드 사용량 | 동시 모델 |
|---|---|---|---|
| Free | $0 | 기준 (주당 약 5M 토큰 수준) | 1 |
| Pro | $20/월 (또는 $200/년) | Free 대비 50x | 3 |
| Max | $100/월 | Pro 대비 5x (Free 대비 250x) | 10 |

- 과금 기준은 토큰이 아니라 **GPU 시간**. 모델 크기·요청 길이에 따라 소모 상이
- 5시간 세션 한도 + 7일 주간 한도
- Max는 용량 문제로 **신규 가입 중단** 상태
- Pro는 추가 사용량 구매 가능

출처: [ollama.com/pricing](https://ollama.com/pricing)

## 10. Kilo Code (kilo.ai)

플랜

| 플랜 | 가격 |
|---|---|
| Free & Open Source | $0 |
| Teams | $15/user/월 (14일 무료 체험) |
| Enterprise | 별도 견적 (SSO/OIDC/SCIM, 감사 로그, SLA) |

추론 비용 옵션

| 옵션 | 비용 |
|---|---|
| Auto Free / BYOK / 로컬 | $0 |
| Kilo Gateway | 제공사 실요율, **마크업 0** |
| Kilo Pass Starter | $19/월 → 최대 $26.60 크레딧 |
| Kilo Pass Pro | $49/월 → 최대 $68.60 크레딧 |
| Kilo Pass Expert | $199/월 → 최대 $278.60 크레딧 |

- 크레딧 구매 시 5% 결제 수수료
- 클라우드 컴퓨트 별도 과금: 초 단위, $0.33~$1.20/시간
- 도메인이 kilocode.ai → **kilo.ai**로 이전(308 리다이렉트)

출처: [kilo.ai/pricing](https://kilo.ai/pricing)

## 11. Cline

| 플랜 | 가격 |
|---|---|
| Open Source (개인) | $0 |
| Teams | $20/user/월 (2차 출처, 첫 10석 무료 주장) |
| Enterprise | 별도 견적 |

- 핵심: **구독료·마크업 없음.** OpenAI/Anthropic/Google 등 본인 API 키로 모델사에 직접 과금
- 공식 pricing 페이지에는 구체적 금액·크레딧·마크업 수치가 공개돼 있지 않음
- ⚠️ Teams $20 및 "첫 10석 무료"는 2차 출처 기준, 공식 확인 실패 (docs.cline.bot/plan/pricing은 404)

출처: [cline.bot/pricing](https://cline.bot/pricing), [comparedge](https://comparedge.com/tools/cline-ai/pricing), [costbench](https://costbench.com/software/ai-coding-assistants/cline/)

## 12. GitHub Copilot

**2026-06-01부로 전 플랜이 premium request → AI 크레딧 사용량 기반 과금으로 전환. 1 크레딧 = $0.01.**

| 플랜 | 가격 | 포함 크레딧 |
|---|---|---|
| Free | $0 | 자동 모델 선택 한정 |
| Student | 무료(인증 시) | 코드 완성 무제한 + 크레딧 할당 |
| Pro | $10/월 | $15 상당 |
| Pro+ | $39/월 | $70 상당 |
| Max | $100/월 | $200 상당 |
| Business | $19/seat/월 | 1,900 크레딧/user (조직 풀) |
| Enterprise | $39/seat/월 | 3,900 크레딧/user |

- 코드 완성(completions)은 계속 무제한. 채팅·에이전트·프리미엄 모델 사용이 크레딧을 소모
- 소모량은 입력/출력/캐시 토큰 × 모델별 API 요율로 계산
- 월간 Pro/Pro+ 사용자는 2026-06-01 자동 전환, **연간 결제자는 만료까지 기존 premium request 체계 유지**

출처: [docs.github.com/copilot/get-started/plans](https://docs.github.com/en/copilot/get-started/plans), [GitHub Blog](https://github.blog/news-insights/company-news/github-copilot-is-moving-to-usage-based-billing/)

## 13. Kiro (AWS)

| 플랜 | 가격 | 크레딧 |
|---|---|---|
| Free | $0 | 50 (오픈웨이트 모델 + Claude Sonnet 4.5) |
| Pro | $20/월 | 1,000 |
| Pro+ | $40/월 | 2,000 |
| Pro Max | $100/월 | 5,000 |
| Power | $200/월 | 10,000 |

- 초과분 애드온: **$0.04/크레딧** (기본 비활성, 월말 정산)
- Team 티어는 동일 가격에 통합 청구, 사용량 분석, AWS IAM Identity Center SSO 추가
- GovCloud는 약 20% 비싸고 무료 티어 없음

출처: [kiro.dev/pricing](https://kiro.dev/pricing/)

## 14. Kimi Code (Moonshot AI)

| 플랜 | 가격 | 사용량 배수 |
|---|---|---|
| Adagio | 무료 | 평가용 |
| Moderato | $19/월 | 1x (컨텍스트 256k) |
| Allegretto | $39/월 | 약 5x (1M 컨텍스트) |
| Allegro | $99/월 | 약 15x |
| Vivace | $199/월 | 약 30x |

- 전 티어가 **하나의 크레딧 풀**을 공유 — Kimi 채팅 앱 사용량도 Kimi Code 예산을 깎음
- 5시간 롤링 토큰 쿼터, 윈도우당 300~1,200 API 호출, 최대 동시 30 요청
- API 단가(1M 토큰, 입력/출력): K2.6 / K2.7 Code $0.95 / $4, K2.5 $0.60 / $2.50~$3, K3 $3 / $15. 반복 프롬프트 캐시 75% 할인
- ⚠️ Moonshot 공식 페이지 자체가 어느 티어부터 Kimi Code가 열리는지 표기가 일관되지 않다는 지적이 있음. 구독 직전 공식 페이지 재확인 권장 (kimi.com/coding은 JS 렌더링으로 직접 파싱 실패)

출처: [codeagentswarm](https://www.codeagentswarm.com/en/guides/kimi-code-plans-and-pricing), [nxcode](https://www.nxcode.io/resources/news/kimi-code-2026-plans-pricing-developer-guide), [benchlm](https://benchlm.ai/moonshot/api-pricing)

## 15. Z.ai GLM Coding Plan

| 플랜 | 월 | 연 | 30% 프로모 | 5시간 크레딧 | 주간 크레딧 | 프롬프트(5h / 주) | MCP 호출/월 |
|---|---|---|---|---|---|---|---|
| Lite | $18 | $151.20 | $12.60/월 | 2,000 | 10,000 | ~80 / ~400 | 100 |
| Pro | $72 | $604.80 | $50.40/월 | 12,000 | 60,000 | ~400 / ~2,000 | 1,000 |
| Max | $160 | $1,344 | $112/월 | 28,000 | 140,000 | ~1,600 / ~8,000 | 4,000 |

- 전 티어 동일 모델: GLM-5.2(플래그십), GLM-5-Turbo, GLM-4.7, GLM-4.5-air
- 피크 시간(14:00~18:00 UTC+8) 프리미엄 모델 3x 차감, 오프피크 2x — 2026년 9월까지 한시적으로 오프피크 1x
- Claude Code, Cline, Roo Code, OpenClaw 등 20종 이상 클라이언트 지원
- 2026-02-11부로 가격 인상 반영됨

출처: [docs.z.ai/devpack/overview](https://docs.z.ai/devpack/overview), [aipricing.guru](https://www.aipricing.guru/z-ai-subscription-pricing/), [Z.ai 공지](https://x.com/Zai_org/status/2021656635668901985)

## 16. Alibaba (Qwen) — 두 가지 상품

### 16-1. Token Plan (Team Edition) — 싱가포르 리전 한정

| 티어 | 가격 | 월 크레딧 |
|---|---|---|
| Standard | $30/seat/월 | 25,000 |
| Pro | $100/seat/월 | 100,000 |
| Max | $200/seat/월 | 250,000 |

- 크레딧은 매 청구 주기 리셋, 미사용분 소멸
- 공유 쿼터 팩: $700/월 = 625,000 크레딧 (팀 전체 공유)
- 포함 모델: qwen3.7-max/plus, qwen3.6-plus/flash, Qwen·Wan 이미지 모델 + DeepSeek, Moonshot, Zhipu, MiniMax 서드파티
- ⚠️ 일부 2차 출처는 $6 / $18 / $68 티어를 언급하나 공식 문서와 불일치. 공식 문서 수치를 채택

### 16-2. Coding Plan

| 티어 | 가격 | 쿼터 |
|---|---|---|
| Pro | ¥200/월 (≈$28) | 5시간 6,000 요청 / 주 45,000 / 월 90,000 |
| Lite | **단종** | 2026-03-20 신규 중단, 2026-04-13 갱신 중단 |

- 5시간 쿼터는 롤링 복원, 주간은 월요일 00:00 (UTC+8) 리셋, 월간은 갱신일 리셋
- 권장 모델: qwen3.7-plus, qwen3.6-plus, kimi-k2.5, glm-5, MiniMax-M2.5
- 지원 툴: Claude Code, OpenClaw, Cursor, Cline, QwenPaw, Qoder, Hermes Agent, OpenCode, Codex, Qwen Code, Lingma, Kilo CLI 등

출처: [Token Plan 개요](https://www.alibabacloud.com/help/en/model-studio/token-plan-overview), [Coding Plan](https://help.aliyun.com/en/model-studio/coding-plan)

## 17. Hermes Agent (Nous Research)

Hermes Agent 소프트웨어 자체는 **무료 오픈소스**. 유료는 선택적 관리형 구독인 Nous Portal.

| 티어 | 가격 | 보너스 크레딧 |
|---|---|---|
| Free | $0 | 월 $0.10 크레딧 |
| Plus | $20/월 | +$2 |
| Super | $100/월 | +$10 |
| Ultra | $200/월 | +$20 |

- 보너스는 가입·업그레이드·갱신 시 지급
- 전 티어 300+ 모델 + 번들 툴(웹 검색, 스크래핑, 이미지 생성, 브라우저 사용, 코드 실행, 음성) 포함
- 실사용 총비용 추정: 로컬 무료 모델 구성 월 $3~5, 유료 모델 + VPS 상시 운용 월 $30~80
- ⚠️ portal.nousresearch.com은 429로 직접 확인 실패, 2차 출처 기준

출처: [llmreference](https://www.llmreference.com/provider/nous-portal), [openclawlaunch](https://openclawlaunch.com/guides/nous-portal), [hostinger](https://www.hostinger.com/tutorials/hermes-agent-cost)

## 18. MiniMax

Token Plan (월 구독)

| 티어 | 가격 | 용도 | 동시 에이전트 |
|---|---|---|---|
| Plus | $20/월 | 개인 프로젝트·프로토타이핑 | 3~4 |
| Max | $50/월 | 일상 에이전트 코딩·멀티모달 | 4~5 |
| Ultra | $120/월 | 헤비 에이전트 워크플로 | 6~7 |

- 5시간 롤링 + 주간 쿼터 윈도우
- 전 티어 M3, M2.7, 이미지·음성·음악 모델 전체 접근
- 선불 크레딧 팩 $5~$100 별도 구매 가능, **365일 유효**, $1당 1,000 크레딧
- API: M2.5는 1M 토큰 $0.15부터
- ⚠️ 2026년 2월 시점 코딩 플랜은 M2.1 기반이었고 M2.5는 PAYG API로만 접근 가능하다는 보고가 있음. 현재 문서는 M3까지 포함으로 표기

출처: [platform.minimax.io/docs/guides/pricing-token-plan](https://platform.minimax.io/docs/guides/pricing-token-plan), [verdent](https://www.verdent.ai/guides/minimax-m2-5-pricing)

## 19. Xiaomi MiMo

Token Plan

| 티어 | 월 | 연 | 월 크레딧 | 연 크레딧 |
|---|---|---|---|---|
| Lite | $6 | $63.36 | 4.1B | 49.2B |
| Standard | $16 | $168.96 | 11B | 132B |
| Pro | $50 | $528 | 38B | 456B |
| Max | $100 | $1,056 | 82B | 984B |

- 연간은 월간 크레딧의 정확히 12배를 12개월치 요금의 약 88% 가격에 제공
- 유효기간: 월간은 구매일 + 30일(23:59:59 UTC), 연간은 구매일부터 1년
- 동시에 **하나의 패키지만 활성화** 가능. 크레딧 또는 유효기간이 0이 되면 즉시 정지
- 미사용 크레딧 환불 불가, 다운그레이드 불가, 업그레이드는 차액 결제
- 베이징 오프피크 시간대 0.8x 차감 혜택

API 단가 (1M 토큰, 캐시히트 입력 / 캐시미스 입력 / 출력) — 2026-05-27 개정

| 모델 | 가격 |
|---|---|
| MiMo-V2.5 | $0.0028 / $0.14 / $0.28 |
| MiMo-V2.5-Pro | $0.0036 / $0.435 / $0.87 |
| MiMo-V2.5-ASR | $0.074/시간 |

- V2.5 시리즈는 **롱컨텍스트 추가 요금 없음**
- MiMo-V2 시리즈는 2026-06-30 지원 종료

출처: [mimo.mi.com](https://mimo.mi.com/), [threatfrontier](https://threatfrontier.com/articles/xiaomi-mimo-token-plan-pricing-2026-tier-guide-for-coding-agents), [openrouter](https://openrouter.ai/xiaomi/mimo-v2.5-pro)

## 20. StepFun (阶跃星辰) Step Plan

| 티어 | 월 가격 | 월 크레딧 | 근사 USD |
|---|---|---|---|
| Flash Mini | ¥49 | 400M | ≈$7 |
| Flash Plus | ¥99 | 1,600M | ≈$14 |
| Flash Pro | ¥199 | 8,000M | ≈$28 |
| Flash Max | ¥699 | 40,000M | ≈$97 |

- 환산: **1M Credit = ¥1**
- 크레딧은 월말 소멸, 다음 주기로 이월되지 않음
- 추가 충전 팩: ¥49 / 400M, ¥99 / 1,600M
- 전 티어 동일 고속 추론 — "표준/고속" 구분 없음. 충전 누적액 기준 계단식 속도 제한도 적용하지 않음
- 개발자 커뮤니티 대상 한시 반값 프로모션 진행 (Mini ¥25 등), 갱신 시 정가 복귀
- 포함 모델: step-3.7-flash, step-3.5-flash 계열, stepaudio-2.5(realtime/chat/TTS/ASR), step-image-edit-2, step-router-v1(복잡도 자동 라우팅)
- 지원 툴: OpenClaw, Claude Code, Cline, Trae, Cursor 등

API 참고가 (1M 토큰, 입력/출력)

| 모델 | 가격 |
|---|---|
| Step 3 | $0.57 / $1.42 |
| Step 3.7 Flash | $0.20 / $1.15 |
| Step 3.5 Flash | $0.090 / $0.300 |

출처: [platform.stepfun.com/docs/zh/step-plan/overview](https://platform.stepfun.com/docs/zh/step-plan/overview), [Step Plan](https://platform.stepfun.com/step-plan), [pricepertoken](https://pricepertoken.com/pricing-page/provider/stepfun-ai)

---

## 부록 A. 과금 모델 유형 분류

| 유형 | 해당 제품 | TokenBar 관점 시사점 |
|---|---|---|
| 달러 표시 크레딧 | Cursor, GitHub Copilot, Hermes, Kilo Pass | 남은 금액을 그대로 표시 가능 — 가장 다루기 쉬움 |
| 추상 크레딧(비공개 환산) | Antigravity, Kiro, Alibaba, StepFun, Xiaomi | 잔량은 알아도 "며칠 쓸 수 있나"는 추정 필요 |
| 요청/프롬프트 수 | Z.ai GLM, Alibaba Coding Plan, opencode Go | 창(5h/주/월) 단위 잔여 표시가 자연스러움 |
| 롤링 rate limit(불투명) | Claude, Codex, Factory, MiniMax, Kimi | 다중 윈도우 동시 추적 필요 (5h + 주 + 월) |
| GPU 시간 | Ollama | 토큰 환산 불가 |
| 작업 단위(ACU) | Devin | 시간 기반 |
| 마크업 0 실비 | opencode Zen, Cline, Kilo Gateway | 잔액 = 실제 달러 |

## 부록 B. 5시간 롤링 윈도우 채택 제품

Claude, Codex, Antigravity, Factory, MiniMax, Kimi, Z.ai GLM, Alibaba Coding Plan, Ollama, opencode Go — 사실상 업계 표준으로 굳었다. Factory는 여기에 7일·30일 윈도우를 더한 3중 구조.

## 부록 C. 확인 실패 / 낮은 신뢰도 항목

| 항목 | 상태 |
|---|---|
| ChatGPT 공식 가격 페이지 | openai.com, chatgpt.com 모두 403 — learn.chatgpt.com 문서로 대체 |
| Devin ACU 단가 | 현행 공식 페이지 미표기, $2.25/ACU는 구 Core 플랜 기준 2차 출처 |
| Cline Teams 가격 | 공식 미공개, docs.cline.bot/plan/pricing 404 |
| Kimi Code 티어별 접근 범위 | Moonshot 공식 표기 자체가 일관되지 않음 |
| Nous Portal 가격 | 공식 사이트 429, 2차 출처 3건 교차 확인 |
| Xiaomi MiMo Token Plan 티어 | platform.xiaomimimo.com 렌더링 실패, 2차 출처 기준 |
| Alibaba Token Plan 저가 티어 | $6/$18/$68 주장과 공식 $30/$100/$200 불일치 |
| Antigravity 크레딧 → 토큰 환산 | Google 미공개 |
| Factory 토큰 포함량 | 공식 문서 미기재 |
