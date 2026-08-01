// Package auth ports v1's credential flows: refresh-on-use (S21) and
// the OAuth/device login machinery behind POST /api/v1/accounts.
package auth

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"tokenbar/internal/pool"
)

// RefreshConfig is one provider's token-refresh endpoint shape,
// ported from the v1 adapters.
type RefreshConfig struct {
	TokenURL     string
	ClientID     string
	ClientSecret string
	JSONBody     bool              // claude posts JSON; codex/antigravity post forms
	Headers      map[string]string // provider-required headers (v1 UA exception)
}

// RefreshConfigs are the ported v1 refresh endpoints. API-key
// providers (xai, devin, kimi) have no refresh and are absent.
var RefreshConfigs = map[string]RefreshConfig{
	"codex": {
		TokenURL: "https://auth.openai.com/oauth/token",
		ClientID: "app_EMoamEEZ73f0CkXaXp7hrann",
	},
	"claude": {
		TokenURL: "https://api.anthropic.com/v1/oauth/token",
		ClientID: "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
		JSONBody: true,
	},
	"antigravity": {
		TokenURL: "https://oauth2.googleapis.com/token",
		// Client id/secret load from the provider config at serve time.
	},
}

type tokenResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	IDToken      string `json:"id_token"`
	ExpiresIn    int64  `json:"expires_in"`
}

type call struct {
	done chan struct{}
	tok  string
	err  error
}

// Refresher performs refresh-on-use: a token is refreshed only when a
// request for that account is being routed and it is past 80% of its
// TTL (S21). Singleflight per account replaces v1's flock.
type Refresher struct {
	Pool    *pool.Pool
	Configs map[string]RefreshConfig
	Client  *http.Client

	mu       sync.Mutex
	inflight map[int64]*call
}

func NewRefresher(p *pool.Pool) *Refresher {
	return &Refresher{
		Pool:     p,
		Configs:  RefreshConfigs,
		Client:   &http.Client{Timeout: 30 * time.Second},
		inflight: map[int64]*call{},
	}
}

// needsRefresh reports whether the token is past 80% of its TTL.
func needsRefresh(ts pool.TokenSet, now float64) bool {
	if ts.ExpiresAt <= 0 {
		return false // API keys and unknown expiries are never refreshed
	}
	if now >= ts.ExpiresAt {
		return true
	}
	lastRefresh := ts.LastRefresh
	if lastRefresh <= 0 {
		// Issued-at unknown: assume the provider default 1h TTL.
		lastRefresh = ts.ExpiresAt - 3600
	}
	if ts.ExpiresAt > lastRefresh {
		return now >= lastRefresh+0.8*(ts.ExpiresAt-lastRefresh)
	}
	return false
}

// TokenFor returns a usable access token for an account, refreshing
// first when due (S21). Accounts whose provider has no refresh config
// return their stored token unchanged.
func (r *Refresher) TokenFor(ctx context.Context, accountID int64) (string, error) {
	a, err := r.Pool.Get(accountID)
	if err != nil {
		return "", err
	}
	ts, err := r.Pool.Tokens(accountID)
	if err != nil {
		return "", err
	}
	cfg, ok := r.Configs[a.Provider]
	if !ok || ts.RefreshToken == "" || !needsRefresh(ts, float64(time.Now().Unix())) {
		return ts.AccessToken, nil
	}

	r.mu.Lock()
	if c, ok := r.inflight[accountID]; ok {
		r.mu.Unlock()
		select {
		case <-c.done:
			return c.tok, c.err
		case <-ctx.Done():
			return "", ctx.Err()
		}
	}
	c := &call{done: make(chan struct{})}
	r.inflight[accountID] = c
	r.mu.Unlock()

	c.tok, c.err = r.refresh(ctx, a.Provider, cfg, accountID, ts)
	close(c.done)
	r.mu.Lock()
	delete(r.inflight, accountID)
	r.mu.Unlock()
	return c.tok, c.err
}

func (r *Refresher) refresh(ctx context.Context, provider string, cfg RefreshConfig, accountID int64, ts pool.TokenSet) (string, error) {
	var req *http.Request
	var err error
	if cfg.JSONBody {
		body, _ := json.Marshal(map[string]string{
			"grant_type": "refresh_token", "client_id": cfg.ClientID,
			"refresh_token": ts.RefreshToken,
		})
		req, err = http.NewRequestWithContext(ctx, "POST", cfg.TokenURL, strings.NewReader(string(body)))
		req.Header.Set("Content-Type", "application/json")
	} else {
		form := url.Values{
			"grant_type":    {"refresh_token"},
			"client_id":     {cfg.ClientID},
			"refresh_token": {ts.RefreshToken},
		}
		if cfg.ClientSecret != "" {
			form.Set("client_secret", cfg.ClientSecret)
		}
		req, err = http.NewRequestWithContext(ctx, "POST", cfg.TokenURL, strings.NewReader(form.Encode()))
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	if err != nil {
		return "", err
	}
	for k, v := range cfg.Headers {
		req.Header.Set(k, v)
	}

	resp, err := r.Client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("auth: %s refresh: %d", provider, resp.StatusCode)
	}
	var tr tokenResponse
	if err := json.Unmarshal(raw, &tr); err != nil {
		return "", err
	}
	if tr.AccessToken == "" {
		return "", fmt.Errorf("auth: %s refresh: empty access token", provider)
	}
	next := pool.TokenSet{
		AccessToken: tr.AccessToken,
		IDToken:     tr.IDToken,
		ExpiresAt:   float64(time.Now().Unix() + tr.ExpiresIn),
		LastRefresh: float64(time.Now().Unix()),
		RawJSON:     string(raw),
	}
	if tr.RefreshToken != "" {
		next.RefreshToken = tr.RefreshToken
	} else {
		next.RefreshToken = ts.RefreshToken
	}
	if err := r.Pool.UpdateTokens(accountID, next); err != nil {
		return "", err
	}
	return next.AccessToken, nil
}
