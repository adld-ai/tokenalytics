// Package api is the management REST surface (spec 5.5, S14-S15).
// Every /api route requires the loopback bearer token; payloads use a
// deny-by-default schema — only the declared fields can ever marshal,
// and a test scans emitted payloads for token-shaped strings.
package api

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"tokenbar/internal/harvest"
	"tokenbar/internal/pool"
	"tokenbar/internal/routing"
)

// FlowRunner executes a provider login flow (M2); injectable so tests
// never touch real OAuth endpoints.
type FlowRunner interface {
	Run(ctx context.Context, provider string) (pool.Account, pool.TokenSet, error)
}

// Server wires the pool and router to HTTP.
type Server struct {
	Pool       *pool.Pool
	Router     *routing.Router
	Token      string
	Mux        *http.ServeMux
	Engine     *harvest.Engine // optional: quota display (M2)
	FlowRunner FlowRunner      // optional: OAuth/device login (M2)
}

func New(p *pool.Pool, r *routing.Router, token string) *Server {
	s := &Server{Pool: p, Router: r, Token: token, Mux: http.NewServeMux()}
	s.Mux.Handle("POST /api/v1/accounts", s.auth(http.HandlerFunc(s.addAccount)))
	s.Mux.Handle("DELETE /api/v1/accounts/{id}", s.auth(http.HandlerFunc(s.removeAccount)))
	s.Mux.Handle("POST /api/v1/routing/{provider}/pin", s.auth(http.HandlerFunc(s.pin)))
	s.Mux.Handle("GET /api/v1/state", s.auth(http.HandlerFunc(s.state)))
	s.Mux.Handle("GET /api/v1/health", s.auth(http.HandlerFunc(s.health)))
	return s
}

