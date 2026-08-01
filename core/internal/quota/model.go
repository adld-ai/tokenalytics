// Package quota is the Go port of v1's window model
// (backend/window_history.py) — the piece of v1 intellectual property
// the spec keeps (5.4). It is display-only (S4): routing MUST NOT
// read it, which a package-boundary test enforces.
//
// The port keeps v1's detection rules and constants verbatim:
//
//	Rule 1: only successful snapshots participate (active/rate_limited).
//	Rule 2: a timed window closed when reset_at moved forward by more
//	        than RESET_TOLERANCE_S and by more than the snapshot gap —
//	        natural at/past the old boundary, coupon/provider_reset when
//	        observed early (with a usage drop required).
//	Rule 3: a timestamp-less window closed when used_pct dropped by
//	        more than DROP_THRESHOLD_PCT — natural near a boundary.
//	Zero-usage windows are never reported.
package quota

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
	"time"
)

const (
	ResetToleranceS  = 120.0
	EarlyResetS      = 600.0
	DropThresholdPct = 10.0
	BoundaryMatchS   = 3600.0
)

var successStatuses = map[string]bool{"active": true, "rate_limited": true}

// Window is one quota window in the declared (normalized) shape.
type Window struct {
	Kind         string   `json:"kind,omitempty"`
	Label        string   `json:"label,omitempty"`
	HistoryKind  string   `json:"history_kind,omitempty"`
	UsedPct      *float64 `json:"used_pct,omitempty"`
	RemainingPct *float64 `json:"remaining_pct,omitempty"`
	ResetAt      *float64 `json:"reset_at_epoch,omitempty"`
	WindowS      int64    `json:"window_s,omitempty"`
	Boundary     any      `json:"boundary,omitempty"` // unix ts or "midnight"
	History      *bool    `json:"history,omitempty"`
	Start        *float64 `json:"start,omitempty"`
}

// Snapshot is one successful reading of an account's quota state.
type Snapshot struct {
	Ts           float64
	Status       string
	Windows      []Window
	BankedResets *int
}

// ClosedWindow is one window that closed between two snapshots.
type ClosedWindow struct {
	WindowKind      string
	WindowStart     *float64
	WindowEnd       float64
	FinalUsedPct    float64
	FinalSnapshotTs float64
	ResetCause      string // natural|coupon|provider_reset|unknown
	Details         map[string]any
}

func f(v float64) *float64 { return &v }

// KindFromWindowS mirrors v1's duration classification.
func KindFromWindowS(windowS int64, def string) string {
	switch {
	case windowS == 0:
		return def
	case windowS >= 17000 && windowS <= 19000:
		return "5h"
	case windowS == 86400:
		return "daily"
	case windowS >= 500000 && windowS < 1000000:
		return "weekly"
	case windowS >= 1000000:
		return "monthly"
	}
	return def
}

// windowSByKind mirrors v1's nominal durations (monthly varies: absent).
var windowSByKind = map[string]int64{
	"5h": 18000, "session": 18000, "daily": 86400,
	"weekly": 604800, "model_weekly": 604800,
}

var slugRe = regexp.MustCompile(`[^a-z0-9]+`)

func (w Window) baseKind() string {
	if w.Kind != "" {
		return w.Kind
	}
	return KindFromWindowS(w.WindowS, "session")
}

// HistoryKey is v1's _declared_kind: the stable per-window history key.
func (w Window) HistoryKey() string {
	if w.HistoryKind != "" {
		return w.HistoryKind
	}
	base := w.baseKind()
	slug := strings.Trim(slugRe.ReplaceAllString(strings.ToLower(w.Label), "_"), "_")
	if slug != "" {
		return base + "_" + slug
	}
	return base
}

func (w Window) used() (float64, bool) {
	if w.UsedPct != nil {
		return *w.UsedPct, true
	}
	if w.RemainingPct != nil {
		v := 100.0 - *w.RemainingPct
		if v < 0 {
			v = 0
		}
		if v > 100 {
			v = 100
		}
		return v, true
	}
	return 0, false
}

func (w Window) historyEnabled() bool {
	return w.History == nil || *w.History
}

type timedWindow struct {
	kind    string
	usedPct float64
	resetAt float64
	windowS int64
	start   *float64
}

func timedWindows(s Snapshot) []timedWindow {
	var out []timedWindow
	for _, w := range s.Windows {
		if !w.historyEnabled() || w.ResetAt == nil {
			continue
		}
		used, ok := w.used()
		if !ok {
			continue
		}
		ws := w.WindowS
		if ws == 0 {
			ws = windowSByKind[w.baseKind()]
		}
		out = append(out, timedWindow{
			kind: w.HistoryKey(), usedPct: used, resetAt: *w.ResetAt,
			windowS: ws, start: w.Start,
		})
	}
	return out
}

type dropWindow struct {
	kind     string
	usedPct  float64
	boundary any
}

func dropWindows(s Snapshot) []dropWindow {
	var out []dropWindow
	for _, w := range s.Windows {
		if !w.historyEnabled() || w.ResetAt != nil {
			continue
		}
		used, ok := w.used()
		if !ok {
			continue
		}
		out = append(out, dropWindow{kind: w.HistoryKey(), usedPct: used, boundary: w.Boundary})
	}
	return out
}

