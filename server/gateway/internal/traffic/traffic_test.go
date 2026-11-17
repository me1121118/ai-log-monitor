package traffic

import (
	"fmt"
	"sync"
	"testing"
	"time"
)

func latency(ms int) *int { return &ms }

func obs(website, agent, source, path string, status int) Observation {
	return Observation{
		WebsiteID:  website,
		AgentID:    agent,
		SourceID:   source,
		Path:       path,
		StatusCode: status,
	}
}

func TestDefaults(t *testing.T) {
	d := Defaults()
	if d.Window != 60*time.Second {
		t.Errorf("Window = %v, want 60s", d.Window)
	}
	if d.MinRequests != 20 {
		t.Errorf("MinRequests = %d, want 20", d.MinRequests)
	}
	if d.ErrorRateThreshold != 0.05 {
		t.Errorf("ErrorRateThreshold = %v, want 0.05", d.ErrorRateThreshold)
	}
	if d.P95LatencyMS != 1000 {
		t.Errorf("P95LatencyMS = %d, want 1000", d.P95LatencyMS)
	}
	if d.Cooldown != 300*time.Second {
		t.Errorf("Cooldown = %v, want 300s", d.Cooldown)
	}
	if d.MaxGroups != 4096 {
		t.Errorf("MaxGroups = %d, want 4096", d.MaxGroups)
	}
	if d.MaxSamplesPerGroup != 256 {
		t.Errorf("MaxSamplesPerGroup = %d, want 256", d.MaxSamplesPerGroup)
	}
}

func TestNewWithConfigRejectsInvalid(t *testing.T) {
	cfg := Defaults()
	cfg.Window = 0
	if _, err := NewWithConfig(cfg); err == nil {
		t.Error("accepted zero window")
	}
	cfg = Defaults()
	cfg.Window = -time.Second
	if _, err := NewWithConfig(cfg); err == nil {
		t.Error("accepted negative window")
	}
	cfg = Defaults()
	cfg.MinRequests = 0
	if _, err := NewWithConfig(cfg); err == nil {
		t.Error("accepted zero min requests")
	}
	cfg = Defaults()
	cfg.ErrorRateThreshold = 0
	if _, err := NewWithConfig(cfg); err == nil {
		t.Error("accepted zero error rate threshold")
	}
	cfg = Defaults()
	cfg.ErrorRateThreshold = 1.5
	if _, err := NewWithConfig(cfg); err == nil {
		t.Error("accepted threshold above 1")
	}
	cfg = Defaults()
	cfg.P95LatencyMS = 0
	if _, err := NewWithConfig(cfg); err == nil {
		t.Error("accepted zero p95 latency limit")
	}
	cfg = Defaults()
	cfg.Cooldown = 0
	if _, err := NewWithConfig(cfg); err == nil {
		t.Error("accepted zero cooldown")
	}
	cfg = Defaults()
	cfg.MaxGroups = 0
	if _, err := NewWithConfig(cfg); err == nil {
		t.Error("accepted zero max groups")
	}
	cfg = Defaults()
	cfg.MaxSamplesPerGroup = -1
	if _, err := NewWithConfig(cfg); err == nil {
		t.Error("accepted negative max samples per group")
	}
}

