// engine.go is the quota-state consumer for harvest observations and
// idle-poll snapshots. It is display-only (S4, 13.3): nothing in the
// request path reads it.
package harvest

import (
	"database/sql"
	"log"
	"sync"
	"time"

	"tokenbar/internal/quota"
	"tokenbar/internal/state"
)

// Engine keeps per-account latest window state and archives closed
// windows, both through the store's single writer.
type Engine struct {
	st *state.Store

	mu      sync.Mutex
	last    map[int64]quota.Snapshot
	lastObs map[int64]time.Time
}

func NewEngine(st *state.Store) *Engine {
	return &Engine{st: st, last: map[int64]quota.Snapshot{}, lastObs: map[int64]time.Time{}}
}

// Observe implements Sink for metered-usage observations.
func (e *Engine) Observe(o Observation) {
	e.mu.Lock()
	e.lastObs[o.AccountID] = o.At
	e.mu.Unlock()
}

// ApplySnapshot stores a full window snapshot (idle poll or header
// harvest), archiving any windows that closed since the previous one.
// Failures are logged and dropped, never propagated (S4).
func (e *Engine) ApplySnapshot(accountID int64, s quota.Snapshot) {
	e.mu.Lock()
	prev, hasPrev := e.last[accountID]
	e.last[accountID] = s
	e.lastObs[accountID] = time.Now()
	e.mu.Unlock()

	var closed []quota.ClosedWindow
	if hasPrev {
		closed = quota.DetectClosedWindows(prev, s, false)
	}
	err := e.st.Submit(func(tx *sql.Tx) error {
		for _, w := range s.Windows {
			used, hasUsed := wUsed(w)
			var resetAt any
			if w.ResetAt != nil {
				resetAt = *w.ResetAt
			}
			_, err := tx.Exec(
				`INSERT INTO quota_windows(account_id, window_kind, used_pct, reset_at, window_s, label, source, updated_at)
				 VALUES(?,?,?,?,?,?,?,?)
				 ON CONFLICT(account_id, window_kind) DO UPDATE SET
				 used_pct=excluded.used_pct, reset_at=excluded.reset_at,
				 window_s=excluded.window_s, label=excluded.label,
				 source=excluded.source, updated_at=excluded.updated_at`,
				accountID, w.HistoryKey(), usedOr(used, hasUsed), resetAt,
				w.WindowS, w.Label, "harvest", time.Now().Unix())
			if err != nil {
				return err
			}
		}
		for _, cw := range closed {
			_, err := tx.Exec(
				`INSERT OR IGNORE INTO window_history
				 (account_id, window_kind, window_start, window_end, final_used_pct,
				  final_snapshot_ts, reset_cause, created_at)
				 VALUES(?,?,?,?,?,?,?,?)`,
				accountID, cw.WindowKind, cw.WindowStart, cw.WindowEnd,
				cw.FinalUsedPct, cw.FinalSnapshotTs, cw.ResetCause, time.Now().Unix())
			if err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		log.Printf("harvest: apply snapshot account=%d: %v (dropped)", accountID, err)
	}
}

func wUsed(w quota.Window) (float64, bool) {
	if w.UsedPct != nil {
		return *w.UsedPct, true
	}
	if w.RemainingPct != nil {
		return 100 - *w.RemainingPct, true
	}
	return 0, false
}

func usedOr(v float64, ok bool) any {
	if !ok {
		return nil
	}
	return v
}

// LastObservation reports when an account last produced request-path
// data; the idle poller skips accounts fresher than its interval (S22).
func (e *Engine) LastObservation(accountID int64) time.Time {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.lastObs[accountID]
}

// LatestWindows is the display read path for /state.
func (e *Engine) LatestWindows(accountID int64) ([]quota.Window, error) {
	rows, err := e.st.Query(
		"SELECT window_kind, used_pct, reset_at, window_s, label FROM quota_windows WHERE account_id = ?", accountID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []quota.Window
	for rows.Next() {
		var w quota.Window
		var used, reset sql.NullFloat64
		if err := rows.Scan(&w.Kind, &used, &reset, &w.WindowS, &w.Label); err != nil {
			return nil, err
		}
		if used.Valid {
			w.UsedPct = &used.Float64
		}
		if reset.Valid {
			w.ResetAt = &reset.Float64
		}
		out = append(out, w)
	}
	return out, rows.Err()
}