func bankedDecreased(prev, next Snapshot) bool {
	return prev.BankedResets != nil && next.BankedResets != nil &&
		*next.BankedResets < *prev.BankedResets
}

func nearBoundary(prevTs, newTs, boundary float64) bool {
	return prevTs-BoundaryMatchS <= boundary && boundary <= newTs+BoundaryMatchS
}

var kst = time.FixedZone("KST", 9*3600)

func nearLocalMidnight(prevTs, newTs float64) bool {
	t := time.Unix(int64(newTs), 0).In(kst)
	day := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, kst)
	for _, d := range []int{0, 1} {
		if nearBoundary(prevTs, newTs, float64(day.AddDate(0, 0, d).Unix())) {
			return true
		}
	}
	return false
}

// DetectClosedWindows ports v1's detect_closed_windows for declared
// snapshots. Error snapshots never participate, so a connection
// failure can never fake or corrupt a reset.
func DetectClosedWindows(prev, next Snapshot, couponHint bool) []ClosedWindow {
	if !successStatuses[prev.Status] || !successStatuses[next.Status] {
		return nil
	}
	if next.Ts <= prev.Ts {
		return nil
	}
	var closed []ClosedWindow
	couponEvidence := couponHint || bankedDecreased(prev, next)

	nextTimed := map[string]timedWindow{}
	for _, w := range timedWindows(next) {
		nextTimed[w.kind] = w
	}
	for _, w := range timedWindows(prev) {
		nw, ok := nextTimed[w.kind]
		if !ok || w.usedPct <= 0 {
			continue
		}
		rOld, rNew := w.resetAt, nw.resetAt
		if rNew-rOld <= ResetToleranceS {
			continue
		}
		// Sliding-boundary guard: a reset_at that merely tracks "now"
		// moves by ≈ the poll gap; a real reset jumps by far more.
		if rNew-rOld <= next.Ts-prev.Ts+ResetToleranceS {
			continue
		}
		var windowEnd float64
		var cause string
		if next.Ts < rOld-EarlyResetS {
			// Early reset also demands a usage drop.
			if nw.usedPct >= w.usedPct {
				continue
			}
			windowEnd = (prev.Ts + next.Ts) / 2
			if couponEvidence {
				cause = "coupon"
			} else {
				cause = "provider_reset"
			}
		} else {
			windowEnd = rOld
			cause = "natural"
		}
		start := w.start
		if start == nil && w.windowS > 0 {
			start = f(rOld - float64(w.windowS))
		}
		closed = append(closed, ClosedWindow{
			WindowKind: w.kind, WindowStart: start, WindowEnd: windowEnd,
			FinalUsedPct: w.usedPct, FinalSnapshotTs: prev.Ts, ResetCause: cause,
			Details: map[string]any{
				"staleness_s": round1(max(0, windowEnd-prev.Ts)),
				"prev_ts":     prev.Ts, "new_ts": next.Ts,
				"old_reset_at": rOld, "new_reset_at": rNew,
			},
		})
	}

	nextDrop := map[string]dropWindow{}
	for _, w := range dropWindows(next) {
		nextDrop[w.kind] = w
	}
	for _, w := range dropWindows(prev) {
		nw, ok := nextDrop[w.kind]
		if !ok || w.usedPct <= 0 {
			continue
		}
		if w.usedPct-nw.usedPct < DropThresholdPct {
			continue
		}
		var natural bool
		if s, ok := w.boundary.(string); ok && s == "midnight" {
			natural = nearLocalMidnight(prev.Ts, next.Ts)
		} else if b, ok := toFloat(w.boundary); ok {
			natural = nearBoundary(prev.Ts, next.Ts, b)
		}
		cause := "unknown"
		if natural {
			cause = "natural"
		}
		closed = append(closed, ClosedWindow{
			WindowKind: w.kind, WindowEnd: next.Ts,
			FinalUsedPct: w.usedPct, FinalSnapshotTs: prev.Ts, ResetCause: cause,
			Details: map[string]any{
				"staleness_s": round1(next.Ts - prev.Ts),
				"prev_ts":     prev.Ts, "new_ts": next.Ts,
				"prev_used_pct": w.usedPct, "new_used_pct": nw.usedPct,
			},
		})
	}
	return closed
}

func toFloat(v any) (float64, bool) {
	switch t := v.(type) {
	case float64:
		return t, true
	case int64:
		return float64(t), true
	case json.Number:
		fv, err := t.Float64()
		return fv, err == nil
	}
	return 0, false
}

func round1(v float64) float64 { return float64(int(v*10+0.5)) / 10 }

func max(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}

// ParseWindows decodes the declared windows array from a raw_json
// payload, mirroring v1's declared() reader.
func ParseWindows(rawJSON string) ([]Window, error) {
	if rawJSON == "" {
		return nil, nil
	}
	var doc struct {
		Windows []Window `json:"windows"`
	}
	if err := json.Unmarshal([]byte(rawJSON), &doc); err != nil {
		return nil, fmt.Errorf("quota: windows: %w", err)
	}
	return doc.Windows, nil
}
