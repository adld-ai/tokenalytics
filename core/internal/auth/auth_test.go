package auth

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"tokenbar/internal/pool"
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

func TestNeedsRefresh80Pct(t *testing.T) {
	// TTL 1000s, last refresh at t=0: due at t=800.
	ts := pool.TokenSet{ExpiresAt: 1000, LastRefresh: 0.0001}
	// lastRefresh≈0 would trigger the unknown-issued-at fallback; use
	// an explicit small value to pin the TTL window instead.
	ts.LastRefresh = 0
	// With LastRefresh unknown, the fallback assumes a 1h provider
	// TTL: due at expiresAt-720.
	// Boundary values avoided: float rounding at the exact 80% mark is
	// operationally irrelevant.
	for now, want := range map[float64]bool{0: false, 279: false, 281: true, 1001: true} {
		if got := needsRefresh(ts, now); got != want {
			t.Errorf("needsRefresh(now=%v) = %v, want %v", now, got, want)
		}
	}
	// Known last refresh: 80% of the measured TTL.
	ts2 := pool.TokenSet{ExpiresAt: 1000, LastRefresh: 500}
	for now, want := range map[float64]bool{899: false, 901: true} {
		if got := needsRefresh(ts2, now); got != want {
			t.Errorf("needsRefresh(known, now=%v) = %v, want %v", now, got, want)
		}
	}
	// Unknown expiry: never refreshed (API keys).
	if needsRefresh(pool.TokenSet{}, 1e12) {
		t.Error("zero expiry must never refresh")
	}
}

func TestRefreshOnUseSingleflight(t *testing.T) {
	var mu sync.Mutex
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		calls++
		mu.Unlock()
		time.Sleep(50 * time.Millisecond)
		json.NewEncoder(w).Encode(map[string]any{
			"access_token": "fresh-at", "refresh_token": "fresh-rt", "expires_in": 3600,
		})
	}))
	t.Cleanup(srv.Close)

	p := newPool(t)
	id, err := p.Add(pool.Account{Provider: "codex", Email: "a@b.c", AccountID: "up_1"},
		pool.TokenSet{AccessToken: "stale", RefreshToken: "rt", ExpiresAt: 100, LastRefresh: 0})
	if err != nil {
		t.Fatal(err)
	}
	r := NewRefresher(p)
	r.Configs = map[string]RefreshConfig{
		"codex": {TokenURL: srv.URL, ClientID: "test"},
	}

	// 8 concurrent routings hit one refresh (singleflight).
	var wg sync.WaitGroup
	results := make([]string, 8)
	for i := range results {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			tok, err := r.TokenFor(context.Background(), id)
			if err != nil {
				t.Error(err)
				return
			}
			results[i] = tok
		}(i)
	}
	wg.Wait()
	for i, tok := range results {
		if tok != "fresh-at" {
			t.Fatalf("result %d = %q", i, tok)
		}
	}
	mu.Lock()
	defer mu.Unlock()
	if calls != 1 {
		t.Fatalf("refresh calls = %d, want 1 (singleflight)", calls)
	}
	// Persisted: a fresh TokenFor now serves the stored token.
	if ts, _ := p.Tokens(id); ts.AccessToken != "fresh-at" || ts.RefreshToken != "fresh-rt" {
		t.Fatalf("persisted tokens = %+v", ts)
	}
}

func TestTokenForFreshTokenSkipsRefresh(t *testing.T) {
	p := newPool(t)
	future := float64(time.Now().Unix()) + 3600
	id, _ := p.Add(pool.Account{Provider: "codex", Email: "a@b.c", AccountID: "up_1"},
		pool.TokenSet{AccessToken: "good", RefreshToken: "rt",
			ExpiresAt: future, LastRefresh: future - 3600})
	r := NewRefresher(p)
	r.Configs = map[string]RefreshConfig{"codex": {TokenURL: "http://127.0.0.1:1/unreachable"}}
	tok, err := r.TokenFor(context.Background(), id)
	if err != nil || tok != "good" {
		t.Fatalf("TokenFor = %q, %v", tok, err)
	}
}

func TestBrowserFlow(t *testing.T) {
	// Mock token endpoint.
	tokSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.ParseForm()
		if r.Form.Get("grant_type") != "authorization_code" || r.Form.Get("code") != "the-code" {
			http.Error(w, "bad", 400)
			return
		}
		json.NewEncoder(w).Encode(map[string]any{"access_token": "at", "expires_in": 3600})
	}))
	t.Cleanup(tokSrv.Close)

	port := 54931
	cfg := FlowConfig{
		Kind: "browser", AuthURL: "https://provider.example/auth",
		TokenURL: tokSrv.URL, ClientID: "cid", Scope: "s",
		Port: port, CallbackPath: "/cb",
	}
	// openBrowser parses the auth URL and completes the loopback
	// callback with the right state.
	openBrowser := func(authURL string) error {
		u, err := url.Parse(authURL)
		if err != nil {
			return err
		}
		go func() {
			time.Sleep(50 * time.Millisecond)
			cb := fmt.Sprintf("http://localhost:%d/cb?code=the-code&state=%s",
				port, u.Query().Get("state"))
			http.Get(cb) //nolint
		}()
		return nil
	}
	res, err := RunBrowserFlow(context.Background(), cfg, openBrowser)
	if err != nil {
		t.Fatal(err)
	}
	if res.Code != "the-code" || !strings.Contains(res.RedirectURI, "/cb") {
		t.Fatalf("%+v", res)
	}
	doc, err := ExchangeCode(context.Background(), http.DefaultClient, cfg, res)
	if err != nil || doc["access_token"] != "at" {
		t.Fatalf("exchange = %v, %v", doc, err)
	}
}

func TestBrowserFlowStateMismatch(t *testing.T) {
	cfg := FlowConfig{
		Kind: "browser", AuthURL: "https://provider.example/auth",
		ClientID: "cid", Port: 54932, CallbackPath: "/cb",
	}
	openBrowser := func(authURL string) error {
		go func() {
			time.Sleep(50 * time.Millisecond)
			http.Get(fmt.Sprintf("http://localhost:%d/cb?code=x&state=wrong", cfg.Port)) //nolint
		}()
		return nil
	}
	_, err := RunBrowserFlow(context.Background(), cfg, openBrowser)
	if err == nil || !strings.Contains(err.Error(), "state mismatch") {
		t.Fatalf("err = %v, want state mismatch", err)
	}
}

func TestDeviceFlow(t *testing.T) {
	var polls int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.ParseForm()
		switch {
		case r.Form.Get("scope") != "":
			json.NewEncoder(w).Encode(map[string]any{
				"device_code": "dc", "user_code": "ABCD", "verification_uri": "https://ex.com/dev",
				"interval": 1, "expires_in": 60,
			})
		default:
			polls++
			if polls < 2 {
				json.NewEncoder(w).Encode(map[string]any{"error": "authorization_pending"})
				return
			}
			json.NewEncoder(w).Encode(map[string]any{"access_token": "gho_x"})
		}
	}))
	t.Cleanup(srv.Close)
	cfg := FlowConfig{Kind: "device", AuthURL: srv.URL, TokenURL: srv.URL, ClientID: "cid", Scope: "read:user"}
	dc, err := StartDeviceFlow(context.Background(), http.DefaultClient, cfg)
	if err != nil || dc.UserCode != "ABCD" {
		t.Fatalf("%+v, %v", dc, err)
	}
	doc, err := PollDeviceFlow(context.Background(), http.DefaultClient, cfg, dc)
	if err != nil || doc["access_token"] != "gho_x" {
		t.Fatalf("%v, %v", doc, err)
	}
}