func (s *Server) auth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		if s.Token == "" || subtle.ConstantTimeCompare([]byte(got), []byte(s.Token)) != 1 {
			http.Error(w, `{"error":"unauthorized"}`, http.StatusUnauthorized)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

// --- Payload schema (S15, deny-by-default) ---
// Only these structs may cross the API boundary. There is no field
// that can carry token material; adding one requires editing this
// block and failing TestPayloadsContainNoTokenMaterial.

type AccountPayload struct {
	ID        int64  `json:"id"`
	Provider  string `json:"provider"`
	Email     string `json:"email,omitempty"`
	Label     string `json:"label,omitempty"`
	Plan      string `json:"plan,omitempty"`
	AccountID string `json:"account_id,omitempty"`
	Disabled  bool   `json:"disabled"`
}

type RoutePayload struct {
	Policy     string  `json:"policy"`
	Pinned     int64   `json:"pinned,omitempty"`
	Candidates []int64 `json:"candidates"`
}

type CooldownPayload struct {
	AccountID int64 `json:"account_id"`
	Until     int64 `json:"until"`
}

type StatePayload struct {
	SchemaVersion int                       `json:"schema_version"`
	GeneratedAt   string                    `json:"generated_at"`
	Accounts      []AccountPayload          `json:"accounts"`
	Routing       map[string]RoutePayload   `json:"routing"`
	Cooldowns     []CooldownPayload         `json:"cooldowns,omitempty"`
	Windows       map[int64][]WindowPayload `json:"windows,omitempty"`
}

// WindowPayload is one quota window for display (advisory only, S4).
type WindowPayload struct {
	Kind    string   `json:"kind"`
	Label   string   `json:"label,omitempty"`
	UsedPct *float64 `json:"used_pct,omitempty"`
	ResetAt *float64 `json:"reset_at,omitempty"`
	WindowS int64    `json:"window_s,omitempty"`
}

type HealthPayload struct {
	OK      bool   `json:"ok"`
	Uptime  string `json:"uptime"`
	Version int    `json:"schema_version"`
}

// --- handlers ---

// addAccountRequest is import-only in M1 (OAuth flows land in M2):
// the caller supplies credential material directly.
type addAccountRequest struct {
	Provider     string  `json:"provider"`
	Email        string  `json:"email"`
	Label        string  `json:"label"`
	Plan         string  `json:"plan"`
	AccountID    string  `json:"account_id"`
	AccessToken  string  `json:"access_token"`
	RefreshToken string  `json:"refresh_token"`
	IDToken      string  `json:"id_token"`
	ExpiresAt    float64 `json:"expires_at"`
	Flow         string  `json:"flow"` // "": direct import | "oauth" | "device" (M2)
}

func (s *Server) addAccount(w http.ResponseWriter, r *http.Request) {
	var req addAccountRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"bad json"}`, http.StatusBadRequest)
		return
	}
	if req.Flow != "" {
		s.addAccountViaFlow(w, r, req.Provider)
		return
	}
	if req.Provider == "" || (req.AccountID == "" && req.Email == "") {
		http.Error(w, `{"error":"provider and identity required"}`, http.StatusBadRequest)
		return
	}
	id, err := s.Pool.Add(pool.Account{
		Provider: req.Provider, Email: req.Email, Label: req.Label,
		Plan: req.Plan, AccountID: req.AccountID,
	}, pool.TokenSet{
		AccessToken: req.AccessToken, RefreshToken: req.RefreshToken,
		IDToken: req.IDToken, ExpiresAt: req.ExpiresAt,
	})
	if err != nil {
		http.Error(w, `{"error":`+strconv.Quote(err.Error())+`}`, http.StatusConflict)
		return
	}
	s.RebuildRoutes()
	writeJSON(w, http.StatusCreated, AccountPayload{ID: id, Provider: req.Provider, Email: req.Email})
}

// addAccountViaFlow runs a provider login flow (OAuth browser /
// device) synchronously behind POST /api/v1/accounts (M2). Human-paced
// by construction: one flow at a time per server (S26).
func (s *Server) addAccountViaFlow(w http.ResponseWriter, r *http.Request, provider string) {
	if s.FlowRunner == nil {
		http.Error(w, `{"error":"flows unavailable"}`, http.StatusNotImplemented)
		return
	}
	if provider == "" {
		http.Error(w, `{"error":"provider required"}`, http.StatusBadRequest)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Minute)
	defer cancel()
	acct, ts, err := s.FlowRunner.Run(ctx, provider)
	if err != nil {
		http.Error(w, `{"error":`+strconv.Quote(err.Error())+`}`, http.StatusBadGateway)
		return
	}
	id, err := s.Pool.Add(acct, ts)
	if err != nil {
		http.Error(w, `{"error":`+strconv.Quote(err.Error())+`}`, http.StatusConflict)
		return
	}
	s.RebuildRoutes()
	writeJSON(w, http.StatusCreated, AccountPayload{
		ID: id, Provider: acct.Provider, Email: acct.Email, AccountID: acct.AccountID,
	})
}

func (s *Server) removeAccount(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		http.Error(w, `{"error":"bad id"}`, http.StatusBadRequest)
		return
	}
	if err := s.Pool.Remove(id); err != nil {
		if errors.Is(err, pool.ErrNotFound) {
			http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
			return
		}
		http.Error(w, `{"error":`+strconv.Quote(err.Error())+`}`, http.StatusInternalServerError)
		return
	}
	s.Router.RemoveAccount(id)
	s.RebuildRoutes()
	w.WriteHeader(http.StatusNoContent)
}

type pinRequest struct {
	AccountID int64 `json:"account_id"`
}

func (s *Server) pin(w http.ResponseWriter, r *http.Request) {
	provider := r.PathValue("provider")
	var req pinRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.AccountID == 0 {
		http.Error(w, `{"error":"account_id required"}`, http.StatusBadRequest)
		return
	}
	if err := s.Router.Pin(provider, req.AccountID); err != nil {
		http.Error(w, `{"error":`+strconv.Quote(err.Error())+`}`, http.StatusConflict)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// RebuildRoutes refreshes the routing table from the pool. Serialized
// through management handlers only; applied via atomic swap (S6).
func (s *Server) RebuildRoutes() {
	accts, err := s.Pool.List()
	if err != nil {
		return
	}
	byProvider := map[string][]int64{}
	for _, a := range accts {
		if a.Disabled {
			continue
		}
		byProvider[a.Provider] = append(byProvider[a.Provider], a.ID)
	}
	existing := s.Router.Routes()
	for provider, candidates := range byProvider {
		policy := routing.PolicyPin
		pinned := int64(0)
		if cur, ok := existing[provider]; ok {
			policy = cur.Policy
			for _, c := range candidates {
				if c == cur.Pinned {
					pinned = c
				}
			}
		}
		if pinned == 0 && len(candidates) > 0 {
			pinned = candidates[0]
		}
		s.Router.SetAccounts(provider, policy, pinned, candidates)
	}
}

func (s *Server) state(w http.ResponseWriter, _ *http.Request) {
	accts, err := s.Pool.List()
	if err != nil {
		http.Error(w, `{"error":`+strconv.Quote(err.Error())+`}`, http.StatusInternalServerError)
		return
	}
	payload := StatePayload{
		SchemaVersion: 1,
		GeneratedAt:   time.Now().UTC().Format(time.RFC3339),
		Accounts:      []AccountPayload{},
		Routing:       map[string]RoutePayload{},
	}
	for _, a := range accts {
		payload.Accounts = append(payload.Accounts, AccountPayload{
			ID: a.ID, Provider: a.Provider, Email: a.Email, Label: a.Label,
			Plan: a.Plan, AccountID: a.AccountID, Disabled: a.Disabled,
		})
		if s.Engine != nil {
			ws, err := s.Engine.LatestWindows(a.ID)
			if err == nil && len(ws) > 0 {
				if payload.Windows == nil {
					payload.Windows = map[int64][]WindowPayload{}
				}
				for _, qw := range ws {
					payload.Windows[a.ID] = append(payload.Windows[a.ID], WindowPayload{
						Kind: qw.Kind, Label: qw.Label,
						UsedPct: qw.UsedPct, ResetAt: qw.ResetAt, WindowS: qw.WindowS,
					})
				}
			}
		}
	}
	for provider, ri := range s.Router.Routes() {
		payload.Routing[provider] = RoutePayload{
			Policy: string(ri.Policy), Pinned: ri.Pinned, Candidates: ri.Candidates,
		}
	}
	for id, until := range s.Router.Cooldowns() {
		payload.Cooldowns = append(payload.Cooldowns, CooldownPayload{
			AccountID: id, Until: until.Unix(),
		})
	}
	writeJSON(w, http.StatusOK, payload)
}

var startedAt = time.Now()

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, HealthPayload{
		OK: true, Uptime: time.Since(startedAt).Round(time.Second).String(), Version: 1,
	})
}
