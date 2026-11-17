package ingest

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"ai-log-server/server/gateway/internal/classifier"
	"ai-log-server/server/gateway/internal/contextbuffer"
	"ai-log-server/server/gateway/internal/traffic"
)

type Metrics struct {
	Buffered     atomic.Int64
	Forwarded    atomic.Int64
	Fallback     atomic.Int64
	Unauthorized atomic.Int64
}

type MetricsSnapshot struct {
	Buffered     int64 `json:"buffered"`
	Forwarded    int64 `json:"forwarded"`
	Fallback     int64 `json:"fallback"`
	Unauthorized int64 `json:"unauthorized"`
}

func (m *Metrics) Snapshot() MetricsSnapshot {
	return MetricsSnapshot{m.Buffered.Load(), m.Forwarded.Load(), m.Fallback.Load(), m.Unauthorized.Load()}
}

type authCache struct {
	mu      sync.Mutex
	expires map[string]time.Time
	ttl     time.Duration
	max     int
	now     func() time.Time
}

func newAuthCache(ttl time.Duration, maxEntries int) *authCache {
	return &authCache{expires: make(map[string]time.Time), ttl: ttl, max: maxEntries, now: time.Now}
}

func (c *authCache) valid(key string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	expires, ok := c.expires[key]
	if !ok || !c.now().Before(expires) {
		delete(c.expires, key)
		return false
	}
	return true
}

func (c *authCache) store(key string) {
	c.mu.Lock()
	now := c.now()
	for candidate, expires := range c.expires {
		if !now.Before(expires) {
			delete(c.expires, candidate)
		}
	}
	if _, exists := c.expires[key]; !exists && len(c.expires) >= c.max {
		oldestKey := ""
		var oldestExpiry time.Time
		for candidate, expires := range c.expires {
			if oldestKey == "" || expires.Before(oldestExpiry) || (expires.Equal(oldestExpiry) && candidate < oldestKey) {
				oldestKey, oldestExpiry = candidate, expires
			}
		}
		delete(c.expires, oldestKey)
	}
	c.expires[key] = now.Add(c.ttl)
	c.mu.Unlock()
}

type Handler struct {
	next          http.Handler
	client        *http.Client
	validateURL   string
	evidenceURL   string
	internalToken string
	maxBodyBytes  int64
	buffer        *contextbuffer.Buffer
	traffic       *traffic.Detector
	metrics       *Metrics
	auth          *authCache
}

func New(next http.Handler, pythonBaseURL string, client *http.Client, internalToken string, maxBodyBytes int64, authTTL time.Duration, buffer *contextbuffer.Buffer, trafficDetector *traffic.Detector, metrics *Metrics) (http.Handler, error) {
	base, err := url.Parse(pythonBaseURL)
	if err != nil {
		return nil, err
	}
	if next == nil || client == nil || internalToken == "" || maxBodyBytes <= 0 || authTTL <= 0 {
		return nil, fmt.Errorf("ingest: invalid handler configuration")
	}
	if buffer == nil {
		buffer = contextbuffer.New()
	}
	if trafficDetector == nil {
		trafficDetector = traffic.New()
	}
	if metrics == nil {
		metrics = &Metrics{}
	}
	return &Handler{
		next: next, client: client, internalToken: internalToken, maxBodyBytes: maxBodyBytes,
		validateURL: base.ResolveReference(&url.URL{Path: "/internal/agents/validate"}).String(),
		evidenceURL: base.ResolveReference(&url.URL{Path: "/internal/evidence"}).String(),
		buffer:      buffer, traffic: trafficDetector, metrics: metrics, auth: newAuthCache(authTTL, 4096),
	}, nil
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || r.URL.Path != "/api/ingest" {
		h.next.ServeHTTP(w, r)
		return
	}
	mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || !strings.EqualFold(mediaType, "application/json") || r.ContentLength > h.maxBodyBytes {
		h.fallback(w, r)
		return
	}
	originalBody := r.Body
	body, err := io.ReadAll(io.LimitReader(originalBody, h.maxBodyBytes+1))
	r.Body = &replayReadCloser{
		Reader: io.MultiReader(bytes.NewReader(body), originalBody),
		Closer: originalBody,
	}
	if err != nil || int64(len(body)) > h.maxBodyBytes || len(bytes.TrimSpace(body)) == 0 {
		h.fallback(w, r)
		return
	}
	var event classifier.Event
	var payload map[string]any
	if json.Unmarshal(body, &event) != nil || json.Unmarshal(body, &payload) != nil || event.WebsiteID == "" || event.AgentID == "" || strings.TrimSpace(event.Message) == "" {
		h.fallback(w, r)
		return
	}
	if event.SourceID == "" {
		event.SourceID = event.FilePath
	}
	agentToken := r.Header.Get("X-Agent-Token")
	valid, err := h.validateAgent(r, event.AgentID, agentToken)
	if err != nil {
		h.fallback(w, r)
		return
	}
	if !valid {
		h.metrics.Unauthorized.Add(1)
		writeJSON(w, http.StatusUnauthorized, map[string]any{"error": "invalid agent token"})
		return
	}
	result := classifier.ClassifyEvent(event)
	if result.SignalType == "traffic" && result.ParsedFields != nil && result.ParsedFields.StatusCode != nil {
		var latencyMS *int
		if result.ParsedFields.LatencyMS != nil && *result.ParsedFields.LatencyMS >= 0 {
			value := int(*result.ParsedFields.LatencyMS + 0.5)
			latencyMS = &value
		}
		anomaly := h.traffic.Observe(traffic.Observation{
			WebsiteID: event.WebsiteID, AgentID: event.AgentID, SourceID: event.SourceID,
			Method: result.ParsedFields.RequestMethod, Path: result.ParsedFields.RequestPath,
			StatusCode: *result.ParsedFields.StatusCode, LatencyMS: latencyMS, Timestamp: event.Timestamp,
		})
		if anomaly == nil {
			h.metrics.Buffered.Add(1)
			writeBuffered(w, body, "normal", "traffic_aggregate", result.Fingerprint)
			return
		}
		payload["message"] = anomaly.Reason
		payload["severity"] = anomaly.Severity
		payload["category"] = anomaly.Category
		payload["fingerprint"] = anomaly.Fingerprint
		payload["signal_type"] = "traffic"
		payload["traffic_anomaly"] = anomaly
		encoded, err := json.Marshal(payload)
		if err != nil || !h.forwardEvidence(w, r, encoded) {
			h.fallback(w, r)
			return
		}
		h.metrics.Forwarded.Add(1)
		return
	}
	if result.Severity == "normal" {
		h.buffer.Append(event, result.Severity)
		h.metrics.Buffered.Add(1)
		writeBuffered(w, body, result.Severity, result.Category, result.Fingerprint)
		return
	}
	payload["severity"] = result.Severity
	payload["category"] = result.Category
	payload["fingerprint"] = result.Fingerprint
	payload["signal_type"] = result.SignalType
	payload["classification"] = result.Classification
	if context := h.buffer.ContextFor(event); len(context) > 0 {
		payload["context_before"] = context
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		h.fallback(w, r)
		return
	}
	if !h.forwardEvidence(w, r, encoded) {
		h.fallback(w, r)
		return
	}
	h.metrics.Forwarded.Add(1)
}

