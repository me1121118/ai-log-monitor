package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

func TestRegisterAgentAcceptsCreatedStatus(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/agents/register" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if r.Header.Get("X-Enroll-Token") != "install-token" {
			t.Fatalf("unexpected enroll token: %s", r.Header.Get("X-Enroll-Token"))
		}
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(map[string]string{"agent_token": "agt_test"})
	}))
	defer server.Close()

	cfg := &Config{}
	cfg.Server.URL = server.URL
	cfg.Enrollment.Token = "install-token"
	cfg.Agent.Name = "web01"
	cfg.Agent.Role = "web"
	cfg.Agent.WebsiteID = "website_1"

	token, err := registerAgent(cfg)
	if err != nil {
		t.Fatalf("registerAgent returned error: %v", err)
	}
	if token != "agt_test" {
		t.Fatalf("unexpected token: %s", token)
	}
}

func TestIngestEventAcceptsCreatedStatus(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/ingest" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if r.Header.Get("X-Agent-Token") != "agt_test" {
			t.Fatalf("unexpected agent token: %s", r.Header.Get("X-Agent-Token"))
		}
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{"severity":"problem"}`))
	}))
	defer server.Close()

	err := ingestEvent(server.URL, "agt_test", Event{
		WebsiteID: "website_1",
		AgentID:   "web01",
		AgentRole: "web",
		LogType:   "app_log",
		Service:   "generic",
		Timestamp: "2026-07-14T10:00:00Z",
		Message:   "upstream timed out",
	})
	if err != nil {
		t.Fatalf("ingestEvent returned error: %v", err)
	}
}

func TestSendHeartbeatPostsAgentHealthWithAgentToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/agents/heartbeat" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if r.Header.Get("X-Agent-Token") != "agt_test" {
			t.Fatalf("unexpected agent token: %s", r.Header.Get("X-Agent-Token"))
		}
		var payload map[string]interface{}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("decode heartbeat payload: %v", err)
		}
		if payload["agent_id"] != "web01" {
			t.Fatalf("unexpected agent_id: %v", payload["agent_id"])
		}
		if payload["website_id"] != "website_1" {
			t.Fatalf("unexpected website_id: %v", payload["website_id"])
		}
		if payload["status"] != "active" {
			t.Fatalf("unexpected status: %v", payload["status"])
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"agent_id":"web01","status":"active"}`))
	}))
	defer server.Close()

	cfg := Config{}
	cfg.Server.URL = server.URL
	cfg.Agent.Name = "web01"
	cfg.Agent.Role = "web"
	cfg.Agent.WebsiteID = "website_1"
	cfg.Logs.Paths = []LogPath{{Name: "nginx_error", Path: "/host/var/log/nginx/error.log", Type: "nginx"}}

	if err := sendHeartbeat(server.URL, "agt_test", cfg); err != nil {
		t.Fatalf("sendHeartbeat returned error: %v", err)
	}
}

func TestResolveAgentTokenReusesSavedTokenWithoutRegistering(t *testing.T) {
	tempDir := t.TempDir()
	if err := saveAgentToken(tempDir, "agt_saved"); err != nil {
		t.Fatal(err)
	}
	cfg := &Config{}
	cfg.Runtime.StateDir = tempDir
	called := false

	token, err := resolveAgentToken(cfg, func(_ *Config) (string, error) {
		called = true
		return "agt_new", nil
	})
	if err != nil {
		t.Fatalf("resolveAgentToken returned error: %v", err)
	}
	if called {
		t.Fatal("registrar should not be called when saved token exists")
	}
	if token != "agt_saved" {
		t.Fatalf("unexpected token: %s", token)
	}
}

func TestResolveAgentTokenRegistersAndPersistsWhenMissing(t *testing.T) {
	tempDir := t.TempDir()
	cfg := &Config{}
	cfg.Runtime.StateDir = tempDir

	token, err := resolveAgentToken(cfg, func(_ *Config) (string, error) {
		return "agt_new", nil
	})
	if err != nil {
		t.Fatalf("resolveAgentToken returned error: %v", err)
	}
	if token != "agt_new" {
		t.Fatalf("unexpected token: %s", token)
	}
	saved, err := loadAgentToken(tempDir)
	if err != nil {
		t.Fatalf("loadAgentToken returned error: %v", err)
	}
	if saved != "agt_new" {
		t.Fatalf("unexpected saved token: %s", saved)
	}
}

func TestRefreshAgentTokenOverwritesSavedToken(t *testing.T) {
	tempDir := t.TempDir()
	if err := saveAgentToken(tempDir, "agt_old"); err != nil {
		t.Fatal(err)
	}
	cfg := &Config{}
	cfg.Runtime.StateDir = tempDir

	token, err := refreshAgentToken(cfg, func(_ *Config) (string, error) {
		return "agt_new", nil
	})
	if err != nil {
		t.Fatalf("refreshAgentToken returned error: %v", err)
	}
	saved, err := loadAgentToken(tempDir)
	if err != nil {
		t.Fatalf("loadAgentToken returned error: %v", err)
	}
	if token != "agt_new" || saved != "agt_new" {
		t.Fatalf("expected refreshed token to be saved, got token=%s saved=%s", token, saved)
	}
}

func TestIsUnauthorizedStatusDetectsUnauthorizedHTTPError(t *testing.T) {
	err := httpStatusError{StatusCode: http.StatusUnauthorized, Body: "invalid agent token"}
	if !isUnauthorizedStatus(err) {
		t.Fatal("expected unauthorized status error to be detected")
	}
}

func TestRegistrationLogDoesNotExposeAgentToken(t *testing.T) {
	source, err := os.ReadFile("main.go")
	if err != nil {
		t.Fatal(err)
	}

	text := string(source)
	if strings.Contains(text, "Token: %s") {
		t.Fatal("registration success log must not print the agent token")
	}
}

func TestHostVitalsParsersAndPriorityOrdering(t *testing.T) {
	memSample := "MemTotal:       16000000 kB\nMemFree:         2000000 kB\nMemAvailable:    4000000 kB\n"
	if ram := parseMemInfo(memSample); ram != 75.0 {
		t.Fatalf("expected 75.0 RAM percent, got %v", ram)
	}

	if cpu, ok := parseLoadAvg("1.50 1.20 1.00 1/200 1234\n", 2); !ok || cpu != 75.0 {
		t.Fatalf("expected 75.0 CPU percent, got %v (ok=%v)", cpu, ok)
	}

	dfSample := "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 100000 64000 36000 64% /\n"
	if disk := parseDfOutput(dfSample); disk != 64.0 {
		t.Fatalf("expected 64.0 Disk percent, got %v", disk)
	}

	ordered := prioritizeEvents([]Event{
		{Message: `198.51.100.1 - - [05/Nov/2026:12:00:00 +0000] "GET /ok HTTP/1.1" 200 12`, Metadata: map[string]interface{}{"status_code": 200}},
		{Message: `198.51.100.2 - - [05/Nov/2026:12:00:01 +0000] "GET /fail HTTP/1.1" 503 12`, Metadata: map[string]interface{}{"status_code": 503}},
	})
	if len(ordered) != 2 || ordered[0].Metadata["status_code"] != 503 {
		t.Fatalf("expected 503 event to be prioritized first, got %#v", ordered)
	}
}
