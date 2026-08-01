package relay

import (
	"bufio"
	"bytes"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	"go.uber.org/goleak"
)

func TestMain(m *testing.M) {
	goleak.VerifyTestMain(m)
}

// sseFixture is a recorded codex-style Responses stream: keepalive,
// deltas, and a terminal [DONE]-style event.
var sseFixture = []string{
	": keepalive\n\n",
	"event: response.created\ndata: {\"type\":\"response.created\",\"response\":{\"id\":\"resp_1\"}}\n\n",
	"event: response.output_text.delta\ndata: {\"type\":\"response.output_text.delta\",\"delta\":\"Hello\"}\n\n",
	"event: response.output_text.delta\ndata: {\"type\":\"response.output_text.delta\",\"delta\":\", world\"}\n\n",
	"event: response.completed\ndata: {\"type\":\"response.completed\",\"response\":{\"id\":\"resp_1\",\"usage\":{\"input_tokens\":12,\"output_tokens\":3}}}\n\n",
}

func fixtureBody() []byte {
	var b bytes.Buffer
	for _, c := range sseFixture {
		b.WriteString(c)
	}
	return b.Bytes()
}

// upstream is a recorded-traffic provider stand-in. It captures the
// headers it received and can stream the fixture chunk-by-chunk.
type upstream struct {
	srv *httptest.Server

	mu     sync.Mutex
	lastH  http.Header
	cancel chan struct{}
}

