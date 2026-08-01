package pool

import (
	"bytes"
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"tokenbar/internal/state"
)

func newStore(t *testing.T) *state.Store {
	t.Helper()
	st, err := state.Init(filepath.Join(t.TempDir(), "pool.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { st.Close() })
	return st
}

func TestAddGetRemove(t *testing.T) {
	p := New(newStore(t), PlainVault{})
	id, err := p.Add(Account{Provider: "codex", Email: "a@b.c", AccountID: "up_1", Plan: "pro"},
		TokenSet{AccessToken: "at", RefreshToken: "rt"})
	if err != nil {
		t.Fatal(err)
	}
	a, err := p.Get(id)
	if err != nil || a.AccountID != "up_1" {
		t.Fatalf("Get = %+v, %v", a, err)
	}
	ts, err := p.Tokens(id)
	if err != nil || ts.AccessToken != "at" {
		t.Fatalf("Tokens = %+v, %v", ts, err)
	}
	if err := p.Remove(id); err != nil {
		t.Fatal(err)
	}
	if _, err := p.Get(id); err != ErrNotFound {
		t.Fatalf("Get after remove = %v, want ErrNotFound", err)
	}
	// Tokens must cascade with the account in the same transaction.
	if _, err := p.Tokens(id); err != ErrNotFound {
		t.Fatalf("Tokens after remove = %v, want ErrNotFound", err)
	}
}

func TestImportV1DBDryRunThenApply(t *testing.T) {
	// Build a v1-shaped source DB.
	dir := t.TempDir()
	v1 := filepath.Join(dir, "v1.db")
	st, err := state.Init(v1)
	if err != nil {
		t.Fatal(err)
	}
	src := New(st, PlainVault{})
	if _, err := src.Add(Account{Provider: "codex", Email: "x@y.z", AccountID: "up_x", Plan: "plus"},
		TokenSet{AccessToken: "at-x"}); err != nil {
		t.Fatal(err)
	}
	if _, err := src.Add(Account{Provider: "codex", Email: "no-id@y.z"},
		TokenSet{AccessToken: "at-y"}); err != nil {
		t.Fatal(err)
	}
	st.Close()

	p := New(newStore(t), PlainVault{})
	var buf bytes.Buffer
	n, err := p.ImportV1DB(v1, true, &buf)
	if err != nil {
		t.Fatal(err)
	}
	if n != 0 {
		t.Fatalf("dry-run imported %d accounts", n)
	}
	out := buf.String()
	if !strings.Contains(out, "up_x") || !strings.Contains(out, "skip-no-identity") {
		t.Fatalf("dry-run mapping missing identity rows:\n%s", out)
	}
	accts, _ := p.List()
	if len(accts) != 0 {
		t.Fatal("dry-run must not write")
	}

	buf.Reset()
	if n, err = p.ImportV1DB(v1, false, &buf); err != nil || n != 1 {
		t.Fatalf("apply imported %d, %v; want 1", n, err)
	}
	accts, _ = p.List()
	if len(accts) != 1 || accts[0].AccountID != "up_x" {
		t.Fatalf("accounts = %+v", accts)
	}
	// Identity dedupe: re-import must skip the same upstream id.
	buf.Reset()
	if n, err = p.ImportV1DB(v1, false, &buf); err != nil || n != 0 {
		t.Fatalf("re-import = %d, %v; want 0 (dedupe by upstream id)", n, err)
	}
	if !strings.Contains(buf.String(), "skip-duplicate") {
		t.Fatalf("expected skip-duplicate:\n%s", buf.String())
	}
}

func TestImportCliproxyDir(t *testing.T) {
	dir := t.TempDir()
	doc := `{"type":"codex","email":"c@d.e","account_id":"up_c","access_token":"at-c","refresh_token":"rt-c"}`
	if err := os.WriteFile(filepath.Join(dir, "codex-c@d.e.json"), []byte(doc), 0o600); err != nil {
		t.Fatal(err)
	}
	p := New(newStore(t), PlainVault{})
	var buf bytes.Buffer
	n, err := p.ImportCliproxyDir(dir, false, &buf)
	if err != nil || n != 1 {
		t.Fatalf("import = %d, %v", n, err)
	}
	accts, _ := p.List()
	if len(accts) != 1 || accts[0].AccountID != "up_c" {
		t.Fatalf("accounts = %+v", accts)
	}
	ts, _ := p.Tokens(accts[0].ID)
	if ts.AccessToken != "at-c" {
		t.Fatalf("tokens = %+v", ts)
	}
}

// TestFKAfterDelete codifies the v1 "FOREIGN KEY constraint failed"
// class: a write referencing a deleted account id fails atomically at
// the FK, and (unlike v1) no poller can be halfway through a snapshot
// write when the delete lands — both are serialized on one writer.
func TestFKAfterDelete(t *testing.T) {
	st := newStore(t)
	p := New(st, PlainVault{})
	id, err := p.Add(Account{Provider: "codex", Email: "a@b.c", AccountID: "up_1"},
		TokenSet{AccessToken: "at"})
	if err != nil {
		t.Fatal(err)
	}
	if err := p.Remove(id); err != nil {
		t.Fatal(err)
	}
	// A stale snapshot write for the deleted id must fail, not
	// silently resurrect or corrupt.
	err = st.Submit(func(tx *sql.Tx) error {
		_, err := tx.Exec(
			`INSERT INTO window_history(account_id, window_kind, window_end,
			 final_used_pct, final_snapshot_ts, reset_cause, created_at)
			 VALUES(?, '5h', 1, 2, 3, 'natural', 4)`, id)
		return err
	})
	if err == nil {
		t.Fatal("window_history insert for deleted account must violate FK")
	}
}
