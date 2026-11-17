// Package contextbuffer keeps a bounded, in-memory window of most-recent
// normal events per website/agent/source partition so that problem events
// can be given prior normal context. It is thread safe, deterministic under
// its configured caps, and uses no goroutines, disk, or external
// dependencies.
package contextbuffer

import (
	"errors"
	"sort"
	"sync"
	"time"
	"unicode/utf8"

	"ai-log-server/server/gateway/internal/classifier"
)

const (
	DefaultTTL                   = 5 * time.Minute
	DefaultMaxEventsPerPartition = 200
	DefaultMaxTotalEvents        = 20000
	DefaultMaxPartitions         = 2048
	DefaultMaxContextLines       = 20
	MaxMessageBytes              = 8 * 1024
)

// NormalSeverity is the only classification severity Append accepts.
const NormalSeverity = "normal"

// Config bounds a Buffer. All fields must be positive.
type Config struct {
	TTL                   time.Duration
	MaxEventsPerPartition int
	MaxTotalEvents        int
	MaxPartitions         int
	MaxContextLines       int
}

// Line is one stored normal event, oldest-to-newest order.
type Line struct {
	Timestamp time.Time `json:"timestamp"`
	Message   string    `json:"message"`
	Service   string    `json:"service"`
	LogType   string    `json:"log_type"`
	SourceID  string    `json:"source_id"`
}

// Metrics is a point-in-time snapshot of the buffer.
type Metrics struct {
	Partitions        int64 `json:"partitions"`
	Events            int64 `json:"events"`
	ExpiredEvictions  int64 `json:"expired_evictions"`
	CapacityEvictions int64 `json:"capacity_evictions"`
	RejectedNonNormal int64 `json:"rejected_non_normal"`
}

type option struct {
	now func() time.Time
}

// Option configures a Buffer.
type Option func(*option)

// WithClock overrides the time source, used for deterministic TTL tests.
func WithClock(now func() time.Time) Option {
	return func(o *option) { o.now = now }
}

func defaultConfig() Config {
	return Config{
		TTL:                   DefaultTTL,
		MaxEventsPerPartition: DefaultMaxEventsPerPartition,
		MaxTotalEvents:        DefaultMaxTotalEvents,
		MaxPartitions:         DefaultMaxPartitions,
		MaxContextLines:       DefaultMaxContextLines,
	}
}

// New returns a Buffer with default limits.
func New(opts ...Option) *Buffer {
	b, err := NewWithConfig(defaultConfig(), opts...)
	if err != nil {
		panic(err)
	}
	return b
}

// NewWithConfig returns a Buffer with the given limits, or an error when any
// limit is non-positive.
func NewWithConfig(cfg Config, opts ...Option) (*Buffer, error) {
	if cfg.TTL <= 0 || cfg.MaxEventsPerPartition <= 0 || cfg.MaxTotalEvents <= 0 || cfg.MaxPartitions <= 0 || cfg.MaxContextLines <= 0 {
		return nil, errors.New("contextbuffer: config values must be positive")
	}
	var o option
	for _, apply := range opts {
		if apply != nil {
			apply(&o)
		}
	}
	if o.now == nil {
		o.now = time.Now
	}
	return &Buffer{
		cfg:   cfg,
		now:   o.now,
		parts: make(map[key]*partition),
	}, nil
}

type key struct {
	websiteID string
	agentID   string
	sourceID  string
}

type entry struct {
	seq      uint64
	ts       time.Time
	storedAt time.Time
	message  string
	service  string
	logType  string
	sourceID string
}

type partition struct {
	entries []entry
}

type Buffer struct {
	mu    sync.Mutex
	cfg   Config
	now   func() time.Time
	next  uint64
	parts map[key]*partition
	total int

	expiredEvictions  int64
	capacityEvictions int64
	rejectedNonNormal int64
}

// Append stores ev when severity is exactly "normal" (the classification
// severity). The message is trimmed to MaxMessageBytes. It reports whether
// the event was stored.
func (b *Buffer) Append(ev classifier.Event, severity string) bool {
	if severity != NormalSeverity {
		b.mu.Lock()
		b.rejectedNonNormal++
		b.mu.Unlock()
		return false
	}

	b.mu.Lock()
	defer b.mu.Unlock()

	now := b.now()
	b.purgeExpired(now)

	k := key{websiteID: ev.WebsiteID, agentID: ev.AgentID, sourceID: ev.SourceID}
	p, ok := b.parts[k]
	if !ok {
		p = b.newPartition(k)
	}

	ts := ev.Timestamp
	if ts.IsZero() {
		ts = now
	}
	b.next++
	e := entry{
		seq:      b.next,
		ts:       ts,
		storedAt: now,
		message:  trimMessage(ev.Message),
		service:  ev.Service,
		logType:  ev.LogType,
		sourceID: ev.SourceID,
	}
	p.entries = insertEntry(p.entries, e)
	b.total++

	for b.total > b.cfg.MaxTotalEvents {
		if !b.evictOldestEntry() {
			break
		}
		b.capacityEvictions++
	}
	for len(p.entries) > b.cfg.MaxEventsPerPartition {
		p.entries = p.entries[1:]
		b.total--
		b.capacityEvictions++
	}

	return true
}