func newUpstream(t *testing.T) *upstream {
	t.Helper()
	u := &upstream{cancel: make(chan struct{})}
	u.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		u.mu.Lock()
		u.lastH = r.Header.Clone()
		u.mu.Unlock()
		io.Copy(io.Discard, r.Body)
		r.Body.Close()
		switch {
		case strings.HasPrefix(r.URL.Path, "/slow"):
			// Never-ending stream: lets the abort test observe that a
			// downstream disconnect cancels the upstream handler.
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(http.StatusOK)
			f, _ := w.(http.Flusher)
			for i := 0; ; i++ {
				select {
				case <-r.Context().Done():
					close(u.cancel)
					return
				case <-time.After(20 * time.Millisecond):
				}
				fmt.Fprintf(w, "event: tick\ndata: %d\n\n", i)
				if f != nil {
					f.Flush()
				}
			}
		case r.URL.Path == "/responses" && r.URL.Query().Get("stream") == "false":
			w.Header().Set("Content-Type", "application/json")
			w.Write([]byte(`{"id":"resp_1","status":"completed"}`))
		case strings.HasPrefix(r.URL.Path, "/responses"):
			w.Header().Set("Content-Type", "text/event-stream")
			w.Header().Set("Cache-Control", "no-cache")
			w.WriteHeader(http.StatusOK)
			f, _ := w.(http.Flusher)
			for _, c := range sseFixture {
				select {
				case <-r.Context().Done():
					close(u.cancel)
					return
				default:
				}
				fmt.Fprint(w, c)
				if f != nil {
					f.Flush()
				}
				time.Sleep(10 * time.Millisecond)
			}
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(u.srv.Close)
	return u
}

func newTestRelay(t *testing.T, u *upstream) *httptest.Server {
	t.Helper()
	base, err := url.Parse(u.srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(New(Config{
		Upstream:    base,
		StripPrefix: "/v1",
		Token:       func() string { return "routed-token" },
	}))
	t.Cleanup(srv.Close)
	return srv
}

// hopByHopExclusions is the explicit list of headers excluded from the
// byte-diff, per the phase-M0 exit criteria: hop-by-hop headers plus
// per-response Date, which legitimately differs between two fetches.
var hopByHopExclusions = []string{
	"Connection", "Keep-Alive", "Proxy-Authenticate", "Proxy-Authorization",
	"TE", "Trailer", "Transfer-Encoding", "Upgrade", "Date",
}

func comparableHeaders(h http.Header) http.Header {
	c := h.Clone()
	for _, k := range hopByHopExclusions {
		c.Del(k)
	}
	return c
}

func TestVerbatimHeadersAndAuthInjection(t *testing.T) {
	u := newUpstream(t)
	r := newTestRelay(t, u)

	req, _ := http.NewRequest("POST", r.URL+"/v1/responses?stream=false",
		strings.NewReader(`{"model":"gpt-5","input":"hi"}`))
	req.Header.Set("Authorization", "Bearer client-sent-token")
	req.Header.Set("User-Agent", "codex_cli_rs/0.146.0 (Mac OS 26.0.0; arm64)")
	req.Header.Set("Originator", "codex_cli_rs")
	req.Header.Set("Chatgpt-Account-Id", "acct_123")
	req.Header.Set("Session_id", "sess_abc")
	req.Header.Set("Openai-Beta", "responses=experimental")
	req.Header.Set("X-Custom-Casing", "Preserved-Value")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status %d", resp.StatusCode)
	}

	u.mu.Lock()
	got := u.lastH
	u.mu.Unlock()

	for _, h := range []string{"X-Forwarded-For", "Via", "Forwarded"} {
		if v := got.Get(h); v != "" {
			t.Errorf("S17 violation: upstream received %s: %q", h, v)
		}
	}
	if got.Get("Authorization") != "Bearer routed-token" {
		t.Errorf("Authorization = %q, want replaced routed token", got.Get("Authorization"))
	}
	for k, want := range map[string]string{
		"User-Agent":         "codex_cli_rs/0.146.0 (Mac OS 26.0.0; arm64)",
		"Originator":         "codex_cli_rs",
		"Chatgpt-Account-Id": "acct_123",
		"Session_id":         "sess_abc",
		"Openai-Beta":        "responses=experimental",
		"X-Custom-Casing":    "Preserved-Value",
	} {
		if got.Get(k) != want {
			t.Errorf("header %s = %q, want %q (must pass verbatim)", k, got.Get(k), want)
		}
	}
}

func TestStreamIntegrityByteDiff(t *testing.T) {
	u := newUpstream(t)
	r := newTestRelay(t, u)
	want := fixtureBody()

	fetch := func(base string) ([]byte, http.Header) {
		req, _ := http.NewRequest("POST", base+"/responses?stream=true",
			strings.NewReader(`{"model":"gpt-5","stream":true}`))
		resp, err := (&http.Client{}).Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		b, err := io.ReadAll(resp.Body)
		if err != nil {
			t.Fatal(err)
		}
		return b, resp.Header
	}

	direct, directH := fetch(u.srv.URL)
	proxied, proxiedH := fetch(r.URL + "/v1")

	if !bytes.Equal(direct, want) {
		t.Fatalf("fixture mismatch vs upstream: got %d bytes want %d", len(direct), len(want))
	}
	if !bytes.Equal(proxied, direct) {
		t.Fatalf("byte-diff: proxied stream differs from direct\nproxied: %q\ndirect:  %q", proxied, direct)
	}
	dh, ph := comparableHeaders(directH), comparableHeaders(proxiedH)
	for k := range dh {
		if !strings.EqualFold(dh.Get(k), ph.Get(k)) {
			t.Errorf("response header %s differs: direct %q proxied %q", k, dh.Get(k), ph.Get(k))
		}
	}
}

func TestAbortMidStreamCancelsUpstream(t *testing.T) {
	u := newUpstream(t)
	r := newTestRelay(t, u)

	req, _ := http.NewRequest("POST", r.URL+"/v1/slow",
		strings.NewReader(`{"model":"gpt-5","stream":true}`))
	resp, err := (&http.Client{}).Do(req)
	if err != nil {
		t.Fatal(err)
	}
	br := bufio.NewReader(resp.Body)
	if _, err := br.ReadString('\n'); err != nil {
		t.Fatalf("first chunk: %v", err)
	}
	resp.Body.Close() // CLI walked away mid-stream

	select {
	case <-u.cancel:
	case <-time.After(2 * time.Second):
		t.Fatal("upstream handler did not observe cancellation within 2s")
	}
}

func TestFlushPerChunkNoBuffering(t *testing.T) {
	u := newUpstream(t)
	r := newTestRelay(t, u)

	start := time.Now()
	req, _ := http.NewRequest("POST", r.URL+"/v1/responses?stream=true",
		strings.NewReader(`{"model":"gpt-5","stream":true}`))
	resp, err := (&http.Client{}).Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	br := bufio.NewReader(resp.Body)
	if _, err := br.ReadString('\n'); err != nil {
		t.Fatalf("first chunk: %v", err)
	}
	first := time.Since(start)
	// The fixture sleeps 10ms between 5 chunks; a buffering relay would
	// deliver the first line only after ~40ms+.
	if first > 40*time.Millisecond {
		t.Fatalf("first chunk took %v; relay appears to buffer (S5)", first)
	}
}
