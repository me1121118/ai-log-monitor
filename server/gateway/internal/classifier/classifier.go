package classifier

import (
	"strings"

	"ai-log-server/server/gateway/internal/parser"
	"ai-log-server/server/gateway/internal/profile"
)

func ClassifyEvent(ev Event) Result {
	prof := profile.ProfileSource(profile.EventSource{
		Service:  ev.Service,
		LogType:  ev.LogType,
		FilePath: ev.FilePath,
	})

	parsed := parser.ParseSignalFields(parser.EventInput{
		Message:    ev.Message,
		StatusCode: ev.StatusCode,
	})

	if ev.StatusCode == nil && parsed.StatusCode != nil {
		ev.StatusCode = parsed.StatusCode
	}

	message := strings.TrimSpace(ev.NormalizedMessage)
	if message == "" {
		message = strings.ToLower(strings.Join(strings.Fields(ev.Message), " "))
	}
	service := strings.ToLower(strings.ReplaceAll(ev.Service, "-", "_"))

	severity := "normal"
	category := "normal"

	isSudoCmd := strings.Contains(message, "sudo:") && (strings.Contains(message, "tty=") || strings.Contains(message, "command=") || strings.Contains(message, "pwd="))
	isSshdNoise := (strings.Contains(message, "sshd[") || strings.Contains(message, "sshd-session[")) &&
		containsAny(message, "connection reset by peer", "kex_exchange_identification", "read error from remote host", "disconnected from")
	isKernelDisplayNoise := strings.Contains(message, "kernel:") && containsAny(message, "vblank wait timed out", "[crtc:", "[drm]")

	if isSudoCmd {
		severity = "normal"
		category = "admin_command"
	} else if isSshdNoise {
		severity = "normal"
		category = "ssh_disconnect"
	} else if isKernelDisplayNoise {
		severity = "normal"
		category = "kernel_display"
	} else if strings.Contains(message, "agent_spool_loss_marker") {
		severity = "problem"
		category = "agent_data_loss"
	} else if containsAny(message, "read-only file system", "remounting filesystem read-only", "remount-ro", "aborting journal") {
		severity = "critical"
		category = "disk_readonly"
	} else if containsAny(message, "i/o error", "buffer i/o error", "blk_update_request", "ext4-fs error", "xfs error", "end_request: i/o error") {
		severity = "critical"
		category = "disk_io_error"
	} else if containsAny(message, "out of memory", "oom", "disk full", "no space left") {
		severity = "critical"
		if containsAny(message, "disk full", "no space left") {
			category = "disk_full"
		} else {
			category = "out_of_memory"
		}
	} else if containsAny(message, "blocked for more than", "hung_task_timeout_secs", "page_cleaner", "long semaphore wait") {
		severity = "problem"
		category = "disk_slow_io"
	} else if containsAny(message, "upstream timed out", "timeout", "timed out") {
		severity = "problem"
		if strings.Contains(message, "upstream") {
			category = "upstream_timeout"
		} else {
			category = "timeout"
		}
	} else if containsAny(message, "connection refused", "cannot connect", "connection reset") {
		severity = "problem"
		category = "connection_refused"
	} else if strings.Contains(message, "too many connections") {
		severity = "problem"
		category = "db_too_many_connections"
	} else if containsAny(message, "permission denied", "access denied") {
		severity = "problem"
		category = "permission_denied"
	} else if ev.StatusCode != nil && *ev.StatusCode >= 500 {
		severity = "problem"
		category = "http_5xx"
	} else if ev.StatusCode != nil && *ev.StatusCode >= 400 {
		severity = "warning"
		category = "http_4xx"
	} else if containsAny(message, "warning", "retry", "slow query") {
		severity = "warning"
		category = "warning"
	}

	explicit := strings.ToLower(ev.Severity)
	if (explicit == "warning" || explicit == "problem" || explicit == "critical") && severity == "normal" {
		severity = explicit
		if category == "normal" {
			category = explicit
		}
	}

	signalType, enrichedCategory, classification := EnrichClassification(
		ev, severity, category, &prof,
	)

	fingerprint := ev.Fingerprint
	if fingerprint == "" {
		fingerprint = "fp_" + service + "_" + enrichedCategory
	}

	var parsedFields *parser.ParsedFields
	if parsed.StatusCode != nil || parsed.RequestMethod != "" || parsed.RequestPath != "" || parsed.LatencyMS != nil || parsed.DatabaseErrorCode != "" {
		p := parsed
		parsedFields = &p
	}

	return Result{
		SignalType:     signalType,
		Severity:       severity,
		Category:       enrichedCategory,
		Classification: classification,
		SourceProfile:  prof,
		ParsedFields:   parsedFields,
		Fingerprint:    fingerprint,
	}
}

func EnrichClassification(ev Event, severity, category string, prof *profile.SourceProfile) (string, string, Classification) {
	service := strings.ToLower(strings.ReplaceAll(ev.Service, "-", "_"))
	logType := strings.ToLower(strings.ReplaceAll(ev.LogType, "-", "_"))
	filePath := strings.ToLower(strings.ReplaceAll(ev.FilePath, "\\", "/"))
	statusCode := ev.StatusCode

	activeProfile := prof
	if activeProfile == nil {
		p := profile.ProfileSource(profile.EventSource{
			Service:  ev.Service,
			LogType:  ev.LogType,
			FilePath: ev.FilePath,
		})
		activeProfile = &p
	}

	signalType := activeProfile.ServiceClass
	if activeProfile.TrafficCandidate && statusCode != nil {
		signalType = "traffic"
	}

	basis := []string{}
	if service != "" {
		basis = append(basis, "service_name")
	}
	if logType != "" || filePath != "" {
		basis = append(basis, "source_path")
	}
	if category != "normal" {
		basis = append(basis, "message_keyword")
	}
	if statusCode != nil {
		basis = append(basis, "status_code")
	}

	var ruleID string
	var confidence float64

	switch {
	case severity == "normal" && signalType == "traffic":
		category = "traffic_request"
		if statusCode != nil {
			ruleID = "traffic.http_success.v1"
		} else {
			ruleID = "traffic.access.v1"
		}
		confidence = 0.98
	case category == "db_too_many_connections":
		ruleID = "db.connection_limit.v1"
		confidence = 0.98
	case severity == "critical" && (category == "out_of_memory" || category == "disk_full" || category == "disk_readonly" || category == "disk_io_error"):
		ruleID = "system.resource_critical.v1"
		confidence = 0.99
	case category == "disk_slow_io":
		ruleID = "system.disk_slow_io.v1"
		confidence = 0.92
	case category == "upstream_timeout":
		ruleID = "proxy.upstream_timeout.v1"
		confidence = 0.96
	case category == "http_5xx":
		if signalType == "traffic" {
			ruleID = "traffic.http_error.v1"
		} else {
			ruleID = "application.http_error.v1"
		}
		confidence = 0.94
	case severity == "warning":
		ruleID = "signal.warning.v1"
		confidence = 0.82
	case severity == "problem" || severity == "critical":
		ruleID = "signal.problem.v1"
		confidence = 0.78
	case signalType == "unknown":
		ruleID = "source.unknown_normal.v1"
		confidence = 0.5
		basis = []string{"fallback"}
	default:
		ruleID = "signal.normal.v1"
		confidence = 0.75
	}

	return signalType, category, Classification{
		RuleID:     ruleID,
		Confidence: confidence,
		Basis:      basis,
	}
}

func containsAny(s string, needles ...string) bool {
	for _, n := range needles {
		if strings.Contains(s, n) {
			return true
		}
	}
	return false
}
