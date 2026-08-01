package harvest

import (
	"net/http"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"tokenbar/internal/pool"
	"tokenbar/internal/quota"
	"tokenbar/internal/state"
)

func TestFromHeadersAnthropic(t *testing.T) {
	h := http.Header{}
	h.Set("Anthropic-Ratelimit-Unified-5h-Utilization", "0.41")
	h.Set("Anthropic-Ratelimit-Unified-5h-Reset", "2026-08-01T20:00:00Z")
	o := FromHeaders(7, h)
	if len(o.Windows) != 1 {
		t.Fatalf("windows = %+v", o.Windows)
	}
	w := o.Windows[0]
	if w.Kind != "5h" || *w.UsedPct != 41 {
		t.Fatalf("%+v", w)
	}
	if w.ResetAt == nil {
		t.Fatal("reset not parsed")
	}
}

func TestTeeParsesResponseCompletedUsage(t *testing.T) {
	sink := &captureSink{}
	stream := strings.NewReader(
		"event: response.created\ndata: {\"type\":\"response.created\"}\n\n" +
			"event: response.output_text.delta\ndata: {\"type\":\"response.output_text.delta\",\"delta\":\"hi\"}\n\n" +
			"event: response.completed\ndata: {\"type\":\"response.completed\",\"response\":{\"usage\":{\"input_tokens\":120,\"output_tokens\":30}}}\n\n")
	tee := TeeBody(9, stream, sink)
	buf := make([]byte, 64)
	for {
		_, err := tee.Read(buf)
		if err != nil {
			break
		}
	}
	tee.Close()
	if sink.obs.Usage == nil || sink.obs.Usage.InputTokens != 120 || sink.obs.Usage.OutputTokens != 30 {
		t.Fatalf("usage = %+v", sink.obs.Usage)
	}
	if sink.obs.AccountID != 9 {
		t.Fatalf("account = %d", sink.obs.AccountID)
	}
}

func TestTeeSplitAcrossChunks(t *testing.T) {
	sink := &captureSink{}
	full := "data: {\"type\":\"response.completed\",\"response\":{\"usage\":{\"input_tokens\":5,\"output_tokens\":1}}}\n\n"
	stream := &chunkedReader{data: []byte(full), chunk: 7}
	tee := TeeBody(1, stream, sink)
	buf := make([]byte, 16)
	for {
		if _, err := tee.Read(buf); err != nil {
			break
		}
	}
	tee.Close()
	if sink.obs.Usage == nil || sink.obs.Usage.InputTokens != 5 {
		t.Fatalf("usage = %+v", sink.obs.Usage)
	}
}

type chunkedReader struct {
	data   []byte
	chunk  int
	offset int
}

func (c *chunkedReader) Read(b []byte) (int, error) {
	if c.offset >= len(c.data) {
		return 0, errEOF
	}
	n := min(c.chunk, len(c.data)-c.offset)
	copy(b, c.data[c.offset:c.offset+n])
	c.offset += n
	return n, nil
}

var errEOF = errorString("EOF")

type errorString string

func (e errorString) Error() string { return string(e) }

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

type captureSink struct{ obs Observation }

func (c *captureSink) Observe(o Observation) { c.obs = o }

func newEngine(t *testing.T) (*Engine, func()) {
	t.Helper()
	st, err := state.Init(filepath.Join(t.TempDir(), "pool.db"))
	if err != nil {
		t.Fatal(err)
	}
	p := pool.New(st, pool.PlainVault{})
	// quota_windows references accounts (FK); seed the ids tests use.
	for i, email := range []string{"a@x.y", "b@x.y", "c@x.y", "d@x.y"} {
		if _, err := p.Add(pool.Account{Provider: "codex", Email: email, AccountID: email},
			pool.TokenSet{AccessToken: "at"}); err != nil {
			t.Fatalf("seed account %d: %v", i, err)
		}
	}
	return NewEngine(st), func() { st.Close() }
}

func TestEngineApplySnapshotStoresWindows(t *testing.T) {
	e, done := newEngine(t)
	defer done()
	reset := float64(time.Now().Unix()) + 18000
	used := 42.0
	snap := quota.Snapshot{
		Ts: float64(time.Now().Unix()), Status: "active",
		Windows: []quota.Window{{Kind: "5h", UsedPct: &used, ResetAt: &reset, WindowS: 18000}},
	}
	e.ApplySnapshot(3, snap)
	ws, err := e.LatestWindows(3)
	if err != nil || len(ws) != 1 {
		t.Fatalf("windows = %+v, %v", ws, err)
	}
	if *ws[0].UsedPct != 42 {
		t.Fatalf("%+v", ws[0])
	}
}

func TestEngineArchivesClosedWindows(t *testing.T) {
	e, done := newEngine(t)
	defer done()
	base := float64(time.Now().Unix())
	mk := func(ts, used, reset float64) quota.Snapshot {
		return quota.Snapshot{Ts: ts, Status: "active", Windows: []quota.Window{
			{Kind: "5h", UsedPct: &used, ResetAt: &reset, WindowS: 18000}}}
	}
	e.ApplySnapshot(4, mk(base, 85, base+300))
	e.ApplySnapshot(4, mk(base+600, 3, base+300+18000))
	rows, err := e.st.Query(
		"SELECT window_kind, reset_cause, final_used_pct FROM window_history WHERE account_id = 4")
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var found bool
	for rows.Next() {
		var kind, cause string
		var pct float64
		rows.Scan(&kind, &cause, &pct)
		if kind == "5h" && cause == "natural" && pct == 85 {
			found = true
		}
	}
	if !found {
		t.Fatal("closed 5h window not archived")
	}
}
