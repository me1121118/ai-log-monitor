package contextbuffer

import (
	"strings"
	"sync"
	"testing"
	"time"

	"ai-log-server/server/gateway/internal/classifier"
)

func testConfig() Config {
	return Config{TTL: 5 * time.Minute, MaxEventsPerPartition: 200, MaxTotalEvents: 20000, MaxPartitions: 2048, MaxContextLines: 20}
}

func event(website, agent, source, message string, timestamp time.Time) classifier.Event {
	return classifier.Event{WebsiteID: website, AgentID: agent, SourceID: source, Message: message, Service: "nginx", LogType: "nginx", Timestamp: timestamp}
}

func TestNewWithConfigRejectsNonPositiveLimits(t *testing.T) {
	cases := []Config{
		{TTL: 0, MaxEventsPerPartition: 1, MaxTotalEvents: 1, MaxPartitions: 1, MaxContextLines: 1},
		{TTL: time.Second, MaxEventsPerPartition: 0, MaxTotalEvents: 1, MaxPartitions: 1, MaxContextLines: 1},
		{TTL: time.Second, MaxEventsPerPartition: 1, MaxTotalEvents: 0, MaxPartitions: 1, MaxContextLines: 1},
		{TTL: time.Second, MaxEventsPerPartition: 1, MaxTotalEvents: 1, MaxPartitions: 0, MaxContextLines: 1},
		{TTL: time.Second, MaxEventsPerPartition: 1, MaxTotalEvents: 1, MaxPartitions: 1, MaxContextLines: 0},
	}
	for _, cfg := range cases {
		if _, err := NewWithConfig(cfg); err == nil {
			t.Fatalf("NewWithConfig(%+v) succeeded", cfg)
		}
	}
}

func TestContextIsolationOrderingAndLimit(t *testing.T) {
	now := time.Date(2026, 7, 31, 10, 0, 0, 0, time.UTC)
	cfg := testConfig()
	cfg.MaxContextLines = 2
	b, _ := NewWithConfig(cfg, WithClock(func() time.Time { return now }))

	b.Append(event("web1", "agent1", "source1", "third", now.Add(3*time.Second)), "normal")
	b.Append(event("web1", "agent1", "source1", "first", now.Add(time.Second)), "normal")
	b.Append(event("web1", "agent1", "source1", "second", now.Add(2*time.Second)), "normal")
	b.Append(event("web2", "agent1", "source1", "wrong website", now), "normal")
	b.Append(event("web1", "agent2", "source1", "wrong agent", now), "normal")
	b.Append(event("web1", "agent1", "source2", "wrong source", now), "normal")

	lines := b.ContextFor(event("web1", "agent1", "source1", "problem", now.Add(4*time.Second)))
	if len(lines) != 2 || lines[0].Message != "second" || lines[1].Message != "third" {
		t.Fatalf("unexpected context: %#v", lines)
	}
}

func TestTTLUsesArrivalTimeAndExpiresAtBoundary(t *testing.T) {
	now := time.Date(2026, 7, 31, 10, 0, 0, 0, time.UTC)
	cfg := testConfig()
	cfg.TTL = time.Minute
	b, _ := NewWithConfig(cfg, WithClock(func() time.Time { return now }))
	oldLogTime := now.Add(-24 * time.Hour)
	b.Append(event("web", "agent", "source", "old timestamp", oldLogTime), "normal")
	if got := b.Snapshot().Events; got != 1 {
		t.Fatalf("events = %d before TTL", got)
	}
	now = now.Add(time.Minute)
	if got := b.Snapshot(); got.Events != 0 || got.ExpiredEvictions != 1 {
		t.Fatalf("unexpected metrics after TTL: %+v", got)
	}
}

func TestPartitionAndGlobalCaps(t *testing.T) {
	now := time.Date(2026, 7, 31, 10, 0, 0, 0, time.UTC)
	cfg := testConfig()
	cfg.MaxEventsPerPartition = 2
	cfg.MaxTotalEvents = 3
	b, _ := NewWithConfig(cfg, WithClock(func() time.Time { return now }))
	for i, message := range []string{"one", "two", "three"} {
		b.Append(event("web", "agent", "source", message, now.Add(time.Duration(i)*time.Second)), "normal")
	}
	lines := b.ContextFor(event("web", "agent", "source", "problem", now.Add(time.Hour)))
	if len(lines) != 2 || lines[0].Message != "two" || lines[1].Message != "three" {
		t.Fatalf("partition cap failed: %#v", lines)
	}
	b.Append(event("web", "agent", "source2", "four", now.Add(4*time.Second)), "normal")
	b.Append(event("web", "agent", "source3", "five", now.Add(5*time.Second)), "normal")
	if got := b.Snapshot(); got.Events != 3 || got.CapacityEvictions != 2 {
		t.Fatalf("global caps failed: %+v", got)
	}
}

func TestPartitionCapEvictsOldestPartition(t *testing.T) {
	now := time.Date(2026, 7, 31, 10, 0, 0, 0, time.UTC)
	cfg := testConfig()
	cfg.MaxPartitions = 2
	b, _ := NewWithConfig(cfg, WithClock(func() time.Time { return now }))
	b.Append(event("web", "agent", "one", "one", now), "normal")
	b.Append(event("web", "agent", "two", "two", now), "normal")
	b.Append(event("web", "agent", "three", "three", now), "normal")
	if got := b.ContextFor(event("web", "agent", "one", "problem", now.Add(time.Second))); len(got) != 0 {
		t.Fatalf("oldest partition was retained: %#v", got)
	}
	if got := b.Snapshot(); got.Partitions != 2 || got.Events != 2 || got.CapacityEvictions != 1 {
		t.Fatalf("unexpected metrics: %+v", got)
	}
}

func TestRejectsNonNormalAndTrimsUTF8Safely(t *testing.T) {
	now := time.Now().UTC()
	b := New(WithClock(func() time.Time { return now }))
	if b.Append(event("web", "agent", "source", "problem", now), "problem") {
		t.Fatal("non-normal event was accepted")
	}
	long := strings.Repeat("a", MaxMessageBytes-1) + "ก"
	b.Append(event("web", "agent", "source", long, now), "normal")
	lines := b.ContextFor(event("web", "agent", "source", "problem", now.Add(time.Second)))
	if len(lines) != 1 || len(lines[0].Message) > MaxMessageBytes || !strings.HasSuffix(lines[0].Message, "a") {
		t.Fatalf("message was not safely trimmed: len=%d", len(lines[0].Message))
	}
	if got := b.Snapshot().RejectedNonNormal; got != 1 {
		t.Fatalf("rejected = %d", got)
	}
}

func TestConcurrentAppendAndContextFor(t *testing.T) {
	now := time.Now().UTC()
	b := New(WithClock(func() time.Time { return now }))
	const workers = 64
	var wg sync.WaitGroup
	wg.Add(workers)
	for i := range workers {
		go func(i int) {
			defer wg.Done()
			ev := event("web", "agent", "source", "normal", now.Add(time.Duration(i)*time.Millisecond))
			b.Append(ev, "normal")
			_ = b.ContextFor(event("web", "agent", "source", "problem", now.Add(time.Second)))
		}(i)
	}
	wg.Wait()
	if got := b.Snapshot().Events; got != workers {
		t.Fatalf("events = %d, want %d", got, workers)
	}
}
