package hls

import (
	"context"
	"sync"
)

// ctxLock is a mutex whose waiter can give up. The two process-wide locks --
// the Quick Sync detection and the canned silence encode -- are each held
// across a subprocess of up to 10 s, and a pipeline waiting behind another
// channel's must still be stoppable: a sync.Mutex would hold its Stop past
// stopJoinWait. The zero value is ready to use.
type ctxLock struct {
	once sync.Once
	ch   chan struct{}
}

// lock takes the lock, or returns ctx's error if ctx ends first.
func (l *ctxLock) lock(ctx context.Context) error {
	l.once.Do(func() { l.ch = make(chan struct{}, 1) })
	select {
	case l.ch <- struct{}{}:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// unlock releases a lock taken by lock.
func (l *ctxLock) unlock() { <-l.ch }
