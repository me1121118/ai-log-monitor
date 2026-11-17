package classifier

import (
	"time"

	"ai-log-server/server/gateway/internal/parser"
	"ai-log-server/server/gateway/internal/profile"
)

type Event struct {
	Service           string    `json:"service"`
	LogType           string    `json:"log_type"`
	FilePath          string    `json:"file_path"`
	Message           string    `json:"message"`
	NormalizedMessage string    `json:"normalized_message"`
	StatusCode        *int      `json:"status_code"`
	Severity          string    `json:"severity"`
	Fingerprint       string    `json:"fingerprint"`
	WebsiteID         string    `json:"website_id"`
	AgentID           string    `json:"agent_id"`
	SourceID          string    `json:"source_id"`
	Timestamp         time.Time `json:"timestamp"`
}

type Classification struct {
	RuleID     string   `json:"rule_id"`
	Confidence float64  `json:"confidence"`
	Basis      []string `json:"basis"`
}

type Result struct {
	SignalType     string
	Severity       string
	Category       string
	Classification Classification
	SourceProfile  profile.SourceProfile
	ParsedFields   *parser.ParsedFields
	Fingerprint    string
}
