package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestClassifyLogPathTreatsKnownServicesAsClassifiersNotWhitelist(t *testing.T) {
	classification, confidence := classifyLogPath("/opt/shop/logs/app.log", "")
	if classification != "custom_app" {
		t.Fatalf("expected custom_app classification, got %s", classification)
	}
	if confidence < 0.50 {
		t.Fatalf("expected useful confidence for custom app path, got %f", confidence)
	}

	classification, confidence = classifyLogPath("/var/log/nginx/error.log", "")
	if classification != "known_service" {
		t.Fatalf("expected known_service classification, got %s", classification)
	}
	if confidence < 0.80 {
		t.Fatalf("expected high confidence for nginx path, got %f", confidence)
	}
}

func TestDiscoverLogPathsRecursivelyFindsRelevantCustomLogs(t *testing.T) {
	tempDir := t.TempDir()
	appLog := filepath.Join(tempDir, "opt", "shop", "logs", "app.log")
	apiLog := filepath.Join(tempDir, "srv", "api", "runtime", "error.log")
	readme := filepath.Join(tempDir, "srv", "api", "README.txt")
	for _, path := range []string{appLog, apiLog, readme} {
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte("ready\n"), 0600); err != nil {
			t.Fatal(err)
		}
	}

	paths := discoverLogPathsWithRoots(nil, []string{tempDir}, 20)

	discovered := map[string]LogPath{}
	for _, item := range paths {
		discovered[item.Path] = item
	}
	if _, ok := discovered[appLog]; !ok {
		t.Fatalf("expected app log to be discovered, got %#v", paths)
	}
	if _, ok := discovered[apiLog]; !ok {
		t.Fatalf("expected api error log to be discovered, got %#v", paths)
	}
	if _, ok := discovered[readme]; ok {
		t.Fatalf("did not expect readme to be discovered: %#v", paths)
	}
	if !discovered[appLog].Discovered {
		t.Fatalf("expected discovered flag on app log: %#v", discovered[appLog])
	}
	if discovered[appLog].Classification != "custom_app" {
		t.Fatalf("expected custom app classification, got %#v", discovered[appLog])
	}
}

func TestDiscoveryRecognizesOnlyRealSystemLogRoots(t *testing.T) {
	if !isSystemLogRoot("/var/log") || !isSystemLogRoot("/host/var/log") {
		t.Fatal("expected mounted system log roots to be recognized")
	}
	if isSystemLogRoot(filepath.Join(t.TempDir(), "var", "log")) {
		t.Fatal("test and custom var/log roots must remain discoverable")
	}
}

