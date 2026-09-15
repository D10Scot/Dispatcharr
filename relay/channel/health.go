package channel

import (
	"context"
	"time"
)

// dataClock is the sink a source writes into: the ring, with the channel's
// last-data timestamp refreshed on every write -- input/manager.py:1367's
// `self.last_data_time = time.time()` after every successful fetch_chunk.
// Every byte an upstream hands over passes through here, so "no data for
// N seconds" is measured from the last byte, not the last chunk.
type dataClock struct{ c *Channel }

func (d dataClock) Write(p []byte) (int, error) {
	d.c.mu.Lock()
	d.c.lastData = d.c.now()
	d.c.mu.Unlock()
	return d.c.ring.Write(p)
}

// Healthy is StreamManager.healthy: true from the moment a connection is
// up until the health monitor sees no data for longer than the inactivity
// threshold, and true again when data resumes. It gates the keepalives and
// the client timeout (output/ts/generator.py:549-551, :592), and it is the
// `healthy` field on GET /proxy/relay/channels (channel_status.py:527-529).
func (c *Channel) Healthy() bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.healthy
}

// inactivityThreshold is _health_inactivity_threshold (input/manager.py:
// 1547-1551): the init grace period while a connection is up and the ring
// is still empty, CONNECTION_TIMEOUT otherwise. Called with mu held.
func (c *Channel) inactivityThreshold() time.Duration {
	if c.connected && c.ring.Head() == 0 {
		return c.tuning.InitGracePeriod
	}
	return c.tuning.ConnectionTimeout
}

// monitorHealth is _monitor_health (input/manager.py:1553-1609): every
// HealthCheckInterval, compare the time since the last byte against the
// threshold; after maxUnhealthyChecks consecutive failures and outside the
// cooldown, ask the run loop for a reconnect (a stream that had been stable)
// or a switch (one that had not) -- parity-matrix row 2.
//
// WHERE IT DIFFERS: Python sets a flag the main loop notices between
// fetch_chunk calls (:1364-1365), each of which blocks up to CHUNK_TIMEOUT
// (5s) in select on a silent pipe (:1845), so the loop acts up to five
// seconds after the flag. This
// monitor sets the same flag and CANCELS the running attempt, so the loop
// acts at once. A divergence in the safe direction, stated rather than
// reproduced: CHUNK_TIMEOUT is not read.
func (c *Channel) monitorHealth(ctx context.Context) {
	interval := max(c.tuning.HealthCheckInterval, time.Millisecond)
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	unhealthyChecks := 0
	var lastAction time.Time
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}

		c.mu.Lock()
		now := c.now()
		inactivity := now.Sub(c.lastData)
		threshold := c.inactivityThreshold()
		var cancel context.CancelFunc

		switch {
		case inactivity > threshold && c.connected:
			if c.healthy {
				c.log.Warn("stream unhealthy: no data", "channel", c.id, "inactive", inactivity.Round(100*time.Millisecond))
				c.healthy = false
			}
			unhealthyChecks++
			if unhealthyChecks >= maxUnhealthyChecks && now.Sub(lastAction) > healthActionCooldown {
				stableFor := c.lastData.Sub(c.connStart)
				switch healthActionFor(stableFor) {
				case actionReconnect:
					if !c.needsReconnect {
						c.log.Info("health monitor: reconnecting a stream that had been stable", "channel", c.id, "stable", stableFor.Round(time.Second))
						c.needsReconnect = true
						lastAction = now
						cancel = c.cancelAttempt
					}
				case actionSwitch:
					if !c.needsSwitch {
						c.log.Info("health monitor: switching an unstable stream", "channel", c.id, "stable", stableFor.Round(time.Second))
						c.needsSwitch = true
						lastAction = now
						cancel = c.cancelAttempt
					}
				}
				unhealthyChecks = 0
			}
		case c.connected && !c.healthy:
			c.log.Info("stream health restored: data resumed", "channel", c.id, "after", inactivity.Round(100*time.Millisecond))
			c.healthy = true
			unhealthyChecks = 0
			c.needsReconnect = false
			c.needsSwitch = false
		}
		if c.healthy {
			unhealthyChecks = 0
		}
		c.mu.Unlock()

		if cancel != nil {
			cancel()
		}
	}
}

// takeFlag reads and clears one of the two recovery flags under the lock.
func (c *Channel) takeFlag(flag *bool) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	set := *flag
	*flag = false
	return set
}

func (c *Channel) flagSet(flag *bool) bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return *flag
}
