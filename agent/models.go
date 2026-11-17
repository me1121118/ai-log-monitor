package main

import "regexp"

type LogPath struct {
	Name           string   `yaml:"name"`
	Path           string   `yaml:"path"`
	Type           string   `yaml:"type"`
	Includes       []string `yaml:"includes,omitempty"`
	Discovered     bool     `yaml:"-"`
	Classification string   `yaml:"-"`
	Confidence     float64  `yaml:"-"`
}

// Config represents the parsed agent.yaml
type Config struct {
	Server struct {
		URL string `yaml:"url"`
	} `yaml:"server"`
	Enrollment struct {
		Token string `yaml:"token"`
	} `yaml:"enrollment"`
	Agent struct {
		Name      string `yaml:"name"`
		Role      string `yaml:"role"`
		WebsiteID string `yaml:"website_id"`
		ClusterID string `yaml:"cluster_id,omitempty"`
	} `yaml:"agent"`
	Logs struct {
		AutoDiscover      bool      `yaml:"auto_discover"`
		DiscoveryRoots    []string  `yaml:"discovery_roots"`
		DiscoveryMaxFiles int       `yaml:"discovery_max_files"`
		Paths             []LogPath `yaml:"paths"`
	} `yaml:"logs"`
	Filter struct {
		SendOnlyMatched bool     `yaml:"send_only_matched"`
		IncludeTraffic  bool     `yaml:"include_traffic,omitempty"`
		Keywords        []string `yaml:"keywords"`
	} `yaml:"filter"`
	Runtime struct {
		StateDir                 string `yaml:"state_dir"`
		ScanIntervalSeconds      int    `yaml:"scan_interval_seconds,omitempty"`
		HeartbeatIntervalSeconds int    `yaml:"heartbeat_interval_seconds"`
		SpoolMaxBytes            int64  `yaml:"spool_max_bytes"`
	} `yaml:"runtime"`
}

type Event struct {
	WebsiteID        string                 `json:"website_id"`
	AgentID          string                 `json:"agent_id"`
	AgentRole        string                 `json:"agent_role"`
	LogType          string                 `json:"log_type"`
	Service          string                 `json:"service"`
	FilePath         string                 `json:"file_path"`
	Timestamp        string                 `json:"timestamp"`
	Message          string                 `json:"message"`
	SourceID         string                 `json:"source_id"`
	SourceConfidence float64                `json:"source_confidence"`
	EventUID         string                 `json:"event_uid"`
	Multiline        bool                   `json:"multiline,omitempty"`
	LineCount        int                    `json:"line_count,omitempty"`
	Metadata         map[string]interface{} `json:"metadata,omitempty"`
}

type LogRecord struct {
	Message   string
	Multiline bool
	LineCount int
}

type TopologyHint struct {
	Source     string                 `json:"source"`
	HintType   string                 `json:"hint_type"`
	Target     string                 `json:"target"`
	Confidence float64                `json:"confidence"`
	LastSeenAt string                 `json:"last_seen_at,omitempty"`
	Metadata   map[string]interface{} `json:"metadata,omitempty"`
}

var builtInProblemTerms = []string{
	"error", "failed", "timeout", "timed out", "exception", "denied",
	"502", "503", "504", "connection refused", "too many connections",
	"no space left", "disk full",
}

var zeroValueMetricCounter = regexp.MustCompile(`(?i)(?:"(?:error|errors|failed|failure|failures|retry|retries|dropped|drop)"|(?:error|errors|failed|failure|failures|retry|retries|dropped|drop))\s*(?:=>|=|:)\s*["']?0["']?(?:\b|[,}\s])`)

var zeroProblemCounterPattern = regexp.MustCompile(
	`(?i)["']?(?:errors|error_count|failures|retries|dropped)["']?\s*(?::|=>|=)\s*["']?0(?:\.0+)?["']?`,
)

var httpStatusCodePattern = regexp.MustCompile(`(?:^|[^0-9])(?:502|503|504)(?:[^0-9]|$)`)

// Fluent Bit's cpu.local records are telemetry, not application log problems.
var normalTelemetryPattern = regexp.MustCompile(`(?i)\bcpu\.local\b`)
