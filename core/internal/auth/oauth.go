// oauth.go ports v1's login-flow machinery to Go: browser OAuth with
// PKCE over a loopback callback (codex, claude, antigravity), device
// flow (copilot), and API-key entry (devin, kimi, xai). The
// browser-flow UA exception is documented in spec 15.2 — the flow
// presents a browser because it IS a browser flow; not request-path
// evasion (S18).
package auth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os/exec"
	"strings"
	"time"
)

// FlowConfig is one provider's login-flow shape, ported from the v1
// adapters.
type FlowConfig struct {
	Kind         string // "browser" | "device" | "apikey"
	AuthURL      string
	TokenURL     string
	ClientID     string
	Scope        string
	Port         int // loopback callback port (browser flows)
	CallbackPath string
	ExtraAuth    map[string]string // provider-specific authorize params
	JSONToken    bool              // token exchange as JSON
}

// FlowConfigs are the ported v1 login shapes.
var FlowConfigs = map[string]FlowConfig{
	"codex": {
		Kind: "browser", AuthURL: "https://auth.openai.com/oauth/authorize",
		TokenURL: "https://auth.openai.com/oauth/token",
		ClientID: "app_EMoamEEZ73f0CkXaXp7hrann",
		Scope:    "openid email profile offline_access",
		Port:     1455, CallbackPath: "/auth/callback",
		ExtraAuth: map[string]string{
			"prompt": "login", "id_token_add_organizations": "true",
			"codex_cli_simplified_flow": "true",
		},
	},
	"claude": {
		Kind: "browser", AuthURL: "https://claude.ai/oauth/authorize",
		TokenURL: "https://api.anthropic.com/v1/oauth/token",
		ClientID: "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
		Scope:    "user:profile user:inference",
		Port:     54545, CallbackPath: "/callback",
		JSONToken: true,
	},
	"antigravity": {
		Kind: "browser", AuthURL: "https://accounts.google.com/o/oauth2/v2/auth",
		TokenURL: "https://oauth2.googleapis.com/token",
		Scope:    "https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/cclog https://www.googleapis.com/auth/experimentsandconfigs",
		Port:     51121, CallbackPath: "/oauth-callback",
	},
	"copilot": {
		Kind:     "device",
		AuthURL:  "https://github.com/login/device/code",
		TokenURL: "https://github.com/login/oauth/access_token",
		ClientID: "Iv1.b507a08c87ecfe98",
		Scope:    "read:user",
	},
	"devin": {Kind: "apikey"},
	"kimi":  {Kind: "apikey"},
	"xai":   {Kind: "apikey"},
}

func genPKCE() (verifier, challenge string, err error) {
	buf := make([]byte, 32)
	if _, err = rand.Read(buf); err != nil {
		return
	}
	verifier = base64.RawURLEncoding.EncodeToString(buf)
	sum := sha256.Sum256([]byte(verifier))
	challenge = base64.RawURLEncoding.EncodeToString(sum[:])
	return
}

func genState() (string, error) {
	buf := make([]byte, 16)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buf), nil
}

// BrowserResult is a completed browser OAuth flow.
type BrowserResult struct {
	Code        string
	RedirectURI string
	Verifier    string
}

// RunBrowserFlow opens the provider's authorize URL and waits for the
// loopback callback, exactly as v1 did. openBrowser is injectable for
// tests.
func RunBrowserFlow(ctx context.Context, cfg FlowConfig, openBrowser func(string) error) (*BrowserResult, error) {
	verifier, challenge, err := genPKCE()
	if err != nil {
		return nil, err
	}
	state, err := genState()
	if err != nil {
		return nil, err
	}
	redirectURI := fmt.Sprintf("http://localhost:%d%s", cfg.Port, cfg.CallbackPath)
	q := url.Values{
		"client_id":             {cfg.ClientID},
		"response_type":         {"code"},
		"redirect_uri":          {redirectURI},
		"scope":                 {cfg.Scope},
		"state":                 {state},
		"code_challenge":        {challenge},
		"code_challenge_method": {"S256"},
	}
	for k, v := range cfg.ExtraAuth {
		q.Set(k, v)
	}

	ln, err := net.Listen("tcp", fmt.Sprintf("localhost:%d", cfg.Port))
	if err != nil {
		return nil, fmt.Errorf("auth: callback listen :%d: %w", cfg.Port, err)
	}
	defer ln.Close()

	type cb struct {
		code, state, errMsg string
	}
	got := make(chan cb, 1)
	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != cfg.CallbackPath {
			http.NotFound(w, r)
			return
		}
		v := r.URL.Query()
		got <- cb{code: v.Get("code"), state: v.Get("state"),
			errMsg: v.Get("error_description")}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		io.WriteString(w, "<html><body><p>TokenBar: login complete. You can close this tab.</p></body></html>")
	})}
	go srv.Serve(ln)
	defer srv.Shutdown(context.Background())

	if err := openBrowser(cfg.AuthURL + "?" + q.Encode()); err != nil {
		return nil, err
	}
	select {
	case res := <-got:
		if res.errMsg != "" {
			return nil, fmt.Errorf("auth: provider error: %s", res.errMsg)
		}
		if res.state != state {
			return nil, fmt.Errorf("auth: state mismatch")
		}
		return &BrowserResult{Code: res.code, RedirectURI: redirectURI, Verifier: verifier}, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-time.After(5 * time.Minute):
		return nil, fmt.Errorf("auth: callback timeout")
	}
}