func writeBuffered(w http.ResponseWriter, body []byte, severity, category, fingerprint string) {
	writeJSON(w, http.StatusCreated, map[string]any{
		"event_id": eventID(body), "incident_id": nil, "severity": severity,
		"category": category, "fingerprint": fingerprint, "buffered": true,
	})
}

type replayReadCloser struct {
	io.Reader
	io.Closer
}

func (h *Handler) validateAgent(r *http.Request, agentID, agentToken string) (bool, error) {
	sum := sha256.Sum256([]byte(agentID + "\x00" + agentToken))
	key := hex.EncodeToString(sum[:])
	if h.auth.valid(key) {
		return true, nil
	}
	body, _ := json.Marshal(map[string]string{"agent_id": agentID})
	req, err := http.NewRequestWithContext(r.Context(), http.MethodPost, h.validateURL, bytes.NewReader(body))
	if err != nil {
		return false, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Gateway-Token", h.internalToken)
	req.Header.Set("X-Agent-Token", agentToken)
	resp, err := h.client.Do(req)
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return false, fmt.Errorf("agent validation returned %d", resp.StatusCode)
	}
	var result struct {
		Valid bool `json:"valid"`
	}
	if json.NewDecoder(io.LimitReader(resp.Body, 64*1024)).Decode(&result) != nil {
		return false, fmt.Errorf("invalid agent validation response")
	}
	if result.Valid {
		h.auth.store(key)
	}
	return result.Valid, nil
}

func (h *Handler) forwardEvidence(w http.ResponseWriter, incoming *http.Request, body []byte) bool {
	req, err := http.NewRequestWithContext(incoming.Context(), http.MethodPost, h.evidenceURL, bytes.NewReader(body))
	if err != nil {
		return false
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Gateway-Token", h.internalToken)
	resp, err := h.client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return false
	}
	for key, values := range resp.Header {
		for _, value := range values {
			w.Header().Add(key, value)
		}
	}
	w.WriteHeader(resp.StatusCode)
	_, _ = io.Copy(w, io.LimitReader(resp.Body, 1024*1024))
	return true
}

func (h *Handler) fallback(w http.ResponseWriter, r *http.Request) {
	h.metrics.Fallback.Add(1)
	h.next.ServeHTTP(w, r)
}

func eventID(body []byte) string {
	sum := sha256.Sum256(body)
	return "evt_gateway_" + hex.EncodeToString(sum[:10])
}

func writeJSON(w http.ResponseWriter, status int, payload map[string]any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
