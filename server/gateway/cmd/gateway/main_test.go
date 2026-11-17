package main

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"ai-log-server/server/gateway/internal/config"
)

func TestRunShutsDownOnContextCancel(t *testing.T) {
	cfg := config.Config{
		ListenAddress:       "127.0.0.1:0",
		PythonBaseURL:       "http://127.0.0.1:1",
		UpstreamTimeout:     5 * time.Second,
		ReadHeaderTimeout:   5 * time.Second,
		IdleTimeout:         10 * time.Second,
		MaxInspectBodyBytes: 8192,
	}

	ctx, cancel := context.WithCancel(context.Background())

	errCh := make(chan error, 1)
	go func() {
		errCh <- run(ctx, cfg)
	}()

	cancel()

	select {
	case err := <-errCh:
		if err != nil && err != http.ErrServerClosed {
			t.Fatalf("run() returned unexpected error: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("run() did not shut down within 2s")
	}
}

func TestRunStartsAndRespondsToHealth(t *testing.T) {
	python := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer python.Close()

	// Find a free port so we can probe the server
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := listener.Addr().String()
	listener.Close()

	cfg := config.Config{
		ListenAddress:       addr,
		PythonBaseURL:       python.URL,
		UpstreamTimeout:     5 * time.Second,
		ReadHeaderTimeout:   5 * time.Second,
		IdleTimeout:         10 * time.Second,
		MaxInspectBodyBytes: 8192,
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	errCh := make(chan error, 1)
	go func() {
		errCh <- run(ctx, cfg)
	}()

	// Probe until the health endpoint responds or timeout
	var lastErr error
	healthURL := fmt.Sprintf("http://%s/health", addr)
	start := time.Now()
	for time.Since(start) < 500*time.Millisecond {
		resp, e := http.Get(healthURL)
		if e == nil {
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				goto ok
			}
		}
		lastErr = e
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("server did not respond to health within 500ms (lastErr: %v)", lastErr)
ok:
	cancel()
	select {
	case err := <-errCh:
		if err != nil {
			t.Fatalf("run() returned error: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("run() did not stop after cancellation")
	}
}
