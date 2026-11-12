package telemetry

import "sync"

// ChannelIDs maps a channel's UUID to its numeric primary key, which is the
// only identity that reaches a label, an attribute or a log field (D7, D9).
// The relay fills it when a channel is published and empties it when the
// channel is removed. The zero value is ready to use and safe for concurrent
// use.
type ChannelIDs struct {
	mu sync.RWMutex
	m  map[string]int
}

// Set records id for uuid.
func (c *ChannelIDs) Set(uuid string, id int) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.m == nil {
		c.m = map[string]int{}
	}
	c.m[uuid] = id
}

// Delete forgets uuid.
func (c *ChannelIDs) Delete(uuid string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	delete(c.m, uuid)
}

// Get returns the numeric id of uuid, 0 when it is unknown.
func (c *ChannelIDs) Get(uuid string) int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.m[uuid]
}

// Len is the number of channels held; a test uses it to see a removal.
func (c *ChannelIDs) Len() int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return len(c.m)
}
