package idlepoll

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"tokenbar/internal/auth"
	"tokenbar/internal/harvest"
	"tokenbar/internal/pool"
	"tokenbar/internal/quota"
	"tokenbar/internal/state"
)

func newPool(t *testing.T) *pool.Pool {
	t.Helper()
	st, err := state.Init(filepath.Join(t.TempDir(), "pool.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { st.Close() })
	return pool.New(st, pool.PlainVault{})
}

// newPoolWithEngine shares one store between pool and engine, as in
// production.
func newPoolWithEngine(t *testing.T) (*pool.Pool, *harvest.Engine) {
	t.Helper()
	st, err := state.Init(filepath.Join(t.TempDir(), "pool.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { st.Close() })
	return pool.New(st, pool.PlainVault{}), harvest.NewEngine(st)
}

type fakeProber struct {
	mu         sync.Mutex
	calls      []int64
	concurrent map[string]int
	maxConc    map[string]int
	fail429    int // first N calls return 429
	delay      time.Duration
}

func newFakeProber() *fakeProber {
	return &fakeProber{concurrent: map[string]int{}, maxConc: map[string]int{}, delay: 20 * time.Millisecond}
}

func (f *fakeProber) Probe(ctx context.Context, a pool.Account) (quota.Snapshot, error) {
	f.mu.Lock()
	f.calls = append(f.calls, a.ID)
	f.concurrent[a.Provider]++
	if f.concurrent[a.Provider] > f.maxConc[a.Provider] {
		f.maxConc[a.Provider] = f.concurrent[a.Provider]
	}
	n429 := f.fail429
	if f.fail429 > 0 {
		f.fail429--
	}
	f.mu.Unlock()
	time.Sleep(f.delay)
	f.mu.Lock()
	f.concurrent[a.Provider]--
	f.mu.Unlock()
	if n429 > 0 {
		return quota.Snapshot{}, RateLimitError{Provider: a.Provider}
	}
	used := 10.0
	return quota.Snapshot{Ts: float64(time.Now().Unix()), Status: "active",
		Windows: []quota.Window{{Kind: "5h", UsedPct: &used}}}, nil
}

func (f *fakeProber) callCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.calls)
}

func TestSchedulerJitterSerializationBackoff(t *testing.T) {
	p, engine := newPoolWithEngine(t)

	var ids []int64
	for i, prov := range []string{"codex", "codex", "claude"} {
		email := fmt.Sprintf("%s-%d@x.y", prov, i)
		id, err := p.Add(pool.Account{Provider: prov, Email: email, AccountID: email},
			pool.TokenSet{AccessToken: "at"})
		if err != nil {
			t.Fatal(err)
		}
		ids = append(ids, id)
	}
	fp := newFakeProber()
	fp.fail429 = 2
	var logBuf bytes.Buffer
	s := New(p, engine, map[string]Prober{"codex": fp, "claude": fp},
		log.New(&logBuf, "", 0))
	s.Interval = 120 * time.Millisecond
	s.jitter = func() float64 { return 1.0 }

	ctx, cancel := context.WithTimeout(context.Background(), 900*time.Millisecond)
	defer cancel()
	s.Run(ctx)

	if fp.maxConc["codex"] > 1 {
		t.Fatalf("codex probes ran concurrently: max=%d (S22 serialization)", fp.maxConc["codex"])
	}
	if fp.callCount() == 0 {
		t.Fatal("no probes ran")
	}
	out := logBuf.String()
	if !bytes.Contains(logBuf.Bytes(), []byte("backoff=1")) {
		t.Fatalf("429 backoff not logged:\n%s", out)
	}
	t.Logf("scheduler log excerpt:\n%s", out)
}

func TestSchedulerSkipsHarvestCovered(t *testing.T) {
	p, engine := newPoolWithEngine(t)
	id, _ := p.Add(pool.Account{Provider: "codex", Email: "a@x.y", AccountID: "up"},
		pool.TokenSet{AccessToken: "at"})
	// Mark the account as recently harvested.
	engine.Observe(harvest.Observation{AccountID: id, At: time.Now()})

	fp := newFakeProber()
	var logBuf bytes.Buffer
	s := New(p, engine, map[string]Prober{"codex": fp}, log.New(&logBuf, "", 0))
	s.Interval = 200 * time.Millisecond
	s.jitter = func() float64 { return 1.0 }
	// Single account: first due fires immediately; the skip reschedules
	// at +200ms, beyond the 120ms run window, so no probe may run.
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Millisecond)
	defer cancel()
	s.Run(ctx)

	if fp.callCount() != 0 {
		t.Fatalf("harvest-covered account was polled %d times (S22 skip)", fp.callCount())
	}
	if !bytes.Contains(logBuf.Bytes(), []byte("skip account")) {
		t.Fatalf("skip not logged:\n%s", logBuf.String())
	}
}

func TestCodexProbeParsesWhamUsage(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer at" {
			http.Error(w, "bad auth", 401)
			return
		}
		// Top-level shape, matching the live wham/usage endpoint.
		json.NewEncoder(w).Encode(map[string]any{
			"plan_type": "pro",
			"rate_limit": map[string]any{
				"primary_window":   map[string]any{"used_percent": 55.0, "reset_after_seconds": 3600.0, "limit_window_seconds": 18000},
				"secondary_window": map[string]any{"used_percent": 20.0, "reset_after_seconds": 86400.0, "limit_window_seconds": 604800},
			},
			"rate_limit_reset_credits": map[string]any{"available_count": 2},
		})
	}))
	t.Cleanup(srv.Close)

	p := newPool(t)
	id, _ := p.Add(pool.Account{Provider: "codex", Email: "a@x.y", AccountID: "up"},
		pool.TokenSet{AccessToken: "at", ExpiresAt: float64(time.Now().Unix()) + 3600,
			LastRefresh: float64(time.Now().Unix())})
	a, _ := p.Get(id)
	probe := &CodexProbe{Pool: p, Refresher: auth.NewRefresher(p), BaseURL: srv.URL}
	snap, err := probe.Probe(context.Background(), a)
	if err != nil {
		t.Fatal(err)
	}
	if len(snap.Windows) != 2 {
		t.Fatalf("windows = %+v", snap.Windows)
	}
	if snap.Windows[0].Kind != "5h" || *snap.Windows[0].UsedPct != 55 {
		t.Fatalf("primary = %+v", snap.Windows[0])
	}
	if snap.Windows[1].Kind != "weekly" {
		t.Fatalf("secondary = %+v", snap.Windows[1])
	}
	if snap.BankedResets == nil || *snap.BankedResets != 2 {
		t.Fatalf("banked = %v", snap.BankedResets)
	}
}

func TestCodexProbe429(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "slow down", http.StatusTooManyRequests)
	}))
	t.Cleanup(srv.Close)
	p := newPool(t)
	id, _ := p.Add(pool.Account{Provider: "codex", Email: "a@x.y", AccountID: "up"},
		pool.TokenSet{AccessToken: "at"})
	a, _ := p.Get(id)
	probe := &CodexProbe{Pool: p, Refresher: auth.NewRefresher(p), BaseURL: srv.URL}
	_, err := probe.Probe(context.Background(), a)
	if _, ok := err.(RateLimitError); !ok {
		t.Fatalf("err = %v, want RateLimitError", err)
	}
}
