package main

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func groupLogLines(lines []string, maxLines int) []LogRecord {
	records := make([]LogRecord, 0, len(lines))
	var current []string

	flush := func() {
		if len(current) == 0 {
			return
		}
		message := strings.Join(current, "\n")
		records = append(records, LogRecord{
			Message:   message,
			Multiline: len(current) > 1,
			LineCount: len(current),
		})
		current = nil
	}

	for _, raw := range lines {
		line := strings.TrimRight(raw, "\r")
		if strings.TrimSpace(line) == "" {
			continue
		}
		if len(current) == 0 {
			current = append(current, line)
			continue
		}
		if shouldContinueLogRecord(current, line) && (maxLines <= 0 || len(current) < maxLines) {
			current = append(current, line)
			continue
		}
		flush()
		current = append(current, line)
	}
	flush()
	return records
}

func shouldContinueLogRecord(current []string, line string) bool {
	if len(current) == 0 {
		return false
	}
	if startsNewLogRecord(line) {
		return false
	}
	trimmed := strings.TrimSpace(line)
	if trimmed == "" {
		return false
	}
	if strings.HasPrefix(line, " ") || strings.HasPrefix(line, "\t") {
		return true
	}
	lower := strings.ToLower(trimmed)
	if strings.HasPrefix(lower, "at ") || strings.HasPrefix(lower, "caused by:") || strings.HasPrefix(lower, "...") {
		return true
	}
	if recordLooksLikeStackTrace(current) && exceptionSummaryPattern.MatchString(trimmed) {
		return true
	}
	if recordLooksLikeStackTrace(current) && (strings.HasPrefix(lower, "panic:") || strings.HasPrefix(lower, "fatal error:")) {
		return true
	}
	return false
}

func startsNewLogRecord(line string) bool {
	trimmed := strings.TrimSpace(line)
	if trimmed == "" {
		return false
	}
	for _, pattern := range newLogRecordPatterns {
		if pattern.MatchString(trimmed) {
			return true
		}
	}
	return false
}

func recordLooksLikeStackTrace(lines []string) bool {
	for _, line := range lines {
		lower := strings.ToLower(strings.TrimSpace(line))
		if strings.Contains(lower, "traceback (most recent call last)") ||
			strings.HasPrefix(lower, "panic:") ||
			strings.HasPrefix(lower, "goroutine ") ||
			strings.HasPrefix(lower, "caused by:") ||
			strings.HasPrefix(lower, "at ") {
			return true
		}
	}
	return false
}

func scanOnce(config *Config) ([]Event, error) {
	state, err := loadState(config.Runtime.StateDir)
	if err != nil {
		state = make(map[string]int64)
	}

	var events []Event

	for _, logPath := range config.Logs.Paths {
		path := logPath.Path
		info, err := os.Stat(path)
		if err != nil || info.IsDir() {
			continue
		}

		savedOffset, hasSavedOffset := state[path]
		size := info.Size()
		if !hasSavedOffset && logPath.Discovered {
			state[path] = size
			continue
		}
		var offset int64 = 0
		if size >= savedOffset {
			offset = savedOffset
		}

		f, err := os.Open(path)
		if err != nil {
			continue
		}

		_, err = f.Seek(offset, 0)
		if err != nil {
			f.Close()
			continue
		}

		// Read complete lines first, then group multiline records before filtering.
		reader := io.Reader(f)
		buf := make([]byte, 32*1024)
		var leftover []byte
		completeLines := make([]string, 0)

		for {
			n, err := reader.Read(buf)
			if n > 0 {
				chunk := append(leftover, buf[:n]...)
				lines := bytes.Split(chunk, []byte{'\n'})
				// If chunk does not end in newline, the last element is leftover
				if !bytes.HasSuffix(chunk, []byte{'\n'}) {
					leftover = lines[len(lines)-1]
					lines = lines[:len(lines)-1]
				} else {
					leftover = nil
					lines = lines[:len(lines)-1]
				}

				for _, lineBytes := range lines {
					line := strings.TrimRight(string(lineBytes), "\r")
					if line == "" {
						continue
					}
					completeLines = append(completeLines, line)
				}
			}
			if err != nil {
				break
			}
		}

		for _, record := range groupLogLines(completeLines, 100) {
			if record.Message == "" {
				continue
			}
			if !matchesSourceIncludes(record.Message, logPath.Includes) {
				continue
			}
			if shouldSendForLogPath(record.Message, logPath, config) {
				events = append(events, buildEvent(*config, logPath, time.Now().UTC().Format(time.RFC3339Nano), record))
			}
		}

		currentOffset, _ := f.Seek(0, 1)
		if len(leftover) > 0 {
			leftoverSize := int64(len(leftover))
			if currentOffset >= leftoverSize {
				currentOffset -= leftoverSize
			} else {
				currentOffset = 0
			}
		}
		state[path] = currentOffset
		f.Close()
	}

	_ = saveState(config.Runtime.StateDir, state)
	return events, nil
}

