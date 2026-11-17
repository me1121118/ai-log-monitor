package shadow

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"

	"ai-log-server/server/gateway/internal/classifier"
)

func TestMetrics_Snapshot(t *testing.T) {
	m := &Metrics{}
	m.Inspected.Add(10)
	m.Matched.Add(3)
	m.Mismatched.Add(1)
	m.Bypassed.Add(5)

	snap := m.Snapshot()
	if snap.Inspected != 10 {
		t.Errorf("Inspected = %d, want 10", snap.Inspected)
	}
	if snap.Matched != 3 {
		t.Errorf("Matched = %d, want 3", snap.Matched)
	}
	if snap.Mismatched != 1 {
		t.Errorf("Mismatched = %d, want 1", snap.Mismatched)
	}
	if snap.Bypassed != 5 {
		t.Errorf("Bypassed = %d, want 5", snap.Bypassed)
	}
}

func TestNew_BypassesNonPOST(t *testing.T) {
	var m Metrics
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"ok"}`))
	})
	h := New(next, 4096, &m)

	req := httptest.NewRequest(http.MethodGet, "/api/ingest", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	snap := m.Snapshot()
	if snap.Bypassed != 0 {
		t.Errorf("Bypassed = %d, want 0 for non-ingest traffic", snap.Bypassed)
	}
	if snap.Inspected != 0 {
		t.Errorf("Inspected = %d, want 0", snap.Inspected)
	}
}

func TestNew_BypassesNonIngestPath(t *testing.T) {
	var m Metrics
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"ok"}`))
	})
	h := New(next, 4096, &m)

	req := httptest.NewRequest(http.MethodPost, "/api/other", nil)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	snap := m.Snapshot()
	if snap.Bypassed != 0 {
		t.Errorf("Bypassed = %d, want 0 for non-ingest traffic", snap.Bypassed)
	}
}

func TestNew_BypassesNonJSONContentType(t *testing.T) {
	var m Metrics
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"ok"}`))
	})
	h := New(next, 4096, &m)

	req := httptest.NewRequest(http.MethodPost, "/api/ingest", nil)
	req.Header.Set("Content-Type", "text/plain")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	snap := m.Snapshot()
	if snap.Bypassed != 1 {
		t.Errorf("Bypassed = %d, want 1", snap.Bypassed)
	}
}

func TestNew_BypassesOversizedBody(t *testing.T) {
	var m Metrics
	var gotBody []byte
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotBody, _ = io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"ok"}`))
	})
	maxBody := int64(16)
	h := New(next, maxBody, &m)

	body := bytes.Repeat([]byte{'x'}, int(maxBody+50))
	req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(body))
	req.ContentLength = -1
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	snap := m.Snapshot()
	if snap.Bypassed != 1 {
		t.Errorf("Bypassed = %d, want 1", snap.Bypassed)
	}
	if !bytes.Equal(gotBody, body) {
		t.Fatalf("oversized request was not replayed byte-for-byte: got %d bytes, want %d", len(gotBody), len(body))
	}
}

func TestNew_BypassesMalformedJSON(t *testing.T) {
	var m Metrics
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"ok"}`))
	})
	h := New(next, 4096, &m)

	body := []byte(`{invalid json`)
	req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	snap := m.Snapshot()
	if snap.Bypassed != 1 {
		t.Errorf("Bypassed = %d, want 1", snap.Bypassed)
	}
}

func TestNew_BypassesJSONArray(t *testing.T) {
	var m Metrics
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"ok"}`))
	})
	h := New(next, 4096, &m)

	body := []byte(`[{"service":"test","message":"hello"}]`)
	req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	snap := m.Snapshot()
	if snap.Bypassed != 1 {
		t.Errorf("Bypassed = %d, want 1", snap.Bypassed)
	}
}

func TestNew_PreservesRequestBody(t *testing.T) {
	var m Metrics
	var gotBody []byte
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var err error
		gotBody, err = io.ReadAll(r.Body)
		if err != nil {
			t.Errorf("reading body: %v", err)
		}
		r.Body.Close()
		w.WriteHeader(http.StatusOK)
	})
	h := New(next, 4096, &m)

	body := []byte(`{"service":"test","log_type":"app","file_path":"/var/log/app.log","message":"hello world"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if !bytes.Equal(gotBody, body) {
		t.Errorf("request body mismatch:\ngot:  %q\nwant: %q", gotBody, body)
	}
}

func TestNew_ForwardsResponseStatusHeadersBody(t *testing.T) {
	var m Metrics
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Custom", "test-value")
		w.WriteHeader(http.StatusCreated)
		w.Write([]byte(`{"status":"created"}`))
	})
	h := New(next, 4096, &m)

	body := []byte(`{"service":"test","log_type":"app","file_path":"/var/log/app.log","message":"hello"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Errorf("status = %d, want %d", rec.Code, http.StatusCreated)
	}
	if rec.Header().Get("X-Custom") != "test-value" {
		t.Errorf("X-Custom = %q, want %q", rec.Header().Get("X-Custom"), "test-value")
	}
	wantBody := `{"status":"created"}`
	if rec.Body.String() != wantBody {
		t.Errorf("body = %q, want %q", rec.Body.String(), wantBody)
	}
}

