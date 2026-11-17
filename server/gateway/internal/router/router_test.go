package router

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHealthReturnsOkWhenPythonIsReachable(t *testing.T) {
	python := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer python.Close()

	calledProxy := false
	proxy := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calledProxy = true
	})

	mux := New(proxy, python.URL, http.DefaultClient)
	ts := httptest.NewServer(mux)
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/health")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("status = %d, want %d", resp.StatusCode, http.StatusOK)
	}
	var body map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if body["status"] != "ok" || body["python"] != "ok" {
		t.Errorf("body = %+v, want {status:ok, python:ok}", body)
	}
	if calledProxy {
		t.Error("proxy should not be called for /health")
	}
}

func TestHealthReturnsDegradedWhenPythonIsUnreachable(t *testing.T) {
	calledProxy := false
	proxy := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calledProxy = true
	})

	mux := New(proxy, "http://127.0.0.1:1", &http.Client{})
	ts := httptest.NewServer(mux)
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/health")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("status = %d, want %d", resp.StatusCode, http.StatusOK)
	}
	var body map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if body["status"] != "degraded" || body["python"] != "unavailable" {
		t.Errorf("body = %+v, want {status:degraded, python:unavailable}", body)
	}
	if calledProxy {
		t.Error("proxy should not be called for /health")
	}
}

func TestHealthReturnsDegradedWhenPythonReturnsFailure(t *testing.T) {
	python := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer python.Close()

	mux := New(http.NotFoundHandler(), python.URL, http.DefaultClient)
	recorder := httptest.NewRecorder()
	mux.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/health", nil))

	var body map[string]string
	if err := json.NewDecoder(recorder.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if body["status"] != "degraded" || body["python"] != "unavailable" {
		t.Fatalf("body = %+v, want degraded Python status", body)
	}
}

func TestOnlyGetHealthIsGatewayOwned(t *testing.T) {
	proxied := false
	proxy := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		proxied = true
		w.WriteHeader(http.StatusAccepted)
	})
	mux := New(proxy, "http://127.0.0.1:1/health", http.DefaultClient)
	recorder := httptest.NewRecorder()
	mux.ServeHTTP(recorder, httptest.NewRequest(http.MethodPost, "/health", nil))

	if !proxied || recorder.Code != http.StatusAccepted {
		t.Fatal("POST /health must be proxied")
	}
}

func TestHealthIncludesMetricsWithoutSensitiveEventData(t *testing.T) {
	python := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer python.Close()

	mux := NewWithMetrics(
		http.NotFoundHandler(),
		python.URL,
		http.DefaultClient,
		func() any {
			return map[string]int64{"inspected": 12, "matched": 11, "mismatched": 1, "bypassed": 2}
		},
	)
	recorder := httptest.NewRecorder()
	mux.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/health", nil))

	var body map[string]any
	if err := json.NewDecoder(recorder.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	shadowData, ok := body["shadow"].(map[string]any)
	if !ok || shadowData["mismatched"] != float64(1) {
		t.Fatalf("unexpected shadow metrics: %#v", body["shadow"])
	}
	if _, exists := shadowData["message"]; exists {
		t.Fatal("health metrics must not expose event messages")
	}
}

func TestHealthUsesConfiguredRuntimeStatsKey(t *testing.T) {
	python := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer python.Close()
	mux := NewWithRuntimeStats(http.NotFoundHandler(), python.URL, http.DefaultClient, "evidence", func() any {
		return map[string]int{"forwarded": 3}
	})
	recorder := httptest.NewRecorder()
	mux.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/health", nil))
	var body map[string]any
	if err := json.NewDecoder(recorder.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if _, ok := body["evidence"]; !ok {
		t.Fatalf("missing evidence stats: %#v", body)
	}
	if _, ok := body["shadow"]; ok {
		t.Fatalf("unexpected shadow stats: %#v", body)
	}
}

func TestProxiesLogin(t *testing.T) {
	proxied := false
	proxy := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		proxied = true
		if r.URL.Path != "/login" {
			t.Errorf("path = %q, want /login", r.URL.Path)
		}
		w.WriteHeader(http.StatusOK)
	})

	mux := New(proxy, "http://127.0.0.1:1", &http.Client{})
	ts := httptest.NewServer(mux)
	defer ts.Close()

	http.Get(ts.URL + "/login")
	if !proxied {
		t.Error("request was not proxied")
	}
}

func TestProxiesIngest(t *testing.T) {
	proxied := false
	proxy := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		proxied = true
		if r.URL.Path != "/api/ingest" {
			t.Errorf("path = %q, want /api/ingest", r.URL.Path)
		}
		w.WriteHeader(http.StatusOK)
	})

	mux := New(proxy, "http://127.0.0.1:1", &http.Client{})
	ts := httptest.NewServer(mux)
	defer ts.Close()

	http.Get(ts.URL + "/api/ingest")
	if !proxied {
		t.Error("request was not proxied")
	}
}

func TestProxiesStaticFiles(t *testing.T) {
	proxied := false
	proxy := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		proxied = true
		if r.URL.Path != "/static/css/styles.css" {
			t.Errorf("path = %q, want /static/css/styles.css", r.URL.Path)
		}
		w.WriteHeader(http.StatusOK)
	})

	mux := New(proxy, "http://127.0.0.1:1", &http.Client{})
	ts := httptest.NewServer(mux)
	defer ts.Close()

	http.Get(ts.URL + "/static/css/styles.css")
	if !proxied {
		t.Error("request was not proxied")
	}
}

func TestProxiesAgentRegistration(t *testing.T) {
	proxied := false
	proxy := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		proxied = true
		w.WriteHeader(http.StatusOK)
	})

	mux := New(proxy, "http://127.0.0.1:1", &http.Client{})
	ts := httptest.NewServer(mux)
	defer ts.Close()

	http.Post(ts.URL+"/api/agents/register", "application/json", strings.NewReader("{}"))
	if !proxied {
		t.Error("request was not proxied")
	}
}

func TestProxiesHeartbeat(t *testing.T) {
	proxied := false
	proxy := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		proxied = true
		w.WriteHeader(http.StatusOK)
	})

	mux := New(proxy, "http://127.0.0.1:1", &http.Client{})
	ts := httptest.NewServer(mux)
	defer ts.Close()

	http.Post(ts.URL+"/api/agents/heartbeat", "application/json", strings.NewReader("{}"))
	if !proxied {
		t.Error("request was not proxied")
	}
}

func TestProxiesPreservesQueryString(t *testing.T) {
	proxied := false
	proxy := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		proxied = true
		if r.URL.RawQuery != "foo=bar" {
			t.Errorf("RawQuery = %q, want %q", r.URL.RawQuery, "foo=bar")
		}
		w.WriteHeader(http.StatusOK)
	})

	mux := New(proxy, "http://127.0.0.1:1", &http.Client{})
	ts := httptest.NewServer(mux)
	defer ts.Close()

	http.Get(ts.URL + "/api/ingest?foo=bar")
	if !proxied {
		t.Error("request was not proxied")
	}
}
