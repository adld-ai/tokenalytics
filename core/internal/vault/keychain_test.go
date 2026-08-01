package vault

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"tokenbar/internal/pool"
	"tokenbar/internal/state"
)

const testService = "com.tonye.tokenbar.test"

func TestKeychainRoundTrip(t *testing.T) {
	k := &Keychain{Service: testService}
	want := pool.TokenSet{AccessToken: "at-secret", RefreshToken: "rt-secret", IDToken: "it"}
	ref, err := k.Seal(want)
	if err != nil {
		t.Skipf("keychain unavailable: %v", err)
	}
	defer k.Delete(ref)
	got, err := k.Open(ref)
	if err != nil {
		t.Fatal(err)
	}
	if got.AccessToken != want.AccessToken || got.RefreshToken != want.RefreshToken {
		t.Fatalf("round trip = %+v", got)
	}
}

func TestMigrationLeavesNoPlaintext(t *testing.T) {
	st, err := state.Init(filepath.Join(t.TempDir(), "pool.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()
	p := pool.New(st, pool.PlainVault{})
	secret := "at-plaintext-migration-marker"
	if _, err := p.Add(pool.Account{Provider: "codex", Email: "a@b.c", AccountID: "up_1"},
		pool.TokenSet{AccessToken: secret, RefreshToken: "rt-marker"}); err != nil {
		t.Fatal(err)
	}

	kv := &Keychain{Service: testService}
	n, err := p.MigrateToVault(kv)
	if err != nil {
		t.Skipf("keychain unavailable: %v", err)
	}
	if n != 1 {
		t.Fatalf("migrated %d rows", n)
	}

	// Read back through the vault.
	ts, err := p.Tokens(1)
	if err != nil || ts.AccessToken != secret {
		t.Fatalf("Tokens after migration = %+v, %v", ts, err)
	}

	// DB dump contains no plaintext token (S16 verification). A
	// backup forces a WAL checkpoint so the scan sees final state.
	if _, err := st.Backup(filepath.Join(t.TempDir(), "b"), 7); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(st.Path())
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), secret) {
		t.Fatal("S16 violation: plaintext access token present in DB dump")
	}
	if strings.Contains(string(raw), "rt-marker") {
		t.Fatal("S16 violation: plaintext refresh token present in DB dump")
	}
}
