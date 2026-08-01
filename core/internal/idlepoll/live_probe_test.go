package idlepoll

import (
	"context"
	"os"
	"testing"

	"tokenbar/internal/auth"
	"tokenbar/internal/pool"
	"tokenbar/internal/state"
)

// TestLiveCodexProbeSpotCheck is the M2 harvest-vs-reality spot check.
// It runs only when TOKENBAR_LIVE_V1DB points at the real v1 pool.db:
//
//	TOKENBAR_LIVE_V1DB=~/solo/token-bar/secrets/pool.db \
//	  go test ./internal/idlepoll -run TestLiveCodexProbeSpotCheck -v
//
// It imports codex accounts into a scratch v2 DB and probes wham/usage
// through the ported refresh + probe path, printing used_pct per
// account for comparison against the v1 poller's status.json.
func TestLiveCodexProbeSpotCheck(t *testing.T) {
	v1 := os.Getenv("TOKENBAR_LIVE_V1DB")
	if v1 == "" {
		t.Skip("set TOKENBAR_LIVE_V1DB to run the live spot check")
	}
	st, err := state.Init(t.TempDir() + "/v2.db")
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()
	p := pool.New(st, pool.PlainVault{})
	if _, err := p.ImportV1DB(v1, false, os.Stderr); err != nil {
		t.Fatal(err)
	}
	refresher := auth.NewRefresher(p)
	probe := &CodexProbe{Pool: p, Refresher: refresher}
	accts, err := p.List()
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("imported accounts: %d", len(accts))
	for _, a := range accts {
		if a.Provider != "codex" {
			continue
		}
		snap, err := probe.Probe(context.Background(), a)
		if err != nil {
			t.Logf("account=%d %s: probe error: %v", a.ID, a.Email, err)
			continue
		}
		t.Logf("account=%d %s: windows=%d", a.ID, a.Email, len(snap.Windows))
		for _, w := range snap.Windows {
			t.Logf("account=%d %s window=%s used_pct=%.1f", a.ID, a.Email, w.Kind, *w.UsedPct)
		}
	}
}
