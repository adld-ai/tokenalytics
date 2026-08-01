// Package routing owns per-provider account selection (spec 5.3,
// S7-S10, S19, S24). The table is swapped atomically (S6) so the
// request path takes no locks shared with management paths.
package routing

import (
	"errors"
	"sort"
	"sync"
	"time"
)

// Policy is a provider routing mode.
type Policy string

const (
	PolicyPin       Policy = "pin"        // default (S9): manual selection, no auto failover
	PolicyFillFirst Policy = "fill-first" // stay on one account until it cools down
)

// Credential is a routable account pick.
type Credential struct {
	AccountID int64
}

var (
	ErrNoCandidates = errors.New("routing: no available accounts")
	ErrUnknownKind  = errors.New("routing: unknown provider")
)

type providerRoute struct {
	Policy     Policy
	Pinned     int64
	Candidates []int64
}

// table is immutable; updates build a new one and swap it in.
type table struct {
	providers map[string]*providerRoute
}

type cooldown struct {
	reason string
	until  time.Time
}

// Router picks accounts and tracks hard-signal cooldowns.
type Router struct {
	mu    sync.Mutex // guards table rebuilds only; reads are lock-free
	tbl   atomicTable
	cdMu  sync.Mutex
	cools map[int64]cooldown
	now   func() time.Time
}

func New() *Router {
	r := &Router{
		cools: map[int64]cooldown{},
		now:   time.Now,
	}
	r.tbl.Store(&table{providers: map[string]*providerRoute{}})
	return r
}

// SetAccounts replaces a provider's candidate list and policy via an
// atomic table swap (S6).
func (r *Router) SetAccounts(provider string, policy Policy, pinned int64, candidates []int64) {
	r.mu.Lock()
	defer r.mu.Unlock()
	old := r.tbl.Load()
	next := &table{providers: make(map[string]*providerRoute, len(old.providers)+1)}
	for k, v := range old.providers {
		next.providers[k] = v
	}
	cp := append([]int64(nil), candidates...)
	sort.Slice(cp, func(i, j int) bool { return cp[i] < cp[j] })
	next.providers[provider] = &providerRoute{Policy: policy, Pinned: pinned, Candidates: cp}
	r.tbl.Store(next)
}

// RemoveAccount drops an account from every provider's route (called
// when the pool deletes it).
func (r *Router) RemoveAccount(id int64) {
	r.mu.Lock()
	defer r.mu.Unlock()
	old := r.tbl.Load()
	next := &table{providers: make(map[string]*providerRoute, len(old.providers))}
	for k, v := range old.providers {
		cp := make([]int64, 0, len(v.Candidates))
		for _, c := range v.Candidates {
			if c != id {
				cp = append(cp, c)
			}
		}
		pinned := v.Pinned
		if pinned == id {
			pinned = 0
		}
		next.providers[k] = &providerRoute{Policy: v.Policy, Pinned: pinned, Candidates: cp}
	}
	r.tbl.Store(next)
	r.cdMu.Lock()
	delete(r.cools, id)
	r.cdMu.Unlock()
}

// Pin sets the pinned account for a provider (S24).
func (r *Router) Pin(provider string, accountID int64) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	old := r.tbl.Load()
	rt, ok := old.providers[provider]
	if !ok {
		return ErrUnknownKind
	}
	found := false
	for _, c := range rt.Candidates {
		if c == accountID {
			found = true
		}
	}
	if !found {
		return ErrNoCandidates
	}
	next := &table{providers: make(map[string]*providerRoute, len(old.providers))}
	for k, v := range old.providers {
		next.providers[k] = v
	}
	cp := *rt
	cp.Pinned = accountID
	next.providers[provider] = &cp
	r.tbl.Store(next)
	return nil
}

func (r *Router) cooled(id int64) bool {
	r.cdMu.Lock()
	defer r.cdMu.Unlock()
	cd, ok := r.cools[id]
	if !ok {
		return false
	}
	if r.now().After(cd.until) {
		delete(r.cools, id) // TTL eviction on read
		return false
	}
	return true
}

// Pick selects the account for one request. With PolicyPin it returns
// the pinned account or an error — automatic failover is opt-in (S9).
// With PolicyFillFirst it returns the first non-cooling candidate.
func (r *Router) Pick(provider string) (Credential, error) {
	rt, ok := r.tbl.Load().providers[provider]
	if !ok {
		return Credential{}, ErrUnknownKind
	}
	switch rt.Policy {
	case PolicyPin:
		if rt.Pinned == 0 {
			return Credential{}, ErrNoCandidates
		}
		if r.cooled(rt.Pinned) {
			return Credential{}, ErrNoCandidates
		}
		return Credential{AccountID: rt.Pinned}, nil
	case PolicyFillFirst:
		for _, c := range rt.Candidates {
			if !r.cooled(c) {
				return Credential{AccountID: c}, nil
			}
		}
		return Credential{}, ErrNoCandidates
	}
	return Credential{}, ErrUnknownKind
}

// NextAfter returns the next candidate after prev for a failover
// retry (at most one retry per request, S8).
func (r *Router) NextAfter(provider string, prev int64) (Credential, error) {
	rt, ok := r.tbl.Load().providers[provider]
	if !ok {
		return Credential{}, ErrUnknownKind
	}
	for _, c := range rt.Candidates {
		if c != prev && !r.cooled(c) {
			return Credential{AccountID: c}, nil
		}
	}
	return Credential{}, ErrNoCandidates
}

// HardSignal reports whether a status code is a definitive quota/auth
// rejection (S7). Timeouts and 5xx are never failover triggers.
func HardSignal(status int) bool {
	return status == 429 || status == 401 || status == 403
}

// Cooldown enters an account into cooldown derived only from a real
// upstream rejection (S10). ttl comes from the provider's reset hint.
func (r *Router) Cooldown(accountID int64, reason string, ttl time.Duration) {
	if ttl <= 0 {
		ttl = 5 * time.Minute
	}
	r.cdMu.Lock()
	r.cools[accountID] = cooldown{reason: reason, until: r.now().Add(ttl)}
	r.cdMu.Unlock()
}

// Cooldowns snapshots the active cooldown table (for /state display).
func (r *Router) Cooldowns() map[int64]time.Time {
	r.cdMu.Lock()
	defer r.cdMu.Unlock()
	out := map[int64]time.Time{}
	for id, cd := range r.cools {
		if r.now().Before(cd.until) {
			out[id] = cd.until
		}
	}
	return out
}

// RouteInfo is the display view of one provider's route.
type RouteInfo struct {
	Policy     Policy
	Pinned     int64
	Candidates []int64
}

// Routes snapshots the whole table.
func (r *Router) Routes() map[string]RouteInfo {
	out := map[string]RouteInfo{}
	for k, v := range r.tbl.Load().providers {
		out[k] = RouteInfo{
			Policy:     v.Policy,
			Pinned:     v.Pinned,
			Candidates: append([]int64(nil), v.Candidates...),
		}
	}
	return out
}