// ExchangeCode swaps an authorization code for tokens.
func ExchangeCode(ctx context.Context, client *http.Client, cfg FlowConfig, res *BrowserResult) (map[string]any, error) {
	form := url.Values{
		"grant_type":    {"authorization_code"},
		"client_id":     {cfg.ClientID},
		"code":          {res.Code},
		"redirect_uri":  {res.RedirectURI},
		"code_verifier": {res.Verifier},
	}
	var req *http.Request
	var err error
	if cfg.JSONToken {
		body, _ := json.Marshal(map[string]string{
			"grant_type": "authorization_code", "client_id": cfg.ClientID,
			"code": res.Code, "redirect_uri": res.RedirectURI,
			"code_verifier": res.Verifier,
		})
		req, err = http.NewRequestWithContext(ctx, "POST", cfg.TokenURL, strings.NewReader(string(body)))
		req.Header.Set("Content-Type", "application/json")
	} else {
		req, err = http.NewRequestWithContext(ctx, "POST", cfg.TokenURL, strings.NewReader(form.Encode()))
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	if err != nil {
		return nil, err
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("auth: token exchange: %d", resp.StatusCode)
	}
	var out map[string]any
	return out, json.Unmarshal(raw, &out)
}

// DeviceCode is the provider's device-flow challenge.
type DeviceCode struct {
	DeviceCode string `json:"device_code"`
	UserCode   string `json:"user_code"`
	VerifyURL  string `json:"verification_uri"`
	Interval   int    `json:"interval"`
	ExpiresIn  int    `json:"expires_in"`
}

// StartDeviceFlow requests a device code (copilot).
func StartDeviceFlow(ctx context.Context, client *http.Client, cfg FlowConfig) (*DeviceCode, error) {
	form := url.Values{"client_id": {cfg.ClientID}, "scope": {cfg.Scope}}
	req, err := http.NewRequestWithContext(ctx, "POST", cfg.AuthURL, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("auth: device code: %d", resp.StatusCode)
	}
	var dc DeviceCode
	return &dc, json.Unmarshal(raw, &dc)
}

// PollDeviceFlow polls until the user authorizes or the code expires.
func PollDeviceFlow(ctx context.Context, client *http.Client, cfg FlowConfig, dc *DeviceCode) (map[string]any, error) {
	interval := time.Duration(max(dc.Interval, 5)) * time.Second
	deadline := time.Now().Add(time.Duration(dc.ExpiresIn) * time.Second)
	for time.Now().Before(deadline) {
		form := url.Values{
			"client_id":   {cfg.ClientID},
			"device_code": {dc.DeviceCode},
			"grant_type":  {"urn:ietf:params:oauth:grant-type:device_code"},
		}
		req, err := http.NewRequestWithContext(ctx, "POST", cfg.TokenURL, strings.NewReader(form.Encode()))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		req.Header.Set("Accept", "application/json")
		resp, err := client.Do(req)
		if err != nil {
			return nil, err
		}
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
		resp.Body.Close()
		var out map[string]any
		if err := json.Unmarshal(raw, &out); err == nil {
			if tok, ok := out["access_token"].(string); ok && tok != "" {
				return out, nil
			}
			if e, _ := out["error"].(string); e == "authorization_pending" || e == "slow_down" {
				select {
				case <-ctx.Done():
					return nil, ctx.Err()
				case <-time.After(interval):
					continue
				}
			}
			return nil, fmt.Errorf("auth: device flow: %v", out["error"])
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(interval):
		}
	}
	return nil, fmt.Errorf("auth: device flow expired")
}

// OpenBrowser opens a URL in the system browser.
func OpenBrowser(u string) error {
	return exec.Command("open", u).Start()
}
