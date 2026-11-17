package router

import (
	"encoding/json"
	"io"
	"net/http"
)

func New(proxyHandler http.Handler, pythonHealthURL string, client *http.Client) http.Handler {
	return newHandler(proxyHandler, pythonHealthURL, client, "", nil)
}

func NewWithMetrics(
	proxyHandler http.Handler,
	pythonHealthURL string,
	client *http.Client,
	metricsSnapshot func() any,
) http.Handler {
	return NewWithRuntimeStats(proxyHandler, pythonHealthURL, client, "shadow", metricsSnapshot)
}

func NewWithRuntimeStats(
	proxyHandler http.Handler,
	pythonHealthURL string,
	client *http.Client,
	statsKey string,
	statsSnapshot func() any,
) http.Handler {
	return newHandler(proxyHandler, pythonHealthURL, client, statsKey, statsSnapshot)
}

func newHandler(
	proxyHandler http.Handler,
	pythonHealthURL string,
	client *http.Client,
	statsKey string,
	metricsSnapshot func() any,
) http.Handler {
	if client == nil {
		client = http.DefaultClient
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet && r.URL.Path == "/health" {
			handleHealth(w, r, pythonHealthURL, client, statsKey, metricsSnapshot)
			return
		}
		proxyHandler.ServeHTTP(w, r)
	})
}

func handleHealth(
	w http.ResponseWriter,
	incoming *http.Request,
	pythonHealthURL string,
	client *http.Client,
	statsKey string,
	metricsSnapshot func() any,
) {
	pythonStatus := "ok"
	req, err := http.NewRequestWithContext(incoming.Context(), http.MethodGet, pythonHealthURL, nil)
	if err != nil {
		pythonStatus = "unavailable"
	}
	var resp *http.Response
	if err == nil {
		resp, err = client.Do(req)
	}
	if err != nil {
		pythonStatus = "unavailable"
	} else {
		_, _ = io.CopyN(io.Discard, resp.Body, 4096)
		resp.Body.Close()
		if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
			pythonStatus = "unavailable"
		}
	}

	overallStatus := "ok"
	if pythonStatus != "ok" {
		overallStatus = "degraded"
	}

	body := map[string]any{
		"status": overallStatus,
		"python": pythonStatus,
	}
	if metricsSnapshot != nil && statsKey != "" {
		body[statsKey] = metricsSnapshot()
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(body)
}
