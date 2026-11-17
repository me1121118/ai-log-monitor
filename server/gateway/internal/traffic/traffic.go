// Package traffic detects per-website traffic anomalies from HTTP
// observations. It is thread safe, deterministic under its configured caps,
// and uses no goroutines, disk, or external dependencies.
package traffic

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

const (
	DefaultWindow             = 60 * time.Second
	DefaultMinRequests        = 20
	DefaultErrorRateThreshold = 0.05
	DefaultP95LatencyMS       = 1000
	DefaultCooldown           = 300 * time.Second
	DefaultMaxGroups          = 4096
	DefaultMaxSamplesPerGroup = 256

	// MaxRouteBytes caps a normalized route, truncated to a valid UTF-8
	// boundary.
	MaxRouteBytes = 256

	// SeverityProblem and CategoryTrafficAnomaly label emitted anomalies.
	SeverityProblem        = "problem"
	CategoryTrafficAnomaly = "traffic_anomaly"
)

// Config bounds a Detector. All fields must be positive.
type Config struct {
	Window             time.Duration
	MinRequests        int
	ErrorRateThreshold float64
	P95LatencyMS       int
	Cooldown           time.Duration
	MaxGroups          int
	MaxSamplesPerGroup int
}

// Defaults returns the production configuration.
func Defaults() Config {
	return Config{
		Window:             DefaultWindow,
		MinRequests:        DefaultMinRequests,
		ErrorRateThreshold: DefaultErrorRateThreshold,
		P95LatencyMS:       DefaultP95LatencyMS,
		Cooldown:           DefaultCooldown,
		MaxGroups:          DefaultMaxGroups,
		MaxSamplesPerGroup: DefaultMaxSamplesPerGroup,
	}
}

func (c Config) validate() error {
	if c.Window <= 0 {
		return fmt.Errorf("traffic: window must be positive")
	}
	if c.MinRequests <= 0 {
		return fmt.Errorf("traffic: min requests must be positive")
	}
	if c.ErrorRateThreshold <= 0 || c.ErrorRateThreshold > 1 {
		return fmt.Errorf("traffic: error rate threshold must be in (0, 1]")
	}
	if c.P95LatencyMS <= 0 {
		return fmt.Errorf("traffic: p95 latency limit must be positive")
	}
	if c.Cooldown <= 0 {
		return fmt.Errorf("traffic: cooldown must be positive")
	}
	if c.MaxGroups <= 0 {
		return fmt.Errorf("traffic: max groups must be positive")
	}
	if c.MaxSamplesPerGroup <= 0 {
		return fmt.Errorf("traffic: max samples per group must be positive")
	}
	return nil
}

// Observation is one HTTP request seen by the gateway. Timestamp preserves
// the source event time for callers, but rolling-window retention uses the
// gateway arrival clock so delayed or skewed agents cannot corrupt windows.
// LatencyMS is optional; nil or negative means no latency was observed.
type Observation struct {
	WebsiteID  string    `json:"website_id"`
	AgentID    string    `json:"agent_id"`
	SourceID   string    `json:"source_id"`
	Method     string    `json:"method"`
	Path       string    `json:"path"`
	StatusCode int       `json:"status_code"`
	LatencyMS  *int      `json:"latency_ms,omitempty"`
	Timestamp  time.Time `json:"timestamp"`
}

// Anomaly describes a traffic degradation for one route group.
type Anomaly struct {
	WebsiteID      string  `json:"website_id"`
	AgentID        string  `json:"agent_id"`
	SourceID       string  `json:"source_id"`
	Route          string  `json:"route"`
	RequestCount   int     `json:"request_count"`
	Status5xxCount int     `json:"status_5xx_count"`
	ErrorRate      float64 `json:"error_rate"`
	P95LatencyMS   int     `json:"p95_latency_ms"`
	Reason         string  `json:"reason"`
	Severity       string  `json:"severity"`
	Category       string  `json:"category"`
	Fingerprint    string  `json:"fingerprint"`
}

// Metrics is a point-in-time snapshot of a Detector.
type Metrics struct {
	Groups             int   `json:"groups"`
	Observations       int64 `json:"observations"`
	Emitted            int64 `json:"emitted"`
	CooldownSuppressed int64 `json:"cooldown_suppressed"`
	CapacityEvictions  int64 `json:"capacity_evictions"`
}

type option struct {
	now func() time.Time
}

// Option configures a Detector.
type Option func(*option)

// WithClock overrides the time source, used for deterministic tests.
func WithClock(now func() time.Time) Option {
	return func(o *option) { o.now = now }
}

// New returns a Detector with default limits.
func New(opts ...Option) *Detector {
	d, err := NewWithConfig(Defaults(), opts...)
	if err != nil {
		panic(err)
	}
	return d
}

