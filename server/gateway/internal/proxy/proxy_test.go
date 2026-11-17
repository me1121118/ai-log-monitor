package proxy

import (
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

func TestProxyPreservesQueryString(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.RawQuery != "foo=bar&baz=qux" {
			t.Errorf("RawQuery = %q, want %q", r.URL.RawQuery, "foo=bar&baz=qux")
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	u, _ := url.Parse(backend.URL)
	handler := New(u, nil)
	frontend := httptest.NewServer(handler)
	defer frontend.Close()

	resp, err := http.Get(frontend.URL + "/path?foo=bar&baz=qux")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
}

func TestProxyPreservesRequestBody(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatal(err)
		}
		if string(body) != "hello world" {
			t.Errorf("body = %q, want %q", string(body), "hello world")
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	u, _ := url.Parse(backend.URL)
	handler := New(u, nil)
	frontend := httptest.NewServer(handler)
	defer frontend.Close()

	resp, err := http.Post(frontend.URL+"/path", "text/plain", strings.NewReader("hello world"))
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
}

func TestProxyPreservesSetCookie(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Set-Cookie", "session=abc123; Path=/")
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	u, _ := url.Parse(backend.URL)
	handler := New(u, nil)
	frontend := httptest.NewServer(handler)
	defer frontend.Close()

	resp, err := http.Get(frontend.URL + "/login")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if got := resp.Header.Get("Set-Cookie"); got != "session=abc123; Path=/" {
		t.Errorf("Set-Cookie = %q, want %q", got, "session=abc123; Path=/")
	}
}

func TestProxyPreservesStatusCode(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer backend.Close()

	u, _ := url.Parse(backend.URL)
	handler := New(u, nil)
	frontend := httptest.NewServer(handler)
	defer frontend.Close()

	resp, err := http.Get(frontend.URL + "/missing")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()

	if resp.StatusCode != http.StatusNotFound {
		t.Errorf("StatusCode = %d, want %d", resp.StatusCode, http.StatusNotFound)
	}
}

func TestProxyPreservesStaticPaths(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/static/css/styles.css" {
			t.Errorf("Path = %q, want %q", r.URL.Path, "/static/css/styles.css")
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	u, _ := url.Parse(backend.URL)
	handler := New(u, nil)
	frontend := httptest.NewServer(handler)
	defer frontend.Close()

	resp, err := http.Get(frontend.URL + "/static/css/styles.css")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
}

func TestProxyStripsInternalAuth(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if v := r.Header.Get("X-Internal-Auth"); v != "" {
			t.Errorf("X-Internal-Auth = %q, should be stripped", v)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()

	u, _ := url.Parse(backend.URL)
	handler := New(u, nil)
	frontend := httptest.NewServer(handler)
	defer frontend.Close()

	req, _ := http.NewRequest("GET", frontend.URL+"/path", nil)
	req.Header.Set("X-Internal-Auth", "secret-token")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
}

func TestProxyUnavailableUpstreamReturns503(t *testing.T) {
	u, _ := url.Parse("http://127.0.0.1:1")
	transport := &http.Transport{
		DialContext: (&net.Dialer{Timeout: 50 * time.Millisecond}).DialContext,
	}
	handler := New(u, transport)
	frontend := httptest.NewServer(handler)
	defer frontend.Close()

	resp, err := http.Get(frontend.URL + "/api/ingest")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Errorf("StatusCode = %d, want %d", resp.StatusCode, http.StatusServiceUnavailable)
	}

	body, _ := io.ReadAll(resp.Body)
	var payload map[string]string
	if err := json.Unmarshal(body, &payload); err != nil {
		t.Fatalf("response body is not valid JSON: %v", err)
	}
	if payload["error"] != "upstream unavailable" {
		t.Errorf("error message = %q, want %q", payload["error"], "upstream unavailable")
	}
}
