package ingest

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"ai-log-server/server/gateway/internal/contextbuffer"
	"ai-log-server/server/gateway/internal/traffic"
)

func payload(message, timestamp string) []byte {
	body, _ := json.Marshal(map[string]any{
		"website_id": "website_1", "agent_id": "db1", "source_id": "src_mysql",
		"service": "mariadb", "log_type": "mysql", "file_path": "/var/log/mysql/error.log",
		"timestamp": timestamp, "message": message,
	})
	return body
}

func trafficPayload(status int) []byte {
	body, _ := json.Marshal(map[string]any{
		"website_id": "website_1", "agent_id": "web1", "source_id": "src_nginx_access",
		"service": "nginx", "log_type": "access", "file_path": "/var/log/nginx/access.log",
		"timestamp": "2026-07-31T10:00:00Z",
		"message":   "10.0.0.1 - - [31/Jul/2026:10:00:00 +0000] \"GET /api/orders/123?full=1 HTTP/1.1\" " + fmt.Sprint(status) + " 42 rt=0.250",
	})
	return body
}

func newRequest(body []byte, token string) *http.Request {
	req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Agent-Token", token)
	return req
}

func TestNormalIsBufferedAndAuthIsCached(t *testing.T) {
	var validations atomic.Int64
	python := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/agents/validate" {
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
		validations.Add(1)
		if r.Header.Get("X-Gateway-Token") != "gateway-secret" || r.Header.Get("X-Agent-Token") != "agent-secret" {
			t.Fatal("missing internal or agent token")
		}
		writeJSON(w, http.StatusOK, map[string]any{"valid": true})
	}))
	defer python.Close()

	var fallback atomic.Int64
	next := http.HandlerFunc(func(http.ResponseWriter, *http.Request) { fallback.Add(1) })
	metrics := &Metrics{}
	h, err := New(next, python.URL, python.Client(), "gateway-secret", 8192, time.Minute, contextbuffer.New(), nil, metrics)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		recorder := httptest.NewRecorder()
		h.ServeHTTP(recorder, newRequest(payload("ready for connections", "2026-07-31T10:00:00Z"), "agent-secret"))
		if recorder.Code != http.StatusCreated {
			t.Fatalf("status = %d body=%s", recorder.Code, recorder.Body.String())
		}
		var response map[string]any
		json.Unmarshal(recorder.Body.Bytes(), &response)
		if response["buffered"] != true || response["severity"] != "normal" {
			t.Fatalf("unexpected response: %#v", response)
		}
	}
	if validations.Load() != 1 || fallback.Load() != 0 || metrics.Snapshot().Buffered != 2 {
		t.Fatalf("validations=%d fallback=%d metrics=%+v", validations.Load(), fallback.Load(), metrics.Snapshot())
	}
}

func TestProblemForwardsClassificationAndPriorContext(t *testing.T) {
	var evidence map[string]any
	python := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/internal/agents/validate":
			writeJSON(w, http.StatusOK, map[string]any{"valid": true})
		case "/internal/evidence":
			if r.Header.Get("X-Gateway-Token") != "gateway-secret" {
				t.Fatal("missing gateway token")
			}
			json.NewDecoder(r.Body).Decode(&evidence)
			writeJSON(w, http.StatusCreated, map[string]any{"event_id": "evt_1", "incident_id": "inc_1", "severity": evidence["severity"], "category": evidence["category"], "fingerprint": evidence["fingerprint"], "buffered": false})
		default:
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
	}))
	defer python.Close()
	h, _ := New(http.NotFoundHandler(), python.URL, python.Client(), "gateway-secret", 8192, time.Minute, contextbuffer.New(), nil, &Metrics{})

	normal := httptest.NewRecorder()
	h.ServeHTTP(normal, newRequest(payload("ready for connections", "2026-07-31T10:00:00Z"), "agent-secret"))
	problem := httptest.NewRecorder()
	h.ServeHTTP(problem, newRequest(payload("Too many connections", "2026-07-31T10:00:01Z"), "agent-secret"))

	if problem.Code != http.StatusCreated || evidence["severity"] != "problem" || evidence["category"] != "db_too_many_connections" {
		t.Fatalf("status=%d evidence=%#v", problem.Code, evidence)
	}
	classification, ok := evidence["classification"].(map[string]any)
	if !ok || classification["rule_id"] != "db.connection_limit.v1" {
		t.Fatalf("classification=%#v", evidence["classification"])
	}
	context, ok := evidence["context_before"].([]any)
	if !ok || len(context) != 1 {
		t.Fatalf("context=%#v", evidence["context_before"])
	}
}

