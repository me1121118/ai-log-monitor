package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestScanOnceWaitsForUnterminatedLine(t *testing.T) {
	tempDir := t.TempDir()
	logPath := filepath.Join(tempDir, "app.log")
	stateDir := filepath.Join(tempDir, "state")
	if err := os.WriteFile(logPath, []byte("connection refu"), 0600); err != nil {
		t.Fatal(err)
	}

	cfg := &Config{}
	cfg.Agent.WebsiteID = "website_1"
	cfg.Agent.Name = "web01"
	cfg.Agent.Role = "web"
	cfg.Logs.Paths = []LogPath{{Name: "app_log", Path: logPath, Type: "generic"}}
	cfg.Filter.SendOnlyMatched = true
	cfg.Filter.Keywords = []string{"connection"}
	cfg.Runtime.StateDir = stateDir

	events, err := scanOnce(cfg)
	if err != nil {
		t.Fatalf("scanOnce returned error: %v", err)
	}
	if len(events) != 0 {
		t.Fatalf("expected no events for unfinished line, got %d", len(events))
	}
	state, err := loadState(stateDir)
	if err != nil {
		t.Fatalf("loadState returned error: %v", err)
	}
	if state[logPath] != 0 {
		t.Fatalf("expected offset to stay at 0, got %d", state[logPath])
	}

	f, err := os.OpenFile(logPath, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.WriteString("sed\n"); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}

	events, err = scanOnce(cfg)
	if err != nil {
		t.Fatalf("scanOnce returned error after completion: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected one completed event, got %d", len(events))
	}
	if events[0].Message != "connection refused" {
		t.Fatalf("unexpected event message: %q", events[0].Message)
	}
}

func TestScanOnceStartsDiscoveredLogsAtEndOnFirstRun(t *testing.T) {
	tempDir := t.TempDir()
	logPath := filepath.Join(tempDir, "syslog")
	stateDir := filepath.Join(tempDir, "state")
	if err := os.WriteFile(logPath, []byte("old timeout from before install\n"), 0600); err != nil {
		t.Fatal(err)
	}

	cfg := &Config{}
	cfg.Agent.WebsiteID = "website_1"
	cfg.Agent.Name = "web01"
	cfg.Agent.Role = "web"
	cfg.Logs.Paths = []LogPath{{Name: "syslog", Path: logPath, Type: "system", Discovered: true}}
	cfg.Filter.SendOnlyMatched = true
	cfg.Filter.Keywords = []string{"timeout"}
	cfg.Runtime.StateDir = stateDir

	events, err := scanOnce(cfg)
	if err != nil {
		t.Fatalf("scanOnce returned error: %v", err)
	}
	if len(events) != 0 {
		t.Fatalf("expected no historical events for first discovered scan, got %d", len(events))
	}

	f, err := os.OpenFile(logPath, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.WriteString("new timeout after install\n"); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}

	events, err = scanOnce(cfg)
	if err != nil {
		t.Fatalf("scanOnce returned error after append: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected one new event after append, got %d", len(events))
	}
	if events[0].Message != "new timeout after install" {
		t.Fatalf("unexpected event message: %q", events[0].Message)
	}
}

func TestGroupLogLinesKeepsTracebackTogether(t *testing.T) {
	records := groupLogLines([]string{
		"2026-07-17T00:00:00Z ERROR Traceback (most recent call last):",
		"  File \"app.py\", line 10, in handler",
		"ValueError: bad input",
		"2026-07-17T00:00:01Z INFO recovered",
	}, 20)

	if len(records) != 2 {
		t.Fatalf("expected 2 records, got %d: %#v", len(records), records)
	}
	if !records[0].Multiline {
		t.Fatal("expected first record to be multiline")
	}
	if records[0].LineCount != 3 {
		t.Fatalf("expected first record line count 3, got %d", records[0].LineCount)
	}
	if !strings.Contains(records[0].Message, "ValueError: bad input") {
		t.Fatalf("traceback record lost final line: %q", records[0].Message)
	}
	if records[1].Multiline {
		t.Fatalf("expected second record to be single-line: %#v", records[1])
	}
}

func TestGroupLogLinesKeepsPlainLinesSeparate(t *testing.T) {
	records := groupLogLines([]string{
		"first warning",
		"second warning",
	}, 20)

	if len(records) != 2 {
		t.Fatalf("expected plain lines to stay separate, got %d: %#v", len(records), records)
	}
}

func TestScanOnceGroupsMultilineStackTrace(t *testing.T) {
	tempDir := t.TempDir()
	logPath := filepath.Join(tempDir, "app.log")
	stateDir := filepath.Join(tempDir, "state")
	content := strings.Join([]string{
		"2026-07-17T00:00:00Z ERROR Traceback (most recent call last):",
		"  File \"app.py\", line 10, in handler",
		"ValueError: connection refused",
		"2026-07-17T00:00:01Z INFO recovered",
		"",
	}, "\n")
	if err := os.WriteFile(logPath, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}

	cfg := &Config{}
	cfg.Agent.WebsiteID = "website_1"
	cfg.Agent.Name = "app01"
	cfg.Agent.Role = "app"
	cfg.Logs.Paths = []LogPath{{Name: "app_log", Path: logPath, Type: "custom_app"}}
	cfg.Filter.SendOnlyMatched = true
	cfg.Filter.Keywords = []string{"connection refused"}
	cfg.Runtime.StateDir = stateDir

	events, err := scanOnce(cfg)
	if err != nil {
		t.Fatalf("scanOnce returned error: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected one grouped traceback event, got %d: %#v", len(events), events)
	}
	if !events[0].Multiline {
		t.Fatal("expected grouped event to be marked multiline")
	}
	if events[0].LineCount != 3 {
		t.Fatalf("expected line count 3, got %d", events[0].LineCount)
	}
	if !strings.Contains(events[0].Message, "ValueError: connection refused") {
		t.Fatalf("grouped event missing exception line: %q", events[0].Message)
	}
}

func TestScanOnceIncludesAccessTrafficWhenIncludeTrafficEnabled(t *testing.T) {
	tempDir := t.TempDir()
	logPath := filepath.Join(tempDir, "access.log")
	stateDir := filepath.Join(tempDir, "state")
	accessLine := `198.51.100.22 - - [05/Nov/2026:12:00:00 +0000] "GET /products HTTP/1.1" 200 512 "-" "curl/8.0"` + "\n"
	if err := os.WriteFile(logPath, []byte(accessLine), 0600); err != nil {
		t.Fatal(err)
	}

	cfg := &Config{}
	cfg.Agent.WebsiteID = "website_1"
	cfg.Agent.Name = "web01"
	cfg.Agent.Role = "web"
	cfg.Logs.Paths = []LogPath{{Name: "nginx_access", Path: logPath, Type: "nginx"}}
	cfg.Filter.SendOnlyMatched = true
	cfg.Filter.IncludeTraffic = true
	cfg.Runtime.StateDir = stateDir

	events, err := scanOnce(cfg)
	if err != nil {
		t.Fatalf("scanOnce returned error: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected 1 traffic event when IncludeTraffic is true, got %d", len(events))
	}
	if events[0].Metadata["client_ip"] != "198.51.100.22" || events[0].Metadata["status_code"] != 200 {
		t.Fatalf("unexpected traffic metadata: %#v", events[0].Metadata)
	}
}
