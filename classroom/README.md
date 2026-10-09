# Classroom view · 교육장 뷰

One wall-screen page for an instructor: every account Tokenalytics is polling, one tile each, worst window first.
강사용 한 화면: Tokenalytics가 폴링 중인 모든 계정을 타일 하나씩, 가장 급한 창부터.

```
python3 -m http.server 8000          # from the repo root
open http://localhost:8000/classroom/index.html            # reads ../secrets/status.json
open http://localhost:8000/classroom/index.html?src=/classroom/fixtures/status.sample.json   # demo data
```
- Sort: exhausted (incl. `rate_limited`/`exceeded`, used ≥ 100 %, or `state.quota == "exhausted"`) → soonest projected exhaust → highest used %. Stale windows are greyed.
- Emails are masked (`tr***@domain`); add `?unmask=1` to show them. Press `f` for fullscreen.
- Reads only the `src` it is given, every 15 s. No build step, no dependencies, app untouched.
- Tests: `python3 -m unittest fixtures/test_keys.py` · `node fixtures/test_sort.js` · `python3 fixtures/screenshot.py` (needs playwright).
