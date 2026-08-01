// Package state is the single-writer SQLite store for TokenBar v2
// (spec S6, R11). One writer goroutine drains a queue so the relay
// request path never blocks on the DB; readers use WAL snapshots.
package state

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"time"

	_ "modernc.org/sqlite"
)

const SchemaVersion = 1

const schema = `
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    email TEXT,
    label TEXT,
    plan TEXT,
    account_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    disabled INTEGER DEFAULT 0,
    tier_override TEXT,
    UNIQUE(provider, email)
);
CREATE TABLE IF NOT EXISTS tokens (
    account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    vault_ref TEXT NOT NULL,
    access_token TEXT,
    refresh_token TEXT,
    id_token TEXT,
    expires_at REAL,
    last_refresh REAL,
    raw_json TEXT
);
CREATE TABLE IF NOT EXISTS lifecycle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    account_id INTEGER,
    event TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS refresh_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    ts REAL NOT NULL,
    kind TEXT,
    success INTEGER,
    message TEXT
);
CREATE TABLE IF NOT EXISTS window_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    window_kind TEXT NOT NULL,
    window_start REAL,
    window_end REAL NOT NULL,
    final_used_pct REAL NOT NULL,
    final_snapshot_ts REAL NOT NULL,
    reset_cause TEXT NOT NULL,
    details TEXT,
    created_at REAL NOT NULL,
    UNIQUE(account_id, window_kind, window_end)
);
CREATE TABLE IF NOT EXISTS routing (
    provider TEXT PRIMARY KEY,
    policy TEXT NOT NULL DEFAULT 'pin',
    pinned_account INTEGER,
    updated_at REAL NOT NULL
);
`

// WriteOp is one unit of serialized mutation. It runs inside a
// transaction on the single writer goroutine.
type WriteOp func(tx *sql.Tx) error

type writeReq struct {
	op   WriteOp
	done chan error
}

// Store owns the DB. Writes are serialized through Submit; reads go
// through Read or the raw handle for queries.
type Store struct {
	db     *sql.DB
	writes chan writeReq
	done   chan struct{}
}

func dsn(path string) string {
	return fmt.Sprintf("file:%s?_pragma=journal_mode(WAL)&_pragma=synchronous(NORMAL)&_pragma=foreign_keys(1)&_pragma=busy_timeout(5000)", path)
}

// Init creates a fresh DB with the current schema. It fails loudly if
// the file already exists.
func Init(path string) (*Store, error) {
	if _, err := os.Stat(path); err == nil {
		return nil, fmt.Errorf("state: %s already exists; refusing to re-initialize (use Open)", path)
	}
	s, err := open(path)
	if err != nil {
		return nil, err
	}
	if _, err := s.db.Exec(schema); err != nil {
		return nil, fmt.Errorf("state: schema: %w", err)
	}
	if _, err := s.db.Exec(
		"INSERT INTO schema_version(version, applied_at) VALUES(?, ?)",
		SchemaVersion, float64(time.Now().Unix())); err != nil {
		return nil, err
	}
	return s, nil
}

// Open opens an existing DB. A missing file is a loud error with a
// repair hint, never a silent auto-create (spec 6).
func Open(path string) (*Store, error) {
	if _, err := os.Stat(path); errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("state: %s missing; run with -init or import a v1 DB to create it", path)
	}
	return open(path)
}

func open(path string) (*Store, error) {
	db, err := sql.Open("sqlite", dsn(path))
	if err != nil {
		return nil, err
	}
	s := &Store{db: db, writes: make(chan writeReq, 256), done: make(chan struct{})}
	go s.writer()
	return s, nil
}

// writer is the only goroutine that ever executes writes (S6).
func (s *Store) writer() {
	defer close(s.done)
	for req := range s.writes {
		tx, err := s.db.Begin()
		if err != nil {
			req.done <- err
			continue
		}
		if err := req.op(tx); err != nil {
			tx.Rollback()
			req.done <- err
			continue
		}
		req.done <- tx.Commit()
	}
}

// Submit enqueues a write and waits for its result. Callers that must
// not block (request path) should use SubmitAsync.
func (s *Store) Submit(op WriteOp) error {
	done := make(chan error, 1)
	s.writes <- writeReq{op: op, done: done}
	return <-done
}

// SubmitAsync enqueues a write without blocking the caller.
func (s *Store) SubmitAsync(op WriteOp) <-chan error {
	done := make(chan error, 1)
	s.writes <- writeReq{op: op, done: done}
	return done
}

// Read runs fn against the read handle (WAL snapshot isolation).
func (s *Store) Read(fn func(tx *sql.Tx) error) error {
	tx, err := s.db.BeginTx(context.Background(), &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return err
	}
	defer tx.Rollback()
	return fn(tx)
}

// Query exposes the raw handle for simple reads.
func (s *Store) Query(query string, args ...any) (*sql.Rows, error) {
	return s.db.Query(query, args...)
}

func (s *Store) Close() error {
	close(s.writes)
	<-s.done
	return s.db.Close()
}

// Backup checkpoints the WAL and copies the DB into dir, keeping
// retentionDays of nightly snapshots (R11).
func (s *Store) Backup(dir string, retentionDays int) (string, error) {
	if err := s.Submit(func(tx *sql.Tx) error {
		_, err := tx.Exec("PRAGMA wal_checkpoint(TRUNCATE)")
		return err
	}); err != nil {
		return "", fmt.Errorf("state: checkpoint: %w", err)
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	dst := filepath.Join(dir, "pool-"+time.Now().Format("2006-01-02")+".db")
	if err := copyFile(s.db, dst); err != nil {
		return "", err
	}
	entries, err := filepath.Glob(filepath.Join(dir, "pool-*.db"))
	if err != nil {
		return dst, nil
	}
	sort.Strings(entries)
	cutoff := time.Now().AddDate(0, 0, -retentionDays)
	for _, e := range entries {
		if info, err := os.Stat(e); err == nil && info.ModTime().Before(cutoff) {
			os.Remove(e)
		}
	}
	return dst, nil
}

func copyFile(db *sql.DB, dst string) error {
	// VACUUM INTO produces a consistent standalone copy. It does not
	// accept bound parameters, so quote the path literally.
	q := "'" + dst + "'"
	if _, err := db.Exec("VACUUM INTO " + q); err != nil {
		return fmt.Errorf("state: backup: %w", err)
	}
	return os.Chmod(dst, 0o600)
}
