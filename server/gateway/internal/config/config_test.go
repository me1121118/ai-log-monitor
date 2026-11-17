package config

import (
	"os"
	"testing"
	"time"
)

func unsetAll() {
	for _, key := range []string{
		"GATEWAY_LISTEN_ADDRESS",
		"PYTHON_BASE_URL",
		"GATEWAY_UPSTREAM_TIMEOUT",
		"GATEWAY_READ_HEADER_TIMEOUT",
		"GATEWAY_IDLE_TIMEOUT",
		"GATEWAY_MAX_INSPECT_BODY_BYTES",
		"GATEWAY_INGEST_MODE",
		"GATEWAY_INTERNAL_TOKEN",
		"GATEWAY_AGENT_AUTH_CACHE_TTL",
	} {
		os.Unsetenv(key)
	}
}

func TestLoadDefaults(t *testing.T) {
	unsetAll()
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() returned error: %v", err)
	}
	if cfg.ListenAddress != ":8888" {
		t.Errorf("ListenAddress = %q, want %q", cfg.ListenAddress, ":8888")
	}
	if cfg.PythonBaseURL != "http://localhost:8889" {
		t.Errorf("PythonBaseURL = %q, want %q", cfg.PythonBaseURL, "http://localhost:8889")
	}
	if cfg.UpstreamTimeout != 30*time.Second {
		t.Errorf("UpstreamTimeout = %v, want %v", cfg.UpstreamTimeout, 30*time.Second)
	}
	if cfg.ReadHeaderTimeout != 10*time.Second {
		t.Errorf("ReadHeaderTimeout = %v, want %v", cfg.ReadHeaderTimeout, 10*time.Second)
	}
	if cfg.IdleTimeout != 90*time.Second {
		t.Errorf("IdleTimeout = %v, want %v", cfg.IdleTimeout, 90*time.Second)
	}
	if cfg.MaxInspectBodyBytes != 8192 {
		t.Errorf("MaxInspectBodyBytes = %d, want %d", cfg.MaxInspectBodyBytes, 8192)
	}
	if cfg.IngestMode != "shadow" {
		t.Errorf("IngestMode = %q, want shadow", cfg.IngestMode)
	}
}

func TestLoadFromEnv(t *testing.T) {
	unsetAll()
	t.Setenv("GATEWAY_LISTEN_ADDRESS", ":9999")
	t.Setenv("PYTHON_BASE_URL", "http://upstream:9000")
	t.Setenv("GATEWAY_UPSTREAM_TIMEOUT", "15s")
	t.Setenv("GATEWAY_READ_HEADER_TIMEOUT", "5s")
	t.Setenv("GATEWAY_IDLE_TIMEOUT", "60s")
	t.Setenv("GATEWAY_MAX_INSPECT_BODY_BYTES", "4096")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() returned error: %v", err)
	}
	if cfg.ListenAddress != ":9999" {
		t.Errorf("ListenAddress = %q, want %q", cfg.ListenAddress, ":9999")
	}
	if cfg.PythonBaseURL != "http://upstream:9000" {
		t.Errorf("PythonBaseURL = %q, want %q", cfg.PythonBaseURL, "http://upstream:9000")
	}
	if cfg.UpstreamTimeout != 15*time.Second {
		t.Errorf("UpstreamTimeout = %v, want %v", cfg.UpstreamTimeout, 15*time.Second)
	}
	if cfg.ReadHeaderTimeout != 5*time.Second {
		t.Errorf("ReadHeaderTimeout = %v, want %v", cfg.ReadHeaderTimeout, 5*time.Second)
	}
	if cfg.IdleTimeout != 60*time.Second {
		t.Errorf("IdleTimeout = %v, want %v", cfg.IdleTimeout, 60*time.Second)
	}
	if cfg.MaxInspectBodyBytes != 4096 {
		t.Errorf("MaxInspectBodyBytes = %d, want %d", cfg.MaxInspectBodyBytes, 4096)
	}
}

func TestLoadRejectsInvalidDuration(t *testing.T) {
	unsetAll()
	t.Setenv("GATEWAY_UPSTREAM_TIMEOUT", "not-a-duration")
	if _, err := Load(); err == nil {
		t.Fatal("Load() should reject an invalid duration")
	}
}

func TestLoadRejectsInvalidOrNonPositiveBodyLimit(t *testing.T) {
	unsetAll()
	for _, value := range []string{"not-a-number", "0", "-1"} {
		t.Setenv("GATEWAY_MAX_INSPECT_BODY_BYTES", value)
		if _, err := Load(); err == nil {
			t.Fatalf("Load() should reject body limit %q", value)
		}
	}
}

func TestLoadRejectsInvalidPythonURL(t *testing.T) {
	unsetAll()
	t.Setenv("PYTHON_BASE_URL", "://bad-url")
	if _, err := Load(); err == nil {
		t.Fatal("Load() should reject an invalid Python base URL")
	}
}

func TestLoadEvidenceModeRequiresInternalToken(t *testing.T) {
	unsetAll()
	t.Setenv("GATEWAY_INGEST_MODE", "evidence")
	if _, err := Load(); err == nil {
		t.Fatal("Load succeeded without evidence token")
	}
	t.Setenv("GATEWAY_INTERNAL_TOKEN", "secret")
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.AgentAuthCacheTTL != 5*time.Minute {
		t.Fatalf("AgentAuthCacheTTL = %s", cfg.AgentAuthCacheTTL)
	}
}

func TestLoadRejectsUnknownIngestMode(t *testing.T) {
	unsetAll()
	t.Setenv("GATEWAY_INGEST_MODE", "active")
	if _, err := Load(); err == nil {
		t.Fatal("Load accepted unknown ingest mode")
	}
}
