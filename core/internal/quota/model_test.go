package quota

import (
	"testing"
	"time"
)

const BASE = 1_700_000_000.0

func timed(kind string, used, resetAt float64, windowS int64) Window {
	return Window{Kind: kind, UsedPct: f(used), ResetAt: f(resetAt), WindowS: windowS}
}

func drop(kind string, used float64, boundary any) Window {
	return Window{Kind: kind, UsedPct: f(used), Boundary: boundary}
}

func snap(ts float64, ws ...Window) Snapshot {
	return Snapshot{Ts: ts, Status: "active", Windows: ws}
}

func TestNaturalRolloverCodex5h(t *testing.T) {
	prev := snap(BASE, timed("5h", 85, BASE+300, 18000))
	next := snap(BASE+600, timed("5h", 3, BASE+300+18000, 18000))
	out := DetectClosedWindows(prev, next, false)
	if len(out) != 1 {
		t.Fatalf("got %d closes, want 1", len(out))
	}
	cw := out[0]
	if cw.WindowKind != "5h" || cw.ResetCause != "natural" {
		t.Fatalf("%+v", cw)
	}
	if cw.WindowEnd != BASE+300 || *cw.WindowStart != BASE+300-18000 {
		t.Fatalf("end %v start %v", cw.WindowEnd, cw.WindowStart)
	}
	if cw.FinalUsedPct != 85 || cw.FinalSnapshotTs != BASE {
		t.Fatalf("%+v", cw)
	}
	if cw.Details["staleness_s"] != 300.0 {
		t.Fatalf("staleness %v", cw.Details["staleness_s"])
	}
}

func TestSleepGapSpanningBoundaryIsNatural(t *testing.T) {
	prev := snap(BASE, timed("5h", 85, BASE+300, 18000))
	next := snap(BASE+30000, timed("5h", 3, BASE+30000+12000, 18000))
	out := DetectClosedWindows(prev, next, false)
	if len(out) != 1 || out[0].ResetCause != "natural" || out[0].WindowEnd != BASE+300 {
		t.Fatalf("%+v", out)
	}
}

func TestEarlyResetCouponEvidence(t *testing.T) {
	two, one := 2, 1
	prev := snap(BASE, timed("5h", 90, BASE+10000, 18000))
	prev.BankedResets = &two
	next := snap(BASE+300, timed("5h", 0.5, BASE+300+18000, 18000))
	next.BankedResets = &one
	out := DetectClosedWindows(prev, next, false)
	if len(out) != 1 || out[0].ResetCause != "coupon" {
		t.Fatalf("%+v", out)
	}
	if out[0].WindowEnd != BASE+150 {
		t.Fatalf("window_end %v, want midpoint", out[0].WindowEnd)
	}
}

func TestEarlyResetWithoutEvidenceIsProviderReset(t *testing.T) {
	two := 2
	prev := snap(BASE, timed("5h", 90, BASE+10000, 18000))
	prev.BankedResets = &two
	next := snap(BASE+300, timed("5h", 0.5, BASE+300+18000, 18000))
	next.BankedResets = &two
	out := DetectClosedWindows(prev, next, false)
	if len(out) != 1 || out[0].ResetCause != "provider_reset" {
		t.Fatalf("%+v", out)
	}
}

func TestCouponHintForcesCoupon(t *testing.T) {
	prev := snap(BASE, timed("5h", 90, BASE+10000, 18000))
	next := snap(BASE+300, timed("5h", 0.5, BASE+300+18000, 18000))
	out := DetectClosedWindows(prev, next, true)
	if len(out) != 1 || out[0].ResetCause != "coupon" {
		t.Fatalf("%+v", out)
	}
}

func TestSlidingResetIdleAccountEmitsNothing(t *testing.T) {
	prev := snap(BASE, timed("5h", 1, BASE+18000, 18000))
	next := snap(BASE+300, timed("5h", 1, BASE+300+18000, 18000))
	if out := DetectClosedWindows(prev, next, false); len(out) != 0 {
		t.Fatalf("%+v", out)
	}
}

func TestGenuineMidwindowCouponDetected(t *testing.T) {
	two, one := 2, 1
	prev := snap(BASE, timed("5h", 80, BASE+9000, 18000))
	prev.BankedResets = &two
	next := snap(BASE+300, timed("5h", 2, BASE+300+18000, 18000))
	next.BankedResets = &one
	out := DetectClosedWindows(prev, next, false)
	if len(out) != 1 || out[0].ResetCause != "coupon" {
		t.Fatalf("%+v", out)
	}
}

