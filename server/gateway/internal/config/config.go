package config

import (
	"fmt"
	"net/url"
	"os"
	"strconv"
	"time"
)

type Config struct {
	ListenAddress        string
	PythonBaseURL        string
	UpstreamTimeout      time.Duration
	ReadHeaderTimeout    time.Duration
	IdleTimeout          time.Duration
	MaxInspectBodyBytes  int64
	IngestMode           string
	GatewayInternalToken string
	AgentAuthCacheTTL    time.Duration
}

func Load() (Config, error) {
	upstreamTimeout, err := durationEnv("GATEWAY_UPSTREAM_TIMEOUT", 30*time.Second)
	if err != nil {
		return Config{}, err
	}
	readHeaderTimeout, err := durationEnv("GATEWAY_READ_HEADER_TIMEOUT", 10*time.Second)
	if err != nil {
		return Config{}, err
	}
	idleTimeout, err := durationEnv("GATEWAY_IDLE_TIMEOUT", 90*time.Second)
	if err != nil {
		return Config{}, err
	}
	maxInspectBodyBytes, err := positiveInt64Env("GATEWAY_MAX_INSPECT_BODY_BYTES", 8192)
	if err != nil {
		return Config{}, err
	}
	agentAuthCacheTTL, err := durationEnv("GATEWAY_AGENT_AUTH_CACHE_TTL", 5*time.Minute)
	if err != nil {
		return Config{}, err
	}
	ingestMode := envOrDefault("GATEWAY_INGEST_MODE", "shadow")
	if ingestMode != "shadow" && ingestMode != "evidence" {
		return Config{}, fmt.Errorf("invalid GATEWAY_INGEST_MODE %q", ingestMode)
	}
	internalToken := os.Getenv("GATEWAY_INTERNAL_TOKEN")
	if ingestMode == "evidence" && internalToken == "" {
		return Config{}, fmt.Errorf("GATEWAY_INTERNAL_TOKEN is required in evidence mode")
	}
	pythonBaseURL := envOrDefault("PYTHON_BASE_URL", "http://localhost:8889")
	parsedURL, err := url.ParseRequestURI(pythonBaseURL)
	if err != nil || (parsedURL.Scheme != "http" && parsedURL.Scheme != "https") || parsedURL.Host == "" {
		return Config{}, fmt.Errorf("invalid PYTHON_BASE_URL %q", pythonBaseURL)
	}

	return Config{
		ListenAddress:        envOrDefault("GATEWAY_LISTEN_ADDRESS", ":8888"),
		PythonBaseURL:        pythonBaseURL,
		UpstreamTimeout:      upstreamTimeout,
		ReadHeaderTimeout:    readHeaderTimeout,
		IdleTimeout:          idleTimeout,
		MaxInspectBodyBytes:  maxInspectBodyBytes,
		IngestMode:           ingestMode,
		GatewayInternalToken: internalToken,
		AgentAuthCacheTTL:    agentAuthCacheTTL,
	}, nil
}

func envOrDefault(key, defaultVal string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return defaultVal
}

func durationEnv(key string, defaultVal time.Duration) (time.Duration, error) {
	if v := os.Getenv(key); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil || d <= 0 {
			return 0, fmt.Errorf("invalid %s %q", key, v)
		}
		return d, nil
	}
	return defaultVal, nil
}

func positiveInt64Env(key string, defaultVal int64) (int64, error) {
	if v := os.Getenv(key); v != "" {
		n, err := strconv.ParseInt(v, 10, 64)
		if err != nil || n <= 0 {
			return 0, fmt.Errorf("invalid %s %q", key, v)
		}
		return n, nil
	}
	return defaultVal, nil
}