// NewWithConfig returns a Detector with the given limits, or an error when
// any limit is non-positive or invalid.
func NewWithConfig(cfg Config, opts ...Option) (*Detector, error) {
	if err := cfg.validate(); err != nil {
		return nil, err
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
	return &Detector{
		cfg:       cfg,
		now:       o.now,
		groups:    make(map[groupKey]*group),
		cooldowns: make(map[groupKey]time.Time),
	}, nil
}

// NormalizeRoute reduces a raw request path to a stable route group: the
// query and fragment are stripped, numeric/UUID/long-hex path segments are
// replaced with ":id", empty paths become "/", and the result is capped at
// MaxRouteBytes on a UTF-8 boundary.
func NormalizeRoute(path string) string {
	if i := strings.IndexAny(path, "?#"); i >= 0 {
		path = path[:i]
	}
	if path == "" {
		return "/"
	}
	segs := strings.Split(path, "/")
	for i, seg := range segs {
		if isDynamic(seg) {
			segs[i] = ":id"
		}
	}
	return clampRoute(strings.Join(segs, "/"))
}

func isDynamic(seg string) bool {
	if seg == "" {
		return false
	}
	numeric := true
	for i := 0; i < len(seg); i++ {
		if seg[i] < '0' || seg[i] > '9' {
			numeric = false
			break
		}
	}
	if numeric {
		return true
	}
	if isUUID(seg) {
		return true
	}
	return len(seg) >= 16 && allHex(seg)
}

func isUUID(s string) bool {
	if len(s) != 36 {
		return false
	}
	for i := 0; i < len(s); i++ {
		switch i {
		case 8, 13, 18, 23:
			if s[i] != '-' {
				return false
			}
		default:
			if !isHexByte(s[i]) {
				return false
			}
		}
	}
	return true
}

func allHex(s string) bool {
	for i := 0; i < len(s); i++ {
		if !isHexByte(s[i]) {
			return false
		}
	}
	return true
}

func isHexByte(c byte) bool {
	return c >= '0' && c <= '9' || c >= 'a' && c <= 'f' || c >= 'A' && c <= 'F'
}

func clampRoute(s string) string {
	if len(s) <= MaxRouteBytes {
		return s
	}
	out := s[:MaxRouteBytes]
	for len(out) > 0 && !utf8.ValidString(out) {
		out = out[:len(out)-1]
	}
	return out
}

type groupKey struct {
	websiteID string
	agentID   string
	sourceID  string
	route     string
}

type sample struct {
	seq        uint64
	ts         time.Time
	statusCode int
	latencyMS  int
	hasLatency bool
}

type group struct {
	createdSeq uint64
	firstSeen  time.Time
	samples    []sample
}

// Detector tracks rolling traffic windows per website/agent/source/route
// partition and emits anomalies when the 5xx rate or p95 latency degrades.
type Detector struct {
	mu  sync.Mutex
	cfg Config
	now func() time.Time
	seq uint64

	groups             map[groupKey]*group
	cooldowns          map[groupKey]time.Time
	observations       int64
	emitted            int64
	cooldownSuppressed int64
	capacityEvictions  int64
}

// Observe records one request and returns an Anomaly when its partition
// degrades above the configured thresholds and is not in cooldown.
func (d *Detector) Observe(obs Observation) *Anomaly {
	d.mu.Lock()
	defer d.mu.Unlock()

	now := d.now()
	d.pruneCooldowns(now)
	ts := now

	route := NormalizeRoute(obs.Path)
	k := groupKey{websiteID: obs.WebsiteID, agentID: obs.AgentID, sourceID: obs.SourceID, route: route}

	g := d.groups[k]
	if g != nil {
		g.purgeExpired(now, d.cfg.Window)
		if len(g.samples) == 0 {
			delete(d.groups, k)
			g = nil
		}
	}
	if g == nil {
		if len(d.groups) >= d.cfg.MaxGroups {
			d.evictOldestGroup()
			d.capacityEvictions++
		}
		d.seq++
		g = &group{createdSeq: d.seq, firstSeen: ts}
		d.groups[k] = g
	}

	d.seq++
	s := sample{seq: d.seq, ts: ts, statusCode: obs.StatusCode}
	if obs.LatencyMS != nil && *obs.LatencyMS >= 0 {
		s.latencyMS = *obs.LatencyMS
		s.hasLatency = true
	}
	g.samples = insertSample(g.samples, s)
	for len(g.samples) > d.cfg.MaxSamplesPerGroup {
		g.samples = g.samples[1:]
		d.capacityEvictions++
	}
	d.observations++

	if len(g.samples) < d.cfg.MinRequests {
		return nil
	}

	status5xx := 0
	for _, cur := range g.samples {
		if cur.statusCode >= 500 {
			status5xx++
		}
	}
	errorRate := float64(status5xx) / float64(len(g.samples))
	p95 := g.p95()

	if errorRate < d.cfg.ErrorRateThreshold && p95 <= d.cfg.P95LatencyMS {
		return nil
	}
	if until, exists := d.cooldowns[k]; exists && now.Before(until) {
		d.cooldownSuppressed++
		return nil
	}

	var reasons []string
	if errorRate >= d.cfg.ErrorRateThreshold {
		reasons = append(reasons, fmt.Sprintf("5xx error rate %.3f >= threshold %.3f", errorRate, d.cfg.ErrorRateThreshold))
	}
	if p95 > d.cfg.P95LatencyMS {
		reasons = append(reasons, fmt.Sprintf("p95 latency %dms > limit %dms", p95, d.cfg.P95LatencyMS))
	}

	anomaly := &Anomaly{
		WebsiteID:      obs.WebsiteID,
		AgentID:        obs.AgentID,
		SourceID:       obs.SourceID,
		Route:          route,
		RequestCount:   len(g.samples),
		Status5xxCount: status5xx,
		ErrorRate:      errorRate,
		P95LatencyMS:   p95,
		Reason:         strings.Join(reasons, "; "),
		Severity:       SeverityProblem,
		Category:       CategoryTrafficAnomaly,
		Fingerprint:    fingerprintOf(k),
	}
	d.storeCooldown(k, now.Add(d.cfg.Cooldown))
	d.emitted++
	return anomaly
}

// Snapshot returns live metrics. Expired samples are purged first.
func (d *Detector) Snapshot() Metrics {
	d.mu.Lock()
	defer d.mu.Unlock()

	now := d.now()
	d.pruneCooldowns(now)
	for k, g := range d.groups {
		g.purgeExpired(now, d.cfg.Window)
		if len(g.samples) == 0 {
			delete(d.groups, k)
		}
	}

	return Metrics{
		Groups:             len(d.groups),
		Observations:       d.observations,
		Emitted:            d.emitted,
		CooldownSuppressed: d.cooldownSuppressed,
		CapacityEvictions:  d.capacityEvictions,
	}
}

func (d *Detector) pruneCooldowns(now time.Time) {
	for key, until := range d.cooldowns {
		if !now.Before(until) {
			delete(d.cooldowns, key)
		}
	}
}

func (d *Detector) storeCooldown(key groupKey, until time.Time) {
	if _, exists := d.cooldowns[key]; !exists && len(d.cooldowns) >= d.cfg.MaxGroups {
		var evictKey groupKey
		var earliest time.Time
		found := false
		for candidate, candidateUntil := range d.cooldowns {
			if !found || candidateUntil.Before(earliest) || (candidateUntil.Equal(earliest) && keyLess(candidate, evictKey)) {
				evictKey, earliest, found = candidate, candidateUntil, true
			}
		}
		if found {
			delete(d.cooldowns, evictKey)
		}
	}
	d.cooldowns[key] = until
}

func keyLess(a, b groupKey) bool {
	if a.websiteID != b.websiteID {
		return a.websiteID < b.websiteID
	}
	if a.agentID != b.agentID {
		return a.agentID < b.agentID
	}
	if a.sourceID != b.sourceID {
		return a.sourceID < b.sourceID
	}
	return a.route < b.route
}

// p95 returns the nearest-rank 95th percentile latency in milliseconds over
// samples that carry a latency, or 0 when none do.
func (g *group) p95() int {
	var values []int
	for _, s := range g.samples {
		if s.hasLatency {
			values = append(values, s.latencyMS)
		}
	}
	if len(values) == 0 {
		return 0
	}
	sort.Ints(values)
	idx := int(math.Ceil(0.95*float64(len(values)))) - 1
	if idx < 0 {
		idx = 0
	}
	if idx >= len(values) {
		idx = len(values) - 1
	}
	return values[idx]
}

func (g *group) purgeExpired(now time.Time, window time.Duration) {
	kept := g.samples[:0]
	for _, s := range g.samples {
		if !now.Before(s.ts.Add(window)) {
			continue
		}
		kept = append(kept, s)
	}
	g.samples = kept
}

func insertSample(samples []sample, s sample) []sample {
	i := sort.Search(len(samples), func(i int) bool {
		a := samples[i]
		if a.ts.After(s.ts) {
			return true
		}
		return a.ts.Equal(s.ts) && a.seq >= s.seq
	})
	samples = append(samples, sample{})
	copy(samples[i+1:], samples[i:])
	samples[i] = s
	return samples
}

func (d *Detector) evictOldestGroup() {
	var oldestKey groupKey
	var oldest *group
	for k, g := range d.groups {
		if oldest == nil || g.firstSeen.Before(oldest.firstSeen) || (g.firstSeen.Equal(oldest.firstSeen) && g.createdSeq < oldest.createdSeq) {
			oldest = g
			oldestKey = k
		}
	}
	if oldest != nil {
		delete(d.groups, oldestKey)
	}
}

func fingerprintOf(k groupKey) string {
	src := fmt.Sprintf("%d:%s|%d:%s|%d:%s|%d:%s",
		len(k.websiteID), k.websiteID,
		len(k.agentID), k.agentID,
		len(k.sourceID), k.sourceID,
		len(k.route), k.route)
	sum := sha256.Sum256([]byte(src))
	return hex.EncodeToString(sum[:])
}
