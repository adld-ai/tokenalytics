package routing

import (
	"testing"
	"time"
)

func TestPinDefaultNoFailover(t *testing.T) {
	r := New()
	r.SetAccounts("codex", PolicyPin, 1, []int64{1, 2})

	c, err := r.Pick("codex")
	if err != nil || c.AccountID != 1 {
		t.Fatalf("Pick = %+v, %v; want pinned account 1", c, err)
	}
	// Pin + cooling pinned account = error, never silent failover (S9).
	r.Cooldown(1, "429", time.Minute)
	if _, err := r.Pick("codex"); err == nil {
		t.Fatal("Pick on cooling pinned account must fail (pin never auto-fails over)")
	}
}

func TestFillFirstSkipsCooldown(t *testing.T) {
	r := New()
	r.SetAccounts("codex", PolicyFillFirst, 1, []int64{1, 2, 3})

	r.Cooldown(1, "429", time.Minute)
	c, err := r.Pick("codex")
	if err != nil || c.AccountID != 2 {
		t.Fatalf("Pick = %+v, %v; want 2", c, err)
	}
}

func TestCooldownTTLEviction(t *testing.T) {
	r := New()
	r.SetAccounts("codex", PolicyFillFirst, 1, []int64{1})
	r.Cooldown(1, "429", 50*time.Millisecond)
	if _, err := r.Pick("codex"); err == nil {
		t.Fatal("want cooldown active")
	}
	time.Sleep(60 * time.Millisecond)
	if _, err := r.Pick("codex"); err != nil {
		t.Fatalf("cooldown should have expired: %v", err)
	}
	if len(r.Cooldowns()) != 0 {
		t.Fatal("expired cooldown must be evicted")
	}
}

func TestNextAfterExcludesPrevAndCooling(t *testing.T) {
	r := New()
	r.SetAccounts("codex", PolicyFillFirst, 1, []int64{1, 2, 3})
	r.Cooldown(2, "401", time.Minute)
	c, err := r.NextAfter("codex", 1)
	if err != nil || c.AccountID != 3 {
		t.Fatalf("NextAfter = %+v, %v; want 3", c, err)
	}
}

func TestHardSignalScope(t *testing.T) {
	for _, s := range []int{429, 401, 403} {
		if !HardSignal(s) {
			t.Errorf("%d must be a failover signal (S7)", s)
		}
	}
	for _, s := range []int{200, 400, 404, 409, 500, 502, 503} {
		if HardSignal(s) {
			t.Errorf("%d must NOT be a failover signal (S7)", s)
		}
	}
}

func TestRemoveAccountAtomicSwap(t *testing.T) {
	r := New()
	r.SetAccounts("codex", PolicyPin, 1, []int64{1, 2})
	r.SetAccounts("claude", PolicyPin, 5, []int64{5, 1})
	r.RemoveAccount(1)
	ri := r.Routes()["codex"]
	if ri.Pinned != 0 || len(ri.Candidates) != 1 || ri.Candidates[0] != 2 {
		t.Fatalf("codex route after remove = %+v", ri)
	}
	ri = r.Routes()["claude"]
	if ri.Pinned != 5 || len(ri.Candidates) != 1 || ri.Candidates[0] != 5 {
		t.Fatalf("claude route after remove = %+v", ri)
	}
}
