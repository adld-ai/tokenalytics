package routing

import "sync/atomic"

// atomicTable is an atomic.Pointer[table] with a friendlier name at
// the call sites.
type atomicTable struct {
	p atomic.Pointer[table]
}

func (a *atomicTable) Load() *table   { return a.p.Load() }
func (a *atomicTable) Store(t *table) { a.p.Store(t) }