func TestDiscoveryMapsMariaDBJournalMessagesFromSyslog(t *testing.T) {
	tempDir := t.TempDir()
	etcRoot := filepath.Join(tempDir, "etc")
	logRoot := filepath.Join(tempDir, "var", "log")
	syslog := filepath.Join(logRoot, "syslog")
	if err := os.MkdirAll(filepath.Join(etcRoot, "mysql"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(logRoot, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(syslog, []byte("mariadbd: ready\n"), 0600); err != nil {
		t.Fatal(err)
	}

	paths := discoverLogPathsWithRoots(nil, []string{logRoot, etcRoot}, 20)
	if len(paths) != 1 {
		t.Fatalf("expected one logical MariaDB source, got %#v", paths)
	}
	if paths[0].Name != "mariadb_journal" || paths[0].Type != "mariadb" || paths[0].Path != syslog {
		t.Fatalf("unexpected MariaDB source: %#v", paths[0])
	}
	if len(paths[0].Includes) == 0 {
		t.Fatalf("expected MariaDB source filter: %#v", paths[0])
	}
}

func TestDiscoverLogPathsHonorsMaxFiles(t *testing.T) {
	tempDir := t.TempDir()
	for index := 0; index < 5; index++ {
		path := filepath.Join(tempDir, "logs", safeSuffix("app"), safeSuffix(string(rune('a'+index)))+".log")
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte("ready\n"), 0600); err != nil {
			t.Fatal(err)
		}
	}

	paths := discoverLogPathsWithRoots(nil, []string{tempDir}, 2)

	if len(paths) != 2 {
		t.Fatalf("expected discovery to honor max files, got %d: %#v", len(paths), paths)
	}
}

func TestSourceIDAndEventUIDAreStable(t *testing.T) {
	id1 := sourceID("app01", "/opt/shop/logs/app.log")
	id2 := sourceID("app01", "/opt/shop/logs/app.log")
	if id1 == "" || id1 != id2 {
		t.Fatalf("expected stable source id, got %q and %q", id1, id2)
	}

	event := buildEvent(Config{}, LogPath{Name: "app", Path: "/opt/shop/logs/app.log", Type: "custom_app"}, "2026-07-17T00:00:00Z", LogRecord{Message: "connection refused", LineCount: 1})
	if event.EventUID == "" {
		t.Fatal("expected event uid")
	}
	if event.SourceID == "" {
		t.Fatal("expected source id")
	}
}

func TestReportLogSourcesPostsDiscoveredPaths(t *testing.T) {
	tempDir := t.TempDir()
	logPath := filepath.Join(tempDir, "app.log")
	if err := os.WriteFile(logPath, []byte("ready\n"), 0600); err != nil {
		t.Fatal(err)
	}

	received := make(chan map[string]interface{}, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/log-sources" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if r.Header.Get("X-Agent-Token") != "agt_test" {
			t.Fatalf("unexpected agent token: %s", r.Header.Get("X-Agent-Token"))
		}
		var payload map[string]interface{}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("decode payload: %v", err)
		}
		received <- payload
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{"stored":1}`))
	}))
	defer server.Close()

	cfg := Config{}
	cfg.Server.URL = server.URL
	cfg.Agent.WebsiteID = "website_1"
	cfg.Agent.Name = "app01"
	cfg.Agent.Role = "app"
	cfg.Logs.Paths = []LogPath{{Name: "app_log", Path: logPath, Type: "custom_app", Discovered: true}}

	if err := reportLogSources(server.URL, "agt_test", cfg); err != nil {
		t.Fatalf("reportLogSources returned error: %v", err)
	}
	payload := <-received
	if payload["website_id"] != "website_1" || payload["agent_id"] != "app01" {
		t.Fatalf("unexpected payload identity: %#v", payload)
	}
	sources, ok := payload["sources"].([]interface{})
	if !ok || len(sources) != 1 {
		t.Fatalf("expected one source, got %#v", payload["sources"])
	}
	source := sources[0].(map[string]interface{})
	if source["path"] != logPath {
		t.Fatalf("unexpected source path: %#v", source)
	}
	if source["status"] != "readable" {
		t.Fatalf("expected readable source, got %#v", source["status"])
	}
	if source["classification"] != "custom_app" {
		t.Fatalf("expected custom_app classification, got %#v", source["classification"])
	}
	metadata := source["metadata"].(map[string]interface{})
	if metadata["discovered"] != true {
		t.Fatalf("expected discovered metadata, got %#v", metadata)
	}
}

func TestReportLogSourcesUnauthorizedIsDetectable(t *testing.T) {
	cfg := Config{}
	cfg.Agent.Name = "web01"
	cfg.Agent.WebsiteID = "website_1"
	cfg.Logs.Paths = []LogPath{{Name: "app", Path: "/tmp/app.log", Type: "generic"}}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = w.Write([]byte(`{"error":"invalid agent token"}`))
	}))
	defer server.Close()

	err := reportLogSources(server.URL, "bad-token", cfg)
	if !isUnauthorizedStatus(err) {
		t.Fatalf("expected unauthorized status error, got %v", err)
	}
}

func TestDiscoverTopologyHintsFindsNginxProxyAndDatabaseHost(t *testing.T) {
	tempDir := t.TempDir()
	nginxDir := filepath.Join(tempDir, "etc", "nginx", "conf.d")
	appDir := filepath.Join(tempDir, "opt", "shop")
	if err := os.MkdirAll(nginxDir, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(appDir, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(nginxDir, "site.conf"), []byte("location /api { proxy_pass http://app01:8080; }\nupstream db_api { server app02:9000; }\n"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(appDir, ".env"), []byte("DB_HOST=db01:3306\n"), 0644); err != nil {
		t.Fatal(err)
	}

	hints := discoverTopologyHintsWithRoots([]string{tempDir}, 20)

	targets := map[string]string{}
	for _, hint := range hints {
		targets[hint.Target] = hint.HintType
	}
	if targets["app01:8080"] != "http_upstream" {
		t.Fatalf("expected nginx proxy target, got %#v", hints)
	}
	if targets["app02:9000"] != "http_upstream" {
		t.Fatalf("expected nginx upstream server target, got %#v", hints)
	}
	if targets["db01:3306"] != "database" {
		t.Fatalf("expected db host target, got %#v", hints)
	}
}

func TestDiscoverTopologyHintsFindsGaleraAndPeerSyncTargets(t *testing.T) {
	tempDir := t.TempDir()
	mysqlDir := filepath.Join(tempDir, "etc", "mysql")
	haproxyDir := filepath.Join(tempDir, "etc", "haproxy")
	if err := os.MkdirAll(mysqlDir, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(haproxyDir, 0755); err != nil {
		t.Fatal(err)
	}
	galeraConf := "[galera]\nwsrep_cluster_address=\"gcomm://10.0.0.11,10.0.0.12,10.0.0.13\"\n"
	if err := os.WriteFile(filepath.Join(mysqlDir, "galera.cnf"), []byte(galeraConf), 0644); err != nil {
		t.Fatal(err)
	}
	haproxyConf := "peers mypeers\n    peer lb02\n"
	if err := os.WriteFile(filepath.Join(haproxyDir, "haproxy.cfg"), []byte(haproxyConf), 0644); err != nil {
		t.Fatal(err)
	}

	hints := discoverTopologyHintsWithRoots([]string{tempDir}, 20)
	targets := map[string]string{}
	for _, hint := range hints {
		targets[hint.Target] = hint.HintType
	}
	for _, expected := range []string{"10.0.0.11", "10.0.0.12", "10.0.0.13", "lb02"} {
		if targets[expected] != "peer_sync" {
			t.Fatalf("expected peer_sync hint for %s, got %#v", expected, hints)
		}
	}
}

func TestBuildEventExtractsHTTPAccessLogMetadata(t *testing.T) {
	cfg := Config{}
	cfg.Agent.Name = "web01"
	cfg.Agent.Role = "web"
	cfg.Agent.WebsiteID = "website_1"
	cfg.Agent.ClusterID = "web_cluster_a"

	logLine := `203.0.113.45 - - [05/Nov/2026:12:00:01 +0000] "POST /api/checkout?retry=1 HTTP/1.1" 502 154 "-" "Mozilla/5.0"`
	ev := buildEvent(
		cfg,
		LogPath{Name: "nginx_access", Path: "/var/log/nginx/access.log", Type: "nginx"},
		"2026-11-05T12:00:01Z",
		LogRecord{Message: logLine, LineCount: 1},
	)
	if ev.Metadata == nil {
		t.Fatal("expected HTTP access log metadata to be populated")
	}
	if ev.Metadata["client_ip"] != "203.0.113.45" {
		t.Fatalf("unexpected client_ip: %#v", ev.Metadata["client_ip"])
	}
	if ev.Metadata["method"] != "POST" {
		t.Fatalf("unexpected method: %#v", ev.Metadata["method"])
	}
	if ev.Metadata["path"] != "/api/checkout?retry=1" {
		t.Fatalf("unexpected path: %#v", ev.Metadata["path"])
	}
	if ev.Metadata["status_code"] != 502 {
		t.Fatalf("unexpected status_code: %#v", ev.Metadata["status_code"])
	}
	if ev.Metadata["cluster_id"] != "web_cluster_a" {
		t.Fatalf("unexpected cluster_id: %#v", ev.Metadata["cluster_id"])
	}
}

func TestReportTopologyHintsPostsDiscoveredRelations(t *testing.T) {
	var payload map[string]interface{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/topology-hints" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if r.Header.Get("X-Agent-Token") != "agt_test" {
			t.Fatalf("unexpected agent token: %s", r.Header.Get("X-Agent-Token"))
		}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("decode payload: %v", err)
		}
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{"stored":1}`))
	}))
	defer server.Close()

	cfg := Config{}
	cfg.Server.URL = server.URL
	cfg.Agent.Name = "web01"
	cfg.Agent.WebsiteID = "website_1"

	err := reportTopologyHints(server.URL, "agt_test", cfg, []TopologyHint{
		{
			Source:     "/host/etc/nginx/site.conf",
			HintType:   "http_upstream",
			Target:     "app01:8080",
			Confidence: 0.9,
			Metadata: map[string]interface{}{
				"directive": "proxy_pass",
			},
		},
	})

	if err != nil {
		t.Fatalf("reportTopologyHints returned error: %v", err)
	}
	if payload["website_id"] != "website_1" || payload["agent_id"] != "web01" {
		t.Fatalf("unexpected routing payload: %#v", payload)
	}
	hints, ok := payload["hints"].([]interface{})
	if !ok || len(hints) != 1 {
		t.Fatalf("expected one hint, got %#v", payload["hints"])
	}
	hint := hints[0].(map[string]interface{})
	if hint["target"] != "app01:8080" {
		t.Fatalf("unexpected hint payload: %#v", hint)
	}
}
