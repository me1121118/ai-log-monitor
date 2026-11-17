package main

import (
	"errors"
	"strings"
	"testing"
)

func TestSpoolEventsPersistAndLoad(t *testing.T) {
	tempDir := t.TempDir()
	first := Event{
		WebsiteID: "website_1",
		AgentID:   "app01",
		AgentRole: "app",
		LogType:   "app",
		Service:   "app",
		Timestamp: "2026-07-17T00:00:00Z",
		Message:   "connection refused",
		EventUID:  "uid-1",
	}
	second := first
	second.Message = "timeout"
	second.EventUID = "uid-2"

	if err := appendSpoolEvent(tempDir, first, 1024*1024); err != nil {
		t.Fatalf("appendSpoolEvent first returned error: %v", err)
	}
	if err := appendSpoolEvent(tempDir, second, 1024*1024); err != nil {
		t.Fatalf("appendSpoolEvent second returned error: %v", err)
	}

	events, err := loadSpoolEvents(tempDir)
	if err != nil {
		t.Fatalf("loadSpoolEvents returned error: %v", err)
	}
	if len(events) != 2 {
		t.Fatalf("expected 2 spooled events, got %d", len(events))
	}
	if events[0].EventUID != "uid-1" || events[1].EventUID != "uid-2" {
		t.Fatalf("events loaded out of order: %#v", events)
	}
}

func TestFlushSpoolEventsKeepsUnsentEvents(t *testing.T) {
	tempDir := t.TempDir()
	events := []Event{
		{WebsiteID: "website_1", AgentID: "app01", AgentRole: "app", Timestamp: "2026-07-17T00:00:00Z", Message: "first", EventUID: "uid-1"},
		{WebsiteID: "website_1", AgentID: "app01", AgentRole: "app", Timestamp: "2026-07-17T00:00:01Z", Message: "second", EventUID: "uid-2"},
		{WebsiteID: "website_1", AgentID: "app01", AgentRole: "app", Timestamp: "2026-07-17T00:00:02Z", Message: "third", EventUID: "uid-3"},
	}
	if err := replaceSpoolEvents(tempDir, events); err != nil {
		t.Fatalf("replaceSpoolEvents returned error: %v", err)
	}

	attempts := 0
	sent, err := flushSpoolEvents(tempDir, func(event Event) error {
		attempts++
		if attempts == 2 {
			return errors.New("server unavailable")
		}
		return nil
	})
	if err == nil {
		t.Fatal("expected flush error")
	}
	if sent != 1 {
		t.Fatalf("expected 1 sent event, got %d", sent)
	}

	remaining, err := loadSpoolEvents(tempDir)
	if err != nil {
		t.Fatalf("loadSpoolEvents returned error: %v", err)
	}
	if len(remaining) != 2 {
		t.Fatalf("expected 2 remaining events, got %d", len(remaining))
	}
	if remaining[0].EventUID != "uid-2" || remaining[1].EventUID != "uid-3" {
		t.Fatalf("unexpected remaining events: %#v", remaining)
	}

	sent, err = flushSpoolEvents(tempDir, func(event Event) error { return nil })
	if err != nil {
		t.Fatalf("second flush returned error: %v", err)
	}
	if sent != 2 {
		t.Fatalf("expected 2 sent events, got %d", sent)
	}
	remaining, err = loadSpoolEvents(tempDir)
	if err != nil {
		t.Fatalf("loadSpoolEvents after flush returned error: %v", err)
	}
	if len(remaining) != 0 {
		t.Fatalf("expected empty spool, got %d events", len(remaining))
	}
}

func TestAppendSpoolEventCreatesLossMarkerWhenBoundedSpoolOverflows(t *testing.T) {
	tempDir := t.TempDir()
	base := Event{
		WebsiteID: "website_1",
		AgentID:   "app01",
		AgentRole: "app",
		LogType:   "app",
		Service:   "app",
		Timestamp: "2026-07-17T00:00:00Z",
		Message:   strings.Repeat("x", 120),
		EventUID:  "uid-base",
	}
	for i := 0; i < 20; i++ {
		event := base
		event.EventUID = safeSuffix("uid overflow ") + string(rune('a'+i))
		event.Message = base.Message + string(rune('a'+i))
		if err := appendSpoolEvent(tempDir, event, 1000); err != nil {
			t.Fatalf("appendSpoolEvent returned error: %v", err)
		}
	}

	events, err := loadSpoolEvents(tempDir)
	if err != nil {
		t.Fatalf("loadSpoolEvents returned error: %v", err)
	}
	foundLossMarker := false
	for _, event := range events {
		if strings.Contains(event.Message, "agent_spool_loss_marker") {
			foundLossMarker = true
			if event.Metadata["reason"] != "spool_max_bytes" {
				t.Fatalf("expected loss marker reason, got %#v", event.Metadata)
			}
		}
	}
	if !foundLossMarker {
		t.Fatalf("expected loss marker in bounded spool, got %#v", events)
	}
}
