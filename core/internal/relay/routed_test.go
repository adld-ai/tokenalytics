package relay

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
)

type fakeSource struct {
	mu        sync.Mutex
	creds     []RoutedCred
	failovers bool
	cooled    []int64
}

func (f *fakeSource) Pick(context.Context) (RoutedCred, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if len(f.creds) == 0 {
		return RoutedCred{}, errors.New("empty")
	}
	return f.creds[0], nil
}

func (f *fakeSource) Next(_ context.Context, prev RoutedCred) (RoutedCred, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	for _, c := range f.creds {
		if c.AccountID != prev.AccountID {
			return c, nil
		}
	}
	return RoutedCred{}, errors.New("no other")
}

func (f *fakeSource) ReportHardFailure(prev RoutedCred, status int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.cooled = append(f.cooled, prev.AccountID)
}

func (f *fakeSource) FailoverAllowed() bool { return f.failovers }

// upstreamScript responds per-account: account 1 gets a hard 429,
// account 2 streams fine.
func upstreamScript(t *testing.T) *httptest.Server {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body)
		r.Body.Close()
		auth := r.Header.Get("Authorization")
		if strings.Contains(auth, "tok-1") {
			w.WriteHeader(http.StatusTooManyRequests)
			fmt.Fprint(w, `{"error":"quota"}`)
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprint(w, "event: done\ndata: ok\n\n")
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestRoutedFailoverOnHardSignal(t *testing.T) {
	up := upstreamScript(t)
	u, _ := url.Parse(up.URL)
	src := &fakeSource{failovers: true, creds: []RoutedCred{
		{AccountID: 1, Token: "tok-1"},
		{AccountID: 2, Token: "tok-2"},
	}}
	r := NewRouted(u, "/v1", src)

	req := httptest.NewRequest("POST", "/v1/responses",
		strings.NewReader(`{"model":"gpt-5.5","input":"hi"}`))
	req.ContentLength = int64(len(`{"model":"gpt-5.5","input":"hi"}`))
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status %d, want failover to account 2's 200", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "event: done") {
		t.Fatalf("body %q, want account 2 stream", rec.Body.String())
	}
	if len(src.cooled) != 1 || src.cooled[0] != 1 {
		t.Fatalf("cooldowns = %v, want [1] (S10)", src.cooled)
	}
}

func TestRoutedNoFailoverWithContinuityMarker(t *testing.T) {
	up := upstreamScript(t)
	u, _ := url.Parse(up.URL)
	src := &fakeSource{failovers: true, creds: []RoutedCred{
		{AccountID: 1, Token: "tok-1"},
		{AccountID: 2, Token: "tok-2"},
	}}
	r := NewRouted(u, "/v1", src)

	body := `{"model":"gpt-5.5","previous_response_id":"resp_123","input":"hi"}`
	req := httptest.NewRequest("POST", "/v1/responses", strings.NewReader(body))
	req.ContentLength = int64(len(body))
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)

	// S19: the upstream 429 must come back verbatim, no retry.
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("status %d, want verbatim 429 (S19)", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "quota") {
		t.Fatalf("body %q, want upstream error verbatim", rec.Body.String())
	}
}

func TestRoutedNoFailoverWhenPolicyPin(t *testing.T) {
	up := upstreamScript(t)
	u, _ := url.Parse(up.URL)
	src := &fakeSource{failovers: false, creds: []RoutedCred{
		{AccountID: 1, Token: "tok-1"},
		{AccountID: 2, Token: "tok-2"},
	}}
	r := NewRouted(u, "/v1", src)

	body := `{"model":"gpt-5.5","input":"hi"}`
	req := httptest.NewRequest("POST", "/v1/responses", strings.NewReader(body))
	req.ContentLength = int64(len(body))
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)

	// S9: pin policy = manual only; the 429 comes back verbatim.
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("status %d, want verbatim 429 under pin (S9)", rec.Code)
	}
	if len(src.cooled) != 1 {
		t.Fatalf("hard failure must still enter cooldown, got %v", src.cooled)
	}
}
