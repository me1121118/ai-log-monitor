package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestShouldSendIgnoresZeroValuedMetricErrorCounters(t *testing.T) {
	cfg := &Config{}
	cfg.Filter.SendOnlyMatched = true
	cfg.Filter.Keywords = []string{"error", "failed", "timeout"}

	message := `fluent-bit cpu.local: {"errors"=>0, "failed"=>0, "cpu_p"=>0.25}`
	if shouldSend(message, cfg) {
		t.Fatalf("expected zero-valued metric counters to be ignored: %q", message)
	}
}

func TestShouldSendKeepsRealProblemSignals(t *testing.T) {
	cfg := &Config{}
	cfg.Filter.SendOnlyMatched = true
	cfg.Filter.Keywords = []string{"error", "failed", "timeout"}

	cases := []string{
		"ERROR failed to connect to database",
		"upstream timeout while waiting for response",
		`fluent-bit metrics {"errors"=>2}`,
	}
	for _, message := range cases {
		if !shouldSend(message, cfg) {
			t.Errorf("expected problem signal to be sent: %q", message)
		}
	}
}

func TestShouldSendIgnoresFluentBitCpuMetricWithoutProblemFields(t *testing.T) {
	cfg := &Config{}
	cfg.Filter.SendOnlyMatched = true
	cfg.Filter.Keywords = []string{"error", "failed", "timeout", "connection refused"}

	message := `2026-07-19T00:29:52+07:00 fluent-bit[616396]: [0] cpu.local: [[1784395791.823546865, {}], {"cpu_p"=>0.500000, "user_p"=>0.250000, "system_p"=>0.250000, "cpu0.p_cpu"=>0.000000}]`
	if shouldSend(message, cfg) {
		t.Fatalf("expected a normal Fluent Bit CPU metric to be ignored: %q", message)
	}
}

func TestShouldSendDoesNotTreatTimestampDigitsAsHttpStatus(t *testing.T) {
	cfg := &Config{}
	cfg.Filter.SendOnlyMatched = true
	cfg.Filter.Keywords = []string{"502", "503", "504"}

	cases := []string{
		`fluent-bit cpu.local: [[1784396066.823626504, {}], {"cpu_p"=>0.250000}]`,
		`2026-07-19T00:39:27.825030+07:00 fluent-bit cpu.local: [[1784396066.823626503, {}], {"cpu_p"=>0.250000}]`,
	}
	for _, message := range cases {
		if shouldSend(message, cfg) {
			t.Errorf("expected digits inside a timestamp to be ignored as an HTTP status: %q", message)
		}
	}
}

func TestLoadConfigKeepsMatchedFilterEnabled(t *testing.T) {
	path := filepath.Join(t.TempDir(), "agent.yaml")
	config := []byte(`server:
  url: "http://127.0.0.1:8888"
agent:
  name: "db1"
  role: "db"
  website_id: "website_1"
filter:
  send_only_matched: true
  keywords:
    - "error"
    - "503"
`)
	if err := os.WriteFile(path, config, 0600); err != nil {
		t.Fatal(err)
	}

	cfg, err := loadConfig(path)
	if err != nil {
		t.Fatalf("loadConfig returned error: %v", err)
	}
	if !cfg.Filter.SendOnlyMatched {
		t.Fatal("expected send_only_matched to remain enabled after YAML load")
	}
	if shouldSend(`fluent-bit cpu.local: [[1784396066.823626503, {}], {"cpu_p"=>0.250000}]`, cfg) {
		t.Fatal("expected the loaded config to ignore a normal CPU metric")
	}
}

func TestShouldSendIgnoresZeroValuedErrorCounters(t *testing.T) {
	cfg := &Config{}
	cfg.Filter.SendOnlyMatched = true
	cfg.Filter.Keywords = []string{"error", "failed", "timeout"}

	normalMetrics := []string{
		`fluent-bit [0] cpu.local: {"errors":0,"cpu_p":0.25}`,
		`service metrics errors=0 failures=0 retries=0`,
		`{"error_count": 0, "dropped": 0, "status": "ok"}`,
	}
	for _, message := range normalMetrics {
		if shouldSend(message, cfg) {
			t.Fatalf("expected zero-valued metric to be ignored: %q", message)
		}
	}
}

func TestShouldSendKeepsRealProblemsAndNonZeroCounters(t *testing.T) {
	cfg := &Config{}
	cfg.Filter.SendOnlyMatched = true
	cfg.Filter.Keywords = []string{"error", "failed", "timeout"}

	problems := []string{
		`database error connecting to primary`,
		`service metrics errors=2`,
		`request timeout after 30s`,
	}
	for _, message := range problems {
		if !shouldSend(message, cfg) {
			t.Fatalf("expected real problem to be sent: %q", message)
		}
	}
}