func TestGuardJumpButUsageClimbed(t *testing.T) {
	prev := snap(BASE, timed("5h", 5, BASE+9000, 18000))
	next := snap(BASE+300, timed("5h", 7, BASE+300+18000, 18000))
	if out := DetectClosedWindows(prev, next, false); len(out) != 0 {
		t.Fatalf("%+v", out)
	}
}

func TestGuardUsageFellButJumpWithinGap(t *testing.T) {
	prev := snap(BASE, timed("5h", 80, BASE+18000, 18000))
	next := snap(BASE+300, timed("5h", 2, BASE+300+18000, 18000))
	if out := DetectClosedWindows(prev, next, false); len(out) != 0 {
		t.Fatalf("%+v", out)
	}
}

func TestNaturalRollAcrossLongGapSuppressed(t *testing.T) {
	prev := snap(BASE, timed("5h", 50, BASE+18000, 18000))
	next := snap(BASE+18000, timed("5h", 1, BASE+18000+18000, 18000))
	if out := DetectClosedWindows(prev, next, false); len(out) != 0 {
		t.Fatalf("%+v", out)
	}
}

func TestWeeklyClassifiedByDuration(t *testing.T) {
	if got := KindFromWindowS(604800, "5h"); got != "weekly" {
		t.Fatalf("KindFromWindowS = %s", got)
	}
}

func TestErrorSnapshotsNeverParticipate(t *testing.T) {
	prev := snap(BASE, timed("5h", 85, BASE+300, 18000))
	prev.Status = "error"
	next := snap(BASE+600, timed("5h", 3, BASE+300+18000, 18000))
	if out := DetectClosedWindows(prev, next, false); len(out) != 0 {
		t.Fatalf("%+v", out)
	}
}

func TestToleranceJitterIgnored(t *testing.T) {
	prev := snap(BASE, timed("5h", 85, BASE+300, 18000))
	next := snap(BASE+600, timed("5h", 3, BASE+300+60, 18000))
	if out := DetectClosedWindows(prev, next, false); len(out) != 0 {
		t.Fatalf("%+v", out)
	}
}

func TestZeroUsageWindowSkipped(t *testing.T) {
	prev := snap(BASE, timed("5h", 0, BASE+300, 18000))
	next := snap(BASE+600, timed("5h", 0, BASE+300+18000, 18000))
	if out := DetectClosedWindows(prev, next, false); len(out) != 0 {
		t.Fatalf("%+v", out)
	}
}

func TestDropNearBoundaryNatural(t *testing.T) {
	boundary := BASE + 400
	prev := snap(BASE, drop("monthly_chat", 70, boundary))
	next := snap(BASE+600, drop("monthly_chat", 5, boundary))
	out := DetectClosedWindows(prev, next, false)
	if len(out) != 1 || out[0].ResetCause != "natural" {
		t.Fatalf("%+v", out)
	}
}

func TestDropFarFromBoundaryUnknown(t *testing.T) {
	boundary := BASE + 90000
	prev := snap(BASE, drop("monthly_chat", 70, boundary))
	next := snap(BASE+600, drop("monthly_chat", 5, boundary))
	out := DetectClosedWindows(prev, next, false)
	if len(out) != 1 || out[0].ResetCause != "unknown" {
		t.Fatalf("%+v", out)
	}
}

func TestSmallDropDoesNotClose(t *testing.T) {
	prev := snap(BASE, drop("monthly_chat", 70, nil))
	next := snap(BASE+600, drop("monthly_chat", 65, nil))
	if out := DetectClosedWindows(prev, next, false); len(out) != 0 {
		t.Fatalf("%+v", out)
	}
}

func TestDropNearLocalMidnightNatural(t *testing.T) {
	// Pair straddling a KST midnight, computed deterministically.
	midnight := float64(time.Date(2026, 8, 2, 0, 0, 0, 0, kst).Unix())
	prev := snap(midnight-300, drop("daily", 60, "midnight"))
	next := snap(midnight+300, drop("daily", 2, "midnight"))
	out := DetectClosedWindows(prev, next, false)
	if len(out) != 1 || out[0].ResetCause != "natural" {
		t.Fatalf("%+v", out)
	}
}

func TestHistoryKindSuffixByLabel(t *testing.T) {
	w := Window{Kind: "weekly", Label: "Claude Fable", UsedPct: f(40)}
	if got := w.HistoryKey(); got != "weekly_claude_fable" {
		t.Fatalf("HistoryKey = %s", got)
	}
}

func TestRemainingPctFallback(t *testing.T) {
	rem := 20.0
	w := Window{Kind: "5h", RemainingPct: &rem}
	if used, ok := w.used(); !ok || used != 80 {
		t.Fatalf("used = %v, %v", used, ok)
	}
}
