// probes.go ports the v1 usage-probe endpoint shapes (S22: the same
// calls the official clients themselves make).
package idlepoll

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"tokenbar/internal/auth"
	"tokenbar/internal/pool"
	"tokenbar/internal/quota"
)

// codexUsage mirrors the wham/usage response shape.
type codexUsage struct {
	PlanType  string `json:"plan_type"`
	RateLimit struct {
		PrimaryWindow   *codexWindow `json:"primary_window"`
		SecondaryWindow *codexWindow `json:"secondary_window"`
	} `json:"rate_limit"`
	ResetCredits struct {
		AvailableCount *int `json:"available_count"`
	} `json:"rate_limit_reset_credits"`
}

type codexWindow struct {
	UsedPercent        *float64 `json:"used_percent"`
	ResetAfterSeconds  *float64 `json:"reset_after_seconds"`
	LimitWindowSeconds int64    `json:"limit_window_seconds"`
}

// CodexProbe polls wham/usage for one codex account.
type CodexProbe struct {
	Pool      *pool.Pool
	Refresher *auth.Refresher
	Client    *http.Client
	BaseURL   string // default https://chatgpt.com/backend-api
}

func (p *CodexProbe) Probe(ctx context.Context, a pool.Account) (quota.Snapshot, error) {
	tok, err := p.Refresher.TokenFor(ctx, a.ID)
	if err != nil {
		return quota.Snapshot{}, err
	}
	base := p.BaseURL
	if base == "" {
		base = "https://chatgpt.com/backend-api"
	}
	req, err := http.NewRequestWithContext(ctx, "GET", base+"/wham/usage", nil)
	if err != nil {
		return quota.Snapshot{}, err
	}
	req.Header.Set("Authorization", "Bearer "+tok)
	if a.AccountID != "" {
		req.Header.Set("ChatGPT-Account-Id", a.AccountID)
	}
	req.Header.Set("User-Agent", "codex_cli_rs/0.146.0")
	client := p.Client
	if client == nil {
		client = &http.Client{Timeout: 30 * time.Second}
	}
	resp, err := client.Do(req)
	if err != nil {
		return quota.Snapshot{}, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if resp.StatusCode == http.StatusTooManyRequests {
		return quota.Snapshot{}, RateLimitError{Provider: "codex"}
	}
	if resp.StatusCode != http.StatusOK {
		return quota.Snapshot{}, fmt.Errorf("codex usage: HTTP %d", resp.StatusCode)
	}
	// The endpoint returns the usage payload at top level (v1 wraps it
	// under "usage" only when persisting raw_json).
	var body codexUsage
	if err := json.Unmarshal(raw, &body); err != nil {
		return quota.Snapshot{}, err
	}
	captured := float64(time.Now().Unix())
	snap := quota.Snapshot{Ts: captured, Status: "active"}
	add := func(cw *codexWindow, def string) {
		if cw == nil {
			return
		}
		if cw.UsedPercent == nil {
			return
		}
		w := quota.Window{
			Kind:    quota.KindFromWindowS(cw.LimitWindowSeconds, def),
			UsedPct: cw.UsedPercent,
			WindowS: cw.LimitWindowSeconds,
		}
		if cw.ResetAfterSeconds != nil {
			reset := captured + *cw.ResetAfterSeconds
			w.ResetAt = &reset
		} else {
			disabled := false
			w.History = &disabled // legacy: no reset ts → no history
		}
		snap.Windows = append(snap.Windows, w)
	}
	add(body.RateLimit.PrimaryWindow, "5h")
	add(body.RateLimit.SecondaryWindow, "weekly")
	snap.BankedResets = body.ResetCredits.AvailableCount
	return snap, nil
}
