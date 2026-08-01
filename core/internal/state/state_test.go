package state

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"
)

func TestOpenMissingIsLoudError(t *testing.T) {
	_, err := Open(filepath.Join(t.TempDir(), "nope.db"))
	if err == nil {
		t.Fatal("Open on missing DB must fail loudly (spec 6)")
	}
}

func TestSingleWriterSerialization(t *testing.T) {
	st, err := Init(filepath.Join(t.TempDir(), "pool.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()

	const n = 64
	done := make(chan error, n)
	for i := 0; i < n; i++ {
		done <- st.Submit(func(tx *sql.Tx) error {
			_, err := tx.Exec(
				"INSERT INTO lifecycle_events(ts, account_id, event) VALUES(1, 1, 'window_reset')")
			return err
		})
	}
	for i := 0; i < n; i++ {
		if err := <-done; err != nil {
			t.Fatal(err)
		}
	}
	var count int
	if err := st.Read(func(tx *sql.Tx) error {
		return tx.QueryRow("SELECT COUNT(*) FROM lifecycle_events").Scan(&count)
	}); err != nil {
		t.Fatal(err)
	}
	if count != n {
		t.Fatalf("count = %d, want %d", count, n)
	}
}

func TestBackup(t *testing.T) {
	dir := t.TempDir()
	st, err := Init(filepath.Join(dir, "pool.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()
	dst, err := st.Backup(filepath.Join(dir, "backups"), 7)
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(dst)
	if err != nil || info.Size() == 0 {
		t.Fatalf("backup missing: %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("backup perms = %o, want 600", info.Mode().Perm())
	}
}