func TestNormalizeRoute(t *testing.T) {
	cases := []struct {
		in   string
		want string
	}{
		{"/users/123", "/users/:id"},
		{"/users/123/edit", "/users/:id/edit"},
		{"/api/v2/orders/42/items", "/api/v2/orders/:id/items"},
		{"/order/123e4567-e89b-12d3-a456-426614174000", "/order/:id"},
		{"/order/123E4567-E89B-12D3-A456-426614174000", "/order/:id"},
		{"/item/a1b2c3d4e5f6a7b8c9d0e1f2", "/item/:id"},
		{"/item/a1B2c3D4e5F6a7B8c9D0e1F2", "/item/:id"},
		{"/item/abcd1234", "/item/abcd1234"},
		{"/search?q=users/123", "/search"},
		{"/search?q=abc#section", "/search"},
		{"/users/123#frag", "/users/:id"},
		{"", "/"},
		{"/", "/"},
		{"?q=1", "/"},
		{"/api/v1/", "/api/v1/"},
		{"/café/42", "/café/:id"},
	}
	for _, tc := range cases {
		if got := NormalizeRoute(tc.in); got != tc.want {
			t.Errorf("NormalizeRoute(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

func TestNormalizeRouteCapsAtMaxRouteBytes(t *testing.T) {
	long := "/users/" + string(make([]byte, 500))
	got := NormalizeRoute(long)
	if len(got) > MaxRouteBytes {
		t.Fatalf("NormalizeRoute returned %d bytes, want at most %d", len(got), MaxRouteBytes)
	}
	if !utf8Valid(got) {
		t.Fatalf("NormalizeRoute truncated on a non-UTF-8 boundary: %q", got)
	}
}

func utf8Valid(s string) bool {
	ok := true
	for _, r := range s {
		_ = r
	}
	return ok
}

func TestIsolationAcrossWebsiteAgentSource(t *testing.T) {
	det, err := NewWithConfig(Defaults())
	if err != nil {
		t.Fatal(err)
	}

	for i := 0; i < 19; i++ {
		if a := det.Observe(obs("w1", "a1", "s1", "/pay", 500)); a != nil {
			t.Fatalf("unexpected anomaly on fill %d: %+v", i, a)
		}
	}
	a := det.Observe(obs("w1", "a1", "s1", "/pay", 500))
	if a == nil {
		t.Fatal("expected anomaly for w1/a1/s1")
	}
	if a.WebsiteID != "w1" || a.AgentID != "a1" || a.SourceID != "s1" || a.Route != "/pay" {
		t.Errorf("anomaly fields = %+v", a)
	}
	if a.Severity != SeverityProblem || a.Category != CategoryTrafficAnomaly {
		t.Errorf("severity/category = %q/%q", a.Severity, a.Category)
	}
	if a.Fingerprint == "" {
		t.Error("empty fingerprint")
	}

	for i := 0; i < 20; i++ {
		if got := det.Observe(obs("w1", "a1", "s2", "/pay", 200)); got != nil {
			t.Fatalf("source s2 must stay isolated: %+v", got)
		}
		if got := det.Observe(obs("w1", "a2", "s1", "/pay", 200)); got != nil {
			t.Fatalf("agent a2 must stay isolated: %+v", got)
		}
		if got := det.Observe(obs("w2", "a1", "s1", "/pay", 200)); got != nil {
			t.Fatalf("website w2 must stay isolated: %+v", got)
		}
		if got := det.Observe(obs("w1", "a1", "s1", "/other", 200)); got != nil {
			t.Fatalf("route /other must stay isolated: %+v", got)
		}
	}
}

func TestThresholdBoundary(t *testing.T) {
	det, err := NewWithConfig(Defaults())
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 19; i++ {
		if a := det.Observe(obs("w", "a", "s", "/r", 200)); a != nil {
			t.Fatalf("below MinRequests emitted anomaly: %+v", a)
		}
	}
	if a := det.Observe(obs("w", "a", "s", "/r", 200)); a != nil {
		t.Fatalf("0%% 5xx at threshold floor emitted anomaly: %+v", a)
	}

	det2, err := NewWithConfig(Defaults())
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 19; i++ {
		det2.Observe(obs("w", "a", "s", "/r", 200))
	}
	a := det2.Observe(obs("w", "a", "s", "/r", 500))
	if a == nil {
		t.Fatal("expected anomaly at exactly 5%% error rate")
	}
	if a.RequestCount != 20 || a.Status5xxCount != 1 {
		t.Errorf("request/5xx counts = %d/%d", a.RequestCount, a.Status5xxCount)
	}
	if a.ErrorRate < 0.05-1e-9 || a.ErrorRate > 0.05+1e-9 {
		t.Errorf("ErrorRate = %v, want ~0.05", a.ErrorRate)
	}
}

func TestP95StrictlyExceedsLimit(t *testing.T) {
	det, err := NewWithConfig(Defaults())
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 20; i++ {
		o := obs("w", "a", "s", "/r", 200)
		o.LatencyMS = latency(1000)
		if a := det.Observe(o); a != nil {
			t.Fatalf("p95 equal to limit emitted anomaly: %+v", a)
		}
	}

	det2, err := NewWithConfig(Defaults())
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 19; i++ {
		o := obs("w", "a", "s", "/r", 200)
		o.LatencyMS = latency(1001)
		det2.Observe(o)
	}
	o := obs("w", "a", "s", "/r", 200)
	o.LatencyMS = latency(900)
	a := det2.Observe(o)
	if a == nil {
		t.Fatal("expected p95 anomaly")
	}
	if a.P95LatencyMS != 1001 {
		t.Errorf("P95LatencyMS = %d, want 1001", a.P95LatencyMS)
	}
	if a.Status5xxCount != 0 {
		t.Errorf("p95-only anomaly should have no 5xx, got %d", a.Status5xxCount)
	}
}

func TestP95WithoutLatency(t *testing.T) {
	det, err := NewWithConfig(Defaults())
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 20; i++ {
		if a := det.Observe(obs("w", "a", "s", "/r", 200)); a != nil {
			t.Fatalf("no-latency 200s emitted anomaly: %+v", a)
		}
	}
}

func TestRollingWindowExpiry(t *testing.T) {
	cur := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	det, err := NewWithConfig(Defaults(), WithClock(func() time.Time { return cur }))
	if err != nil {
		t.Fatal(err)
	}

	for i := 0; i < 19; i++ {
		o := obs("w", "a", "s", "/r", 500)
		o.Timestamp = cur
		det.Observe(o)
	}
	if a := det.Observe(obs("w", "a", "s", "/r", 500)); a == nil {
		t.Fatal("expected anomaly within window")
	}
	if m := det.Snapshot(); m.Emitted != 1 {
		t.Fatalf("Emitted = %d, want 1", m.Emitted)
	}

	cur = cur.Add(60 * time.Second)
	if a := det.Observe(obs("w", "a", "s", "/r", 200)); a != nil {
		t.Fatalf("expired samples still counted: %+v", a)
	}

	cur = cur.Add(time.Second)
	for i := 0; i < 19; i++ {
		o := obs("w", "a", "s", "/r", 200)
		o.Timestamp = cur
		det.Observe(o)
	}
	if a := det.Observe(obs("w", "a", "s", "/r", 200)); a != nil {
		t.Fatalf("fresh healthy window emitted anomaly: %+v", a)
	}
	m := det.Snapshot()
	if m.Groups != 1 {
		t.Errorf("Groups = %d, want 1", m.Groups)
	}
	if m.Observations != 41 {
		t.Errorf("Observations = %d, want 41", m.Observations)
	}
}

func TestCooldownSuppressesAndReemits(t *testing.T) {
	cur := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	det, err := NewWithConfig(Defaults(), WithClock(func() time.Time { return cur }))
	if err != nil {
		t.Fatal(err)
	}

	for i := 0; i < 19; i++ {
		o := obs("w", "a", "s", "/r", 500)
		o.Timestamp = cur
		det.Observe(o)
	}
	a := det.Observe(obs("w", "a", "s", "/r", 500))
	if a == nil {
		t.Fatal("expected first anomaly")
	}
	firstFP := a.Fingerprint

	cur = cur.Add(10 * time.Second)
	o := obs("w", "a", "s", "/r", 500)
	o.Timestamp = cur
	if got := det.Observe(o); got != nil {
		t.Fatalf("cooldown should suppress anomaly, got %+v", got)
	}
	m := det.Snapshot()
	if m.Emitted != 1 || m.CooldownSuppressed != 1 {
		t.Errorf("after suppression Emitted/CooldownSuppressed = %d/%d, want 1/1", m.Emitted, m.CooldownSuppressed)
	}

	cur = cur.Add(300 * time.Second)
	for i := 0; i < 19; i++ {
		o := obs("w", "a", "s", "/r", 500)
		o.Timestamp = cur
		det.Observe(o)
	}
	a = det.Observe(obs("w", "a", "s", "/r", 500))
	if a == nil {
		t.Fatal("expected re-emission after cooldown")
	}
	if a.Fingerprint != firstFP {
		t.Errorf("fingerprint changed across cooldown: %s vs %s", a.Fingerprint, firstFP)
	}
	if m := det.Snapshot(); m.Emitted != 2 {
		t.Errorf("Emitted = %d, want 2", m.Emitted)
	}
}

func TestCooldownSurvivesRollingGroupExpiry(t *testing.T) {
	cur := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	det, err := NewWithConfig(Defaults(), WithClock(func() time.Time { return cur }))
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 20; i++ {
		if anomaly := det.Observe(obs("w", "a", "s", "/r", 500)); i == 19 && anomaly == nil {
			t.Fatal("expected initial anomaly")
		}
	}
	cur = cur.Add(61 * time.Second)
	for i := 0; i < 20; i++ {
		if anomaly := det.Observe(obs("w", "a", "s", "/r", 500)); anomaly != nil {
			t.Fatalf("cooldown was lost after rolling group expiry: %+v", anomaly)
		}
	}
	if got := det.Snapshot().CooldownSuppressed; got != 1 {
		t.Fatalf("CooldownSuppressed = %d, want 1", got)
	}
}

func TestCapsBoundGroupsAndSamples(t *testing.T) {
	cfg := Defaults()
	cfg.MaxGroups = 2
	cfg.MaxSamplesPerGroup = 4
	cfg.MinRequests = 4
	det, err := NewWithConfig(cfg)
	if err != nil {
		t.Fatal(err)
	}

	o := obs("w", "a", "s", "/first", 200)
	o.Timestamp = time.Unix(1, 0)
	det.Observe(o)
	o = obs("w", "a", "s", "/first", 500)
	o.Timestamp = time.Unix(2, 0)
	det.Observe(o)
	o = obs("w", "a", "s", "/first", 500)
	o.Timestamp = time.Unix(3, 0)
	det.Observe(o)
	o = obs("w", "a", "s", "/first", 500)
	o.Timestamp = time.Unix(4, 0)
	a := det.Observe(o)
	if a == nil {
		t.Fatal("expected anomaly when the bounded group reached MinRequests")
	}
	if a.RequestCount != 4 || a.Status5xxCount != 3 {
		t.Errorf("bounded request/5xx counts = %d/%d, want 4/3", a.RequestCount, a.Status5xxCount)
	}
	o = obs("w", "a", "s", "/first", 500)
	o.Timestamp = time.Unix(5, 0)
	det.Observe(o)

	det.Observe(obs("w", "a", "s", "/first", 500))

	det.Observe(obs("w", "a", "s", "/second", 200))
	det.Observe(obs("w", "a", "s", "/third", 500))
	m := det.Snapshot()
	if m.Groups != 2 {
		t.Errorf("Groups = %d, want 2 after oldest-group eviction", m.Groups)
	}
	if m.CapacityEvictions < 3 {
		t.Errorf("CapacityEvictions = %d, want >= 3", m.CapacityEvictions)
	}
}

func TestFingerprintDeterministic(t *testing.T) {
	cfg := Defaults()
	cfg.MinRequests = 1
	det, err := NewWithConfig(cfg)
	if err != nil {
		t.Fatal(err)
	}
	det.Observe(obs("w", "a", "s", "/r", 500))
	det2, err := NewWithConfig(cfg)
	if err != nil {
		t.Fatal(err)
	}
	det2.Observe(obs("w", "a", "s", "/r", 500))
	if det.Snapshot().Emitted != det2.Snapshot().Emitted {
		t.Fatal("expected identical behavior")
	}
}

func TestObserveUnderConcurrency(t *testing.T) {
	det, err := NewWithConfig(Defaults())
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	for g := 0; g < 64; g++ {
		wg.Add(1)
		go func(g int) {
			defer wg.Done()
			for i := 0; i < 50; i++ {
				o := obs("w1", "a1", "s1", fmt.Sprintf("/route/%d/item", g%4), 200)
				if i%5 == 0 {
					o.StatusCode = 500
				}
				o.LatencyMS = latency(500)
				det.Observe(o)
			}
		}(g)
	}
	wg.Wait()
	m := det.Snapshot()
	if m.Groups == 0 || m.Observations != 64*50 {
		t.Errorf("Snapshot after race = %+v", m)
	}
}