func TestNew_MatchedClassification(t *testing.T) {
	var m Metrics
	ev := classifier.Event{
		Service:           "test",
		LogType:           "app",
		FilePath:          "/var/log/app.log",
		Message:           "out of memory",
		NormalizedMessage: "out of memory",
	}
	result := classifier.ClassifyEvent(ev)

	upstreamResp := map[string]string{
		"severity": result.Severity,
		"category": result.Category,
	}
	respBody, _ := json.Marshal(upstreamResp)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write(respBody)
	})
	h := New(next, 4096, &m)

	reqBody, _ := json.Marshal(ev)
	req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	snap := m.Snapshot()
	if snap.Inspected != 1 {
		t.Errorf("Inspected = %d, want 1", snap.Inspected)
	}
	if snap.Matched != 1 {
		t.Errorf("Matched = %d, want 1", snap.Matched)
	}
	if snap.Mismatched != 0 {
		t.Errorf("Mismatched = %d, want 0", snap.Mismatched)
	}
	if snap.Bypassed != 0 {
		t.Errorf("Bypassed = %d, want 0", snap.Bypassed)
	}
}

func TestNew_MismatchedClassification(t *testing.T) {
	var m Metrics
	ev := classifier.Event{
		Service:           "test",
		LogType:           "app",
		FilePath:          "/var/log/app.log",
		Message:           "out of memory",
		NormalizedMessage: "out of memory",
	}

	upstreamResp := map[string]string{
		"severity": "wrong",
		"category": "wrong",
	}
	respBody, _ := json.Marshal(upstreamResp)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write(respBody)
	})
	h := New(next, 4096, &m)

	reqBody, _ := json.Marshal(ev)
	req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	snap := m.Snapshot()
	if snap.Inspected != 1 {
		t.Errorf("Inspected = %d, want 1", snap.Inspected)
	}
	if snap.Matched != 0 {
		t.Errorf("Matched = %d, want 0", snap.Matched)
	}
	if snap.Mismatched != 1 {
		t.Errorf("Mismatched = %d, want 1", snap.Mismatched)
	}
	if snap.Bypassed != 0 {
		t.Errorf("Bypassed = %d, want 0", snap.Bypassed)
	}
}

func TestNew_ForwardsResponseOnBypass(t *testing.T) {
	var m Metrics
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Proxied", "true")
		w.WriteHeader(http.StatusAccepted)
		w.Write([]byte(`{"proxied":true}`))
	})
	h := New(next, 4096, &m)

	req := httptest.NewRequest(http.MethodOptions, "/api/ingest", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusAccepted {
		t.Errorf("status = %d, want %d", rec.Code, http.StatusAccepted)
	}
	if rec.Header().Get("X-Proxied") != "true" {
		t.Errorf("X-Proxied = %q, want %q", rec.Header().Get("X-Proxied"), "true")
	}
	if rec.Body.String() != `{"proxied":true}` {
		t.Errorf("body = %q, want %q", rec.Body.String(), `{"proxied":true}`)
	}
}

func TestNew_RequiresExactPath(t *testing.T) {
	var m Metrics
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	h := New(next, 4096, &m)

	req := httptest.NewRequest(http.MethodPost, "/api/ingest/extra", nil)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	snap := m.Snapshot()
	if snap.Bypassed != 0 {
		t.Errorf("Bypassed = %d, want 0 for non-ingest traffic", snap.Bypassed)
	}
}

func TestNew_ZeroMaxBodyBytes(t *testing.T) {
	var m Metrics
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	h := New(next, 0, &m)

	body := []byte(`{}`)
	req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	snap := m.Snapshot()
	if snap.Bypassed != 1 {
		t.Errorf("Bypassed = %d, want 1 (body exceeds 0)", snap.Bypassed)
	}
}

