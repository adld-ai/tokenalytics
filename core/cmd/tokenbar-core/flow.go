// flow.go implements api.FlowRunner with the ported v1 login flows.
package main

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"tokenbar/internal/auth"
	"tokenbar/internal/pool"
)

type flowRunner struct {
	configs map[string]auth.FlowConfig
}

func (f *flowRunner) Run(ctx context.Context, provider string) (pool.Account, pool.TokenSet, error) {
	cfg, ok := f.configs[provider]
	if !ok {
		return pool.Account{}, pool.TokenSet{}, fmt.Errorf("flow: unknown provider %q", provider)
	}
	client := &http.Client{Timeout: 30 * time.Second}
	switch cfg.Kind {
	case "browser":
		res, err := auth.RunBrowserFlow(ctx, cfg, auth.OpenBrowser)
		if err != nil {
			return pool.Account{}, pool.TokenSet{}, err
		}
		tok, err := auth.ExchangeCode(ctx, client, cfg, res)
		if err != nil {
			return pool.Account{}, pool.TokenSet{}, err
		}
		return accountFromTokenDoc(provider, tok)
	case "device":
		dc, err := auth.StartDeviceFlow(ctx, client, cfg)
		if err != nil {
			return pool.Account{}, pool.TokenSet{}, err
		}
		fmt.Printf("tokenbar-core: %s login — open %s and enter code %s\n",
			provider, dc.VerifyURL, dc.UserCode)
		tok, err := auth.PollDeviceFlow(ctx, client, cfg, dc)
		if err != nil {
			return pool.Account{}, pool.TokenSet{}, err
		}
		return accountFromTokenDoc(provider, tok)
	}
	return pool.Account{}, pool.TokenSet{}, fmt.Errorf("flow: %s uses direct credential entry", provider)
}

// accountFromTokenDoc maps a provider token response to an account
// identity + token set. Identity comes from the id_token claims
// (upstream account id, never email-keyed, R16).
func accountFromTokenDoc(provider string, tok map[string]any) (pool.Account, pool.TokenSet, error) {
	str := func(k string) string {
		v, _ := tok[k].(string)
		return v
	}
	num := func(k string) float64 {
		v, _ := tok[k].(float64)
		return v
	}
	ts := pool.TokenSet{
		AccessToken:  str("access_token"),
		RefreshToken: str("refresh_token"),
		IDToken:      str("id_token"),
		ExpiresAt:    float64(time.Now().Unix()) + num("expires_in"),
		LastRefresh:  float64(time.Now().Unix()),
	}
	if ts.AccessToken == "" {
		return pool.Account{}, pool.TokenSet{}, fmt.Errorf("flow: no access_token in response")
	}
	a := pool.Account{Provider: provider}
	if ts.IDToken != "" {
		if claims, err := auth.DecodeJWTPayload(ts.IDToken); err == nil {
			a.Email, _ = claims["email"].(string)
			switch provider {
			case "codex":
				if authNS, ok := claims["https://api.openai.com/auth"].(map[string]any); ok {
					a.AccountID, _ = authNS["chatgpt_account_id"].(string)
				}
				if a.Email == "" {
					if prof, ok := claims["https://api.openai.com/profile"].(map[string]any); ok {
						a.Email, _ = prof["email"].(string)
					}
				}
			}
		}
	}
	return a, ts, nil
}
