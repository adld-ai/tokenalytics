// Package idlepoll is the human-shaped idle poller (S22): interval
// ≥ 15 min with ±20% jitter, strictly serialized per provider,
// accounts with recent request-path harvest are skipped, and any 429
// backs off exponentially. One scheduler goroutine with a next-due
// heap feeds a worker pool of 4 (12.3). No heartbeat traffic (S20).
package idlepoll

import (
	"container/heap"
	"context"
	"log"
	"math/rand"
	"sync"
	"time"

	"tokenbar/internal/harvest"
	"tokenbar/internal/pool"
	"tokenbar/internal/quota"
)

// Prober fetches one account's quota snapshot using the provider's own
// endpoint shapes.
type Prober interface {
	Probe(ctx context.Context, a pool.Account) (quota.Snapshot, error)
}

// RateLimitError marks a 429 from a probe; the scheduler backs off.
type RateLimitError struct{ Provider string }

func (e RateLimitError) Error() string { return "idlepoll: 429 from " + e.Provider }

type item struct {
	accountID int64
	provider  string
	due       time.Time
	backoff   int // consecutive 429s
	index     int
}

type dueHeap []*item

func (h dueHeap) Len() int           { return len(h) }
func (h dueHeap) Less(i, j int) bool { return h[i].due.Before(h[j].due) }
func (h dueHeap) Swap(i, j int) {
	h[i], h[j] = h[j], h[i]
	h[i].index, h[j].index = i, j
}
func (h *dueHeap) Push(x any) { it := x.(*item); it.index = len(*h); *h = append(*h, it) }
func (h *dueHeap) Pop() any {
	old := *h
	n := len(old)
	it := old[n-1]
	old[n-1] = nil
	*h = old[:n-1]
	return it
}

// Scheduler runs the idle poll.
type Scheduler struct {
	Pool     *pool.Pool
	Engine   *harvest.Engine
	Probers  map[string]Prober
	Interval time.Duration // >= 15 min in production (S22)
	Workers  int
	Logger   *log.Logger

	now    func() time.Time
	jitter func() float64 // 0.8..1.2 in production
	rnd    *rand.Rand
}

func New(p *pool.Pool, e *harvest.Engine, probers map[string]Prober, logger *log.Logger) *Scheduler {
	if logger == nil {
		logger = log.Default()
	}
	s := &Scheduler{
		Pool: p, Engine: e, Probers: probers,
		Interval: 15 * time.Minute, Workers: 4, Logger: logger,
		now: time.Now, rnd: rand.New(rand.NewSource(time.Now().UnixNano())),
	}
	s.jitter = func() float64 { return 1 + (s.rnd.Float64()*0.4 - 0.2) } // ±20%
	return s
}

// Run starts the scheduler loop and workers until ctx is canceled.
func (s *Scheduler) Run(ctx context.Context) {
	accts, err := s.Pool.List()
	if err != nil {
		s.Logger.Printf("idlepoll: list accounts: %v", err)
		return
	}
	h := &dueHeap{}
	now := s.now()
	n := max(len(accts), 1)
	i := 0
	for _, a := range accts {
		if a.Disabled {
			continue
		}
		if _, ok := s.Probers[a.Provider]; !ok {
			continue // no probe for this provider: never guessed traffic
		}
		// Stagger initial due times across one interval so the fleet
		// never fires in sync (E9).
		due := now.Add(time.Duration(float64(s.Interval) * float64(i) / float64(n)))
		heap.Push(h, &item{accountID: a.ID, provider: a.Provider, due: due})
		i++
	}

	jobs := make(chan *item, 16)
	var wg sync.WaitGroup
	var inflightMu sync.Mutex
	inflightProvider := map[string]bool{}
	for w := 0; w < s.Workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for it := range jobs {
				s.runOne(ctx, it)
				inflightMu.Lock()
				delete(inflightProvider, it.provider)
				inflightMu.Unlock()
			}
		}()
	}

	timer := time.NewTimer(time.Hour)
	defer timer.Stop()
	for {
		if h.Len() == 0 {
			select {
			case <-ctx.Done():
				close(jobs)
				wg.Wait()
				return
			case <-time.After(time.Minute):
				continue
			}
		}
		next := (*h)[0]
		wait := time.Until(next.due)
		if wait < 0 {
			wait = 0
		}
		timer.Reset(wait)
		select {
		case <-ctx.Done():
			close(jobs)
			wg.Wait()
			return
		case <-timer.C:
			it := heap.Pop(h).(*item)
			// Skip accounts with recent request-path harvest (S22).
			if last := s.Engine.LastObservation(it.accountID); s.now().Sub(last) < s.Interval {
				s.Logger.Printf("idlepoll: skip account=%d (harvest %s ago)",
					it.accountID, s.now().Sub(last).Round(time.Second))
				it.due = s.now().Add(time.Duration(float64(s.Interval) * s.jitter()))
				heap.Push(h, it)
				continue
			}
			// Strict per-provider serialization.
			inflightMu.Lock()
			if inflightProvider[it.provider] {
				inflightMu.Unlock()
				it.due = s.now().Add(30 * time.Second)
				heap.Push(h, it)
				continue
			}
			inflightProvider[it.provider] = true
			inflightMu.Unlock()
			select {
			case jobs <- it:
			case <-ctx.Done():
				close(jobs)
				wg.Wait()
				return
			}
			// Reschedule with jittered interval, stretched by backoff.
			mult := float64(int64(1) << min(it.backoff, 4))
			it.due = s.now().Add(time.Duration(float64(s.Interval) * s.jitter() * mult))
			heap.Push(h, it)
		}
	}
}

func (s *Scheduler) runOne(ctx context.Context, it *item) {
	a, err := s.Pool.Get(it.accountID)
	if err != nil {
		return // deleted between scheduling and run: drop silently
	}
	prober := s.Probers[it.provider]
	start := s.now()
	snap, err := prober.Probe(ctx, a)
	if err != nil {
		if rl, ok := err.(RateLimitError); ok {
			it.backoff++
			s.Logger.Printf("idlepoll: account=%d provider=%s 429, backoff=%d",
				it.accountID, rl.Provider, it.backoff)
			return
		}
		s.Logger.Printf("idlepoll: account=%d provider=%s error: %v",
			it.accountID, it.provider, err)
		return
	}
	it.backoff = 0
	s.Engine.ApplySnapshot(it.accountID, snap)
	s.Logger.Printf("idlepoll: account=%d provider=%s ok in %s",
		it.accountID, it.provider, s.now().Sub(start).Round(time.Millisecond))
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