func TestNew_ExactlyMaxBodyBytes(t *testing.T) {
	var m Metrics
	ev := classifier.Event{
		Service:           "test",
		LogType:           "app",
		FilePath:          "/var/log/app.log",
		Message:           "out of memory",
		NormalizedMessage: "out of memory",
	}
	result := classifier.ClassifyEvent(ev)

	upstreamResp := map[string]string{
		"severity": result.Severity,
		"category": result.Category,
	}
	respBody, _ := json.Marshal(upstreamResp)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write(respBody)
	})

	reqBody, _ := json.Marshal(ev)
	maxBody := int64(len(reqBody))

	h := New(next, maxBody, &m)

	req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	snap := m.Snapshot()
	if snap.Inspected != 1 {
		t.Errorf("Inspected = %d, want 1", snap.Inspected)
	}
	if snap.Bypassed != 0 {
		t.Errorf("Bypassed = %d, want 0", snap.Bypassed)
	}
}

func TestNew_CapturesUpTo64KiBResponse(t *testing.T) {
	var m Metrics
	ev := classifier.Event{
		Service:           "test",
		LogType:           "app",
		FilePath:          "/var/log/app.log",
		Message:           "out of memory",
		NormalizedMessage: "out of memory",
	}
	result := classifier.ClassifyEvent(ev)

	upstreamResp := map[string]string{
		"severity": result.Severity,
		"category": result.Category,
	}
	respJSON, _ := json.Marshal(upstreamResp)

	largePrefix := bytes.Repeat([]byte{'x'}, 64*1024)
	fullResp := append(largePrefix, respJSON...)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write(fullResp)
	})
	h := New(next, 4096, &m)

	reqBody, _ := json.Marshal(ev)
	req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(reqBody))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if !bytes.Equal(rec.Body.Bytes(), fullResp) {
		t.Error("response body was not forwarded unchanged")
	}

	snap := m.Snapshot()
	if snap.Inspected != 1 {
		t.Errorf("Inspected = %d, want 1", snap.Inspected)
	}
	if snap.Matched != 0 {
		t.Errorf("Matched = %d, want 0 (severity/category beyond 64KiB)", snap.Matched)
	}
	if snap.Mismatched != 1 {
		t.Errorf("Mismatched = %d, want 1 for an unparseable bounded response", snap.Mismatched)
	}
}

func TestNew_ReadErrorBypasses(t *testing.T) {
	var m Metrics
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	h := New(next, 4096, &m)

	req := httptest.NewRequest(http.MethodPost, "/api/ingest", errReader{})
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	snap := m.Snapshot()
	if snap.Bypassed != 1 {
		t.Errorf("Bypassed = %d, want 1", snap.Bypassed)
	}
}

type errReader struct{}

func (errReader) Read([]byte) (int, error) { return 0, io.ErrUnexpectedEOF }

func TestNew_ConcurrentAtomicMetrics(t *testing.T) {
	var m Metrics
	ev := classifier.Event{
		Service:           "test",
		LogType:           "app",
		FilePath:          "/var/log/app.log",
		Message:           "out of memory",
		NormalizedMessage: "out of memory",
	}
	result := classifier.ClassifyEvent(ev)

	upstreamResp := map[string]string{
		"severity": result.Severity,
		"category": result.Category,
	}
	respBody, _ := json.Marshal(upstreamResp)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write(respBody)
	})
	h := New(next, 4096, &m)

	reqBody, _ := json.Marshal(ev)

	n := 64
	var wg sync.WaitGroup
	wg.Add(n)

	for range n {
		go func() {
			defer wg.Done()
			req := httptest.NewRequest(http.MethodPost, "/api/ingest", bytes.NewReader(reqBody))
			req.Header.Set("Content-Type", "application/json")
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)

			if rec.Code != http.StatusOK {
				t.Errorf("status = %d, want %d", rec.Code, http.StatusOK)
			}
			if !bytes.Equal(rec.Body.Bytes(), respBody) {
				t.Error("response body changed by shadow handler")
			}
		}()
	}
	wg.Wait()

	snap := m.Snapshot()
	if snap.Inspected != int64(n) {
		t.Errorf("Inspected = %d, want %d", snap.Inspected, n)
	}
	if snap.Matched != int64(n) {
		t.Errorf("Matched = %d, want %d", snap.Matched, n)
	}
	if snap.Mismatched != 0 {
		t.Errorf("Mismatched = %d, want 0", snap.Mismatched)
	}
	if snap.Bypassed != 0 {
		t.Errorf("Bypassed = %d, want 0", snap.Bypassed)
	}
}