// ContextFor returns the newest up to MaxContextLines prior lines from the
// exact website/agent/source partition of ev, ordered oldest-to-newest.
// Lines are excluded when expired or not strictly before ev's timestamp.
func (b *Buffer) ContextFor(ev classifier.Event) []Line {
	b.mu.Lock()
	defer b.mu.Unlock()

	now := b.now()
	b.purgeExpired(now)

	p, ok := b.parts[key{websiteID: ev.WebsiteID, agentID: ev.AgentID, sourceID: ev.SourceID}]
	if !ok {
		return nil
	}

	ts := ev.Timestamp
	if ts.IsZero() {
		ts = now
	}
	cut := sort.Search(len(p.entries), func(i int) bool {
		return !p.entries[i].ts.Before(ts)
	})
	if cut == 0 {
		return nil
	}
	start := cut - b.cfg.MaxContextLines
	if start < 0 {
		start = 0
	}
	lines := make([]Line, cut-start)
	for i, e := range p.entries[start:cut] {
		lines[i] = Line{
			Timestamp: e.ts,
			Message:   e.message,
			Service:   e.service,
			LogType:   e.logType,
			SourceID:  e.sourceID,
		}
	}
	return lines
}

// Snapshot returns live metrics. Expired entries are purged first.
func (b *Buffer) Snapshot() Metrics {
	b.mu.Lock()
	defer b.mu.Unlock()

	b.purgeExpired(b.now())

	return Metrics{
		Partitions:        int64(len(b.parts)),
		Events:            int64(b.total),
		ExpiredEvictions:  b.expiredEvictions,
		CapacityEvictions: b.capacityEvictions,
		RejectedNonNormal: b.rejectedNonNormal,
	}
}

func (b *Buffer) newPartition(k key) *partition {
	if len(b.parts) >= b.cfg.MaxPartitions {
		b.evictOldestPartition()
	}
	p := &partition{}
	b.parts[k] = p
	return p
}

func (b *Buffer) purgeExpired(now time.Time) {
	for k, p := range b.parts {
		kept := p.entries[:0]
		for _, candidate := range p.entries {
			if expiredEntry(candidate, now, b.cfg.TTL) {
				b.expiredEvictions++
				b.total--
				continue
			}
			kept = append(kept, candidate)
		}
		p.entries = kept
		if len(p.entries) == 0 {
			delete(b.parts, k)
		}
	}
}

func (b *Buffer) evictOldestEntry() bool {
	var oldestKey key
	var oldest *partition
	oldestIndex := -1
	for k, p := range b.parts {
		if len(p.entries) == 0 {
			delete(b.parts, k)
			continue
		}
		for i := range p.entries {
			if oldest == nil || p.entries[i].seq < oldest.entries[oldestIndex].seq {
				oldest = p
				oldestKey = k
				oldestIndex = i
			}
		}
	}
	if oldest == nil {
		return false
	}
	oldest.entries = append(oldest.entries[:oldestIndex], oldest.entries[oldestIndex+1:]...)
	b.total--
	if len(oldest.entries) == 0 {
		delete(b.parts, oldestKey)
	}
	return true
}

func (b *Buffer) evictOldestPartition() {
	var oldestKey key
	var oldest *partition
	for k, p := range b.parts {
		if len(p.entries) == 0 {
			delete(b.parts, k)
			continue
		}
		if oldest == nil || firstSequence(p) < firstSequence(oldest) {
			oldest = p
			oldestKey = k
		}
	}
	if oldest == nil {
		return
	}
	b.capacityEvictions += int64(len(oldest.entries))
	b.total -= len(oldest.entries)
	delete(b.parts, oldestKey)
}

func expiredEntry(e entry, now time.Time, ttl time.Duration) bool {
	return !now.Before(e.storedAt.Add(ttl))
}

func firstSequence(p *partition) uint64 {
	first := p.entries[0].seq
	for _, candidate := range p.entries[1:] {
		if candidate.seq < first {
			first = candidate.seq
		}
	}
	return first
}

func less(a, b entry) bool {
	if a.ts.Before(b.ts) {
		return true
	}
	if b.ts.Before(a.ts) {
		return false
	}
	return a.seq < b.seq
}

func insertEntry(entries []entry, e entry) []entry {
	i := sort.Search(len(entries), func(i int) bool {
		return less(e, entries[i])
	})
	entries = append(entries, entry{})
	copy(entries[i+1:], entries[i:])
	entries[i] = e
	return entries
}

func trimMessage(msg string) string {
	if len(msg) <= MaxMessageBytes {
		return msg
	}
	trimmed := msg[:MaxMessageBytes]
	for len(trimmed) > 0 && !utf8.ValidString(trimmed) {
		trimmed = trimmed[:len(trimmed)-1]
	}
	return trimmed
}