func matchesSourceIncludes(message string, includes []string) bool {
	if len(includes) == 0 {
		return true
	}
	lower := strings.ToLower(message)
	for _, include := range includes {
		if include = strings.ToLower(strings.TrimSpace(include)); include != "" && strings.Contains(lower, include) {
			return true
		}
	}
	return false
}

func shouldSendForLogPath(message string, logPath LogPath, config *Config) bool {
	if !config.Filter.SendOnlyMatched {
		return true
	}
	if config.Filter.IncludeTraffic && isTrafficLogPath(logPath) {
		return true
	}
	return shouldSend(message, config)
}

func shouldSend(message string, config *Config) bool {
	if !config.Filter.SendOnlyMatched {
		return true
	}
	if config.Filter.IncludeTraffic && httpAccessLogPattern.MatchString(strings.TrimSpace(message)) {
		return true
	}
	if normalTelemetryPattern.MatchString(message) {
		return false
	}
	lowerMsg := strings.ToLower(message)
	if strings.Contains(lowerMsg, "sudo:") && (strings.Contains(lowerMsg, "tty=") || strings.Contains(lowerMsg, "command=") || strings.Contains(lowerMsg, "pwd=")) {
		return false
	}
	if (strings.Contains(lowerMsg, "sshd[") || strings.Contains(lowerMsg, "sshd-session[")) &&
		(strings.Contains(lowerMsg, "connection reset by peer") || strings.Contains(lowerMsg, "kex_exchange_identification") || strings.Contains(lowerMsg, "read error from remote host")) {
		return false
	}
	if strings.Contains(lowerMsg, "kernel:") && strings.Contains(lowerMsg, "vblank wait timed out") {
		return false
	}
	lower := zeroValueMetricCounter.ReplaceAllString(lowerMsg, "")
	searchable := zeroProblemCounterPattern.ReplaceAllString(lower, "metric_zero")
	for _, term := range config.Filter.Keywords {
		if containsProblemTerm(searchable, term) {
			return true
		}
	}
	for _, term := range builtInProblemTerms {
		if containsProblemTerm(searchable, term) {
			return true
		}
	}
	return false
}

func containsProblemTerm(message string, term string) bool {
	term = strings.ToLower(strings.TrimSpace(term))
	if term == "502" || term == "503" || term == "504" {
		return httpStatusCodePattern.MatchString(message)
	}
	return strings.Contains(message, term)
}

func loadState(stateDir string) (map[string]int64, error) {
	path := filepath.Join(stateDir, "offsets.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return make(map[string]int64), err
	}
	var state map[string]int64
	err = json.Unmarshal(data, &state)
	return state, err
}

func saveState(stateDir string, state map[string]int64) error {
	err := os.MkdirAll(stateDir, 0755)
	if err != nil {
		return err
	}
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(stateDir, "offsets.json"), data, 0600)
}

// --------------------- HTTP CLIENT ---------------------
