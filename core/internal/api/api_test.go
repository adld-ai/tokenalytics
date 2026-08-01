package api

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"tokenbar/internal/pool"
	"tokenbar/internal/routing"
	"tokenbar/internal/state"
)

func newTestServer(t *testing.T) (*Server, *httptest.Server) {
	t.Helper()
	st, err := state.Init(filepath.Join(t.TempDir(), "pool.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { st.Close() })
	s := New(pool.New(st, pool.PlainVault{}), routing.New(), "test-admin-token")
	ts := httptest.NewServer(s.Mux)
	t.Cleanup(ts.Close)
	return s, ts
}

func authed(t *testing.T, method, url, body string) *http.Response {
	t.Helper()
	req, err := http.NewRequest(method, url, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer test-admin-token")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return resp
}

func addTestAccount(t *testing.T, ts *httptest.Server, provider, email, acctID string) int64 {
	t.Helper()
	resp := authed(t, "POST", ts.URL+"/api/v1/accounts", fmt.Sprintf(
		`{"provider":%q,"email":%q,"account_id":%q,"access_token":"eyJhbGciOi.fake.jwt","refresh_token":"rt.fake"}`, provider, email, acctID))
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("add %s: status %d", email, resp.StatusCode)
	}
	var p AccountPayload
	json.NewDecoder(resp.Body).Decode(&p)
	return p.ID
}

func TestBearerAuthRequired(t *testing.T) {
	_, ts := newTestServer(t)
	for _, path := range []string{"/api/v1/state", "/api/v1/health"} {
		resp, err := http.Get(ts.URL + path)
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		if resp.StatusCode != http.StatusUnauthorized {
			t.Fatalf("%s without token: %d, want 401 (S14)", path, resp.StatusCode)
		}
	}
}

// tokenPatterns match JWTs, OpenAI-style keys, and refresh tokens.
var tokenPatterns = []*regexp.Regexp{
	regexp.MustCompile(`eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}`),
	regexp.MustCompile(`sk-[A-Za-z0-9_-]{10,}`),
	regexp.MustCompile(`rt\.[A-Za-z0-9_-]{5,}`),
	regexp.MustCompile(`Bearer\s+[A-Za-z0-9._-]{20,}`),
}

func TestPayloadsContainNoTokenMaterial(t *testing.T) {
	_, ts := newTestServer(t)
	addTestAccount(t, ts, "codex", "a@b.c", "up_1")

	resp := authed(t, "GET", ts.URL+"/api/v1/state", "")
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("state: %d", resp.StatusCode)
	}
	var buf strings.Builder
	var payload StatePayload
	dec := json.NewDecoder(resp.Body)
	if err := dec.Decode(&payload); err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(payload)
	buf.Write(raw)
	for _, re := range tokenPatterns {
		if re.MatchString(buf.String()) {
			t.Fatalf("S15 violation: /state payload matches %s", re)
		}
	}
}

func TestDeleteReflectedInStateUnder50ms(t *testing.T) {
	_, ts := newTestServer(t)
	id := addTestAccount(t, ts, "codex", "a@b.c", "up_1")

	start := time.Now()
	resp := authed(t, "DELETE", fmt.Sprintf("%s/api/v1/accounts/%d", ts.URL, id), "")
	resp.Body.Close()
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("delete: %d", resp.StatusCode)
	}
	resp = authed(t, "GET", ts.URL+"/api/v1/state", "")
	defer resp.Body.Close()
	var payload StatePayload
	json.NewDecoder(resp.Body).Decode(&payload)
	elapsed := time.Since(start)
	for _, a := range payload.Accounts {
		if a.ID == id {
			t.Fatal("deleted account still in /state")
		}
	}
	if elapsed > 50*time.Millisecond {
		t.Fatalf("delete→state propagation took %v (> 50 ms)", elapsed)
	}
	t.Logf("delete→state propagation: %v", elapsed)
}

// TestDeleteRacingStateRead codifies the v1 delete-resurrection race:
// concurrent DELETEs and /state reads can never observe the account
// after its 204, because both are serialized behind one writer.
func TestDeleteRacingStateRead(t *testing.T) {
	_, ts := newTestServer(t)
	id := addTestAccount(t, ts, "codex", "a@b.c", "up_1")

	resp := authed(t, "DELETE", fmt.Sprintf("%s/api/v1/accounts/%d", ts.URL, id), "")
	resp.Body.Close()

	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 10; j++ {
				r := authed(t, "GET", ts.URL+"/api/v1/state", "")
				var p StatePayload
				json.NewDecoder(r.Body).Decode(&p)
				r.Body.Close()
				for _, a := range p.Accounts {
					if a.ID == id {
						t.Error("resurrection: deleted account visible in /state")
					}
				}
			}
		}()
	}
	wg.Wait()
}

// TestNoStaleListWriteAPI documents the v1 stale-list rewrite class:
// the API exposes no endpoint that accepts a full account list, so a
// client holding a pre-delete snapshot cannot write it back.
func TestNoStaleListWriteAPI(t *testing.T) {
	_, ts := newTestServer(t)
	for _, method := range []string{"PUT", "PATCH"} {
		resp := authed(t, method, ts.URL+"/api/v1/accounts", `[{"id":1}]`)
		resp.Body.Close()
		if resp.StatusCode != http.StatusMethodNotAllowed {
			t.Fatalf("%s /accounts: %d, want 405 (no list-write surface)", method, resp.StatusCode)
		}
	}
}

func TestPinEndpoint(t *testing.T) {
	s, ts := newTestServer(t)
	a := addTestAccount(t, ts, "codex", "a@b.c", "up_1")
	b := addTestAccount(t, ts, "codex", "c@d.e", "up_2")
	s.RebuildRoutes()

	resp := authed(t, "POST", ts.URL+"/api/v1/routing/codex/pin", fmt.Sprintf(`{"account_id":%d}`, b))
	resp.Body.Close()
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("pin: %d", resp.StatusCode)
	}
	if ri := s.Router.Routes()["codex"]; ri.Pinned != b {
		t.Fatalf("pinned = %d, want %d", ri.Pinned, b)
	}
	// Pinning a deleted/unknown account must fail.
	resp = authed(t, "POST", ts.URL+"/api/v1/routing/codex/pin", `{"account_id":9999}`)
	resp.Body.Close()
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("pin unknown: %d, want 409", resp.StatusCode)
	}
	_ = a
}