func TestTrafficIsAggregatedAndOnlyAnomalyIsForwarded(t *testing.T) {
	var evidenceCount atomic.Int64
	var evidence map[string]any
	python := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/internal/agents/validate":
			writeJSON(w, http.StatusOK, map[string]any{"valid": true})
		case "/internal/evidence":
			evidenceCount.Add(1)
			if err := json.NewDecoder(r.Body).Decode(&evidence); err != nil {
				t.Fatal(err)
			}
			writeJSON(w, http.StatusCreated, map[string]any{"event_id": "evt_traffic", "incident_id": "inc_traffic"})
		default:
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
	}))
	defer python.Close()

	detector, err := traffic.NewWithConfig(traffic.Defaults())
	if err != nil {
		t.Fatal(err)
	}
	metrics := &Metrics{}
	h, err := New(http.NotFoundHandler(), python.URL, python.Client(), "gateway-secret", 8192, time.Minute, contextbuffer.New(), detector, metrics)
	if err != nil {
		t.Fatal(err)
	}

	for i := 0; i < 19; i++ {
		recorder := httptest.NewRecorder()
		h.ServeHTTP(recorder, newRequest(trafficPayload(500), "agent-secret"))
		if recorder.Code != http.StatusCreated {
			t.Fatalf("request %d status=%d body=%s", i+1, recorder.Code, recorder.Body.String())
		}
		var response map[string]any
		_ = json.Unmarshal(recorder.Body.Bytes(), &response)
		if response["buffered"] != true || response["severity"] != "normal" || response["category"] != "traffic_aggregate" {
			t.Fatalf("request %d response=%#v", i+1, response)
		}
	}
	if evidenceCount.Load() != 0 {
		t.Fatalf("normal aggregate forwarded %d evidence events", evidenceCount.Load())
	}

	recorder := httptest.NewRecorder()
	h.ServeHTTP(recorder, newRequest(trafficPayload(500), "agent-secret"))
	if recorder.Code != http.StatusCreated || evidenceCount.Load() != 1 {
		t.Fatalf("anomaly status=%d evidence_count=%d body=%s", recorder.Code, evidenceCount.Load(), recorder.Body.String())
	}
	if evidence["severity"] != "problem" || evidence["category"] != "traffic_anomaly" || evidence["signal_type"] != "traffic" {
		t.Fatalf("unexpected traffic evidence: %#v", evidence)
	}
	aggregate, ok := evidence["traffic_anomaly"].(map[string]any)
	if !ok || aggregate["route"] != "/api/orders/:id" || aggregate["request_count"] != float64(20) || aggregate["status_5xx_count"] != float64(20) {
		t.Fatalf("unexpected traffic aggregate: %#v", evidence["traffic_anomaly"])
	}
	if metrics.Snapshot().Buffered != 19 || metrics.Snapshot().Forwarded != 1 {
		t.Fatalf("unexpected metrics: %+v", metrics.Snapshot())
	}
}

func TestInvalidAgentTokenReturnsUnauthorized(t *testing.T) {
	python := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"valid": false})
	}))
	defer python.Close()
	metrics := &Metrics{}
	h, _ := New(http.NotFoundHandler(), python.URL, python.Client(), "gateway-secret", 8192, time.Minute, contextbuffer.New(), nil, metrics)
	recorder := httptest.NewRecorder()
	h.ServeHTTP(recorder, newRequest(payload("normal", "2026-07-31T10:00:00Z"), "wrong"))
	if recorder.Code != http.StatusUnauthorized || metrics.Snapshot().Unauthorized != 1 {
		t.Fatalf("status=%d metrics=%+v", recorder.Code, metrics.Snapshot())
	}
}

func TestValidationFailureFallsBackWithOriginalBody(t *testing.T) {
	python := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer python.Close()
	original := payload("normal line", "2026-07-31T10:00:00Z")
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		if !bytes.Equal(body, original) {
			t.Fatalf("fallback body changed: %s", body)
		}
		w.WriteHeader(http.StatusAccepted)
	})
	metrics := &Metrics{}
	h, _ := New(next, python.URL, python.Client(), "gateway-secret", 8192, time.Minute, contextbuffer.New(), nil, metrics)
	recorder := httptest.NewRecorder()
	h.ServeHTTP(recorder, newRequest(original, "agent-secret"))
	if recorder.Code != http.StatusAccepted || metrics.Snapshot().Fallback != 1 {
		t.Fatalf("status=%d metrics=%+v", recorder.Code, metrics.Snapshot())
	}
}

func TestOtherRoutesPassThrough(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusNoContent) })
	h, _ := New(next, "http://127.0.0.1:1", http.DefaultClient, "secret", 8192, time.Minute, contextbuffer.New(), nil, nil)
	recorder := httptest.NewRecorder()
	h.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/api/agents", nil))
	if recorder.Code != http.StatusNoContent {
		t.Fatalf("status=%d", recorder.Code)
	}
}

func TestUnknownLengthOversizedBodyFallsBackByteForByte(t *testing.T) {
	original := bytes.Repeat([]byte("x"), 128)
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		if !bytes.Equal(body, original) {
			t.Fatalf("fallback body length=%d want=%d", len(body), len(original))
		}
		w.WriteHeader(http.StatusAccepted)
	})
	h, _ := New(next, "http://127.0.0.1:1", http.DefaultClient, "secret", 32, time.Minute, contextbuffer.New(), nil, nil)
	req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(original))
	req.ContentLength = -1
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	h.ServeHTTP(recorder, req)
	if recorder.Code != http.StatusAccepted {
		t.Fatalf("status=%d", recorder.Code)
	}
}

func TestAuthCacheIsBoundedAndEvictsDeterministically(t *testing.T) {
	now := time.Date(2026, 7, 31, 10, 0, 0, 0, time.UTC)
	cache := newAuthCache(time.Minute, 2)
	cache.now = func() time.Time { return now }
	cache.store("b")
	now = now.Add(time.Second)
	cache.store("a")
	now = now.Add(time.Second)
	cache.store("c")
	if len(cache.expires) != 2 || cache.valid("b") || !cache.valid("a") || !cache.valid("c") {
		t.Fatalf("unexpected bounded cache: %#v", cache.expires)
	}
}
