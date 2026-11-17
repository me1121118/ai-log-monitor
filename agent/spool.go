package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"time"
)

func appendSpoolEvent(stateDir string, event Event, maxBytes int64) error {
	if err := os.MkdirAll(stateDir, 0755); err != nil {
		return err
	}
	f, err := os.OpenFile(spoolPath(stateDir), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	encoded, err := json.Marshal(event)
	if err != nil {
		_ = f.Close()
		return err
	}
	if _, err := f.Write(append(encoded, '\n')); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return compactSpoolIfNeeded(stateDir, event, maxBytes)
}

func loadSpoolEvents(stateDir string) ([]Event, error) {
	data, err := os.ReadFile(spoolPath(stateDir))
	if err != nil {
		if os.IsNotExist(err) {
			return []Event{}, nil
		}
		return nil, err
	}
	lines := bytes.Split(data, []byte{'\n'})
	events := make([]Event, 0, len(lines))
	for _, line := range lines {
		line = bytes.TrimSpace(line)
		if len(line) == 0 {
			continue
		}
		var event Event
		if err := json.Unmarshal(line, &event); err != nil {
			return nil, err
		}
		events = append(events, event)
	}
	return events, nil
}

func replaceSpoolEvents(stateDir string, events []Event) error {
	if err := os.MkdirAll(stateDir, 0755); err != nil {
		return err
	}
	if len(events) == 0 {
		if err := os.Remove(spoolPath(stateDir)); err != nil && !os.IsNotExist(err) {
			return err
		}
		return nil
	}
	var buf bytes.Buffer
	for _, event := range events {
		encoded, err := json.Marshal(event)
		if err != nil {
			return err
		}
		buf.Write(encoded)
		buf.WriteByte('\n')
	}
	return os.WriteFile(spoolPath(stateDir), buf.Bytes(), 0600)
}

func flushSpoolEvents(stateDir string, sender func(Event) error) (int, error) {
	events, err := loadSpoolEvents(stateDir)
	if err != nil {
		return 0, err
	}
	for index, event := range events {
		if err := sender(event); err != nil {
			replaceErr := replaceSpoolEvents(stateDir, events[index:])
			if replaceErr != nil {
				return index, replaceErr
			}
			return index, err
		}
	}
	if err := replaceSpoolEvents(stateDir, nil); err != nil {
		return len(events), err
	}
	return len(events), nil
}

func compactSpoolIfNeeded(stateDir string, newest Event, maxBytes int64) error {
	if maxBytes <= 0 {
		return nil
	}
	info, err := os.Stat(spoolPath(stateDir))
	if err != nil {
		return err
	}
	if info.Size() <= maxBytes {
		return nil
	}
	events, err := loadSpoolEvents(stateDir)
	if err != nil {
		return err
	}
	if len(events) == 0 {
		return nil
	}
	dropped := len(events) - 1
	if dropped < 1 {
		dropped = 1
	}
	marker := lossMarkerFromEvent(newest, dropped, "spool_max_bytes")
	kept := []Event{marker, newest}
	for len(kept) > 1 && int64(encodedSpoolSize(kept)) > maxBytes {
		kept = kept[:1]
	}
	return replaceSpoolEvents(stateDir, kept)
}

func encodedSpoolSize(events []Event) int {
	total := 0
	for _, event := range events {
		encoded, _ := json.Marshal(event)
		total += len(encoded) + 1
	}
	return total
}

func lossMarkerFromEvent(event Event, dropped int, reason string) Event {
	timestamp := time.Now().UTC().Format(time.RFC3339Nano)
	message := fmt.Sprintf("agent_spool_loss_marker dropped=%d reason=%s", dropped, reason)
	return Event{
		WebsiteID:        event.WebsiteID,
		AgentID:          event.AgentID,
		AgentRole:        event.AgentRole,
		LogType:          "agent_spool",
		Service:          "agent",
		FilePath:         spoolPath(""),
		Timestamp:        timestamp,
		Message:          message,
		SourceID:         sourceID(event.AgentID, "agent_spool"),
		SourceConfidence: 1,
		EventUID:         eventUID(event.AgentID, "agent_spool", timestamp, message),
		Metadata: map[string]interface{}{
			"dropped_count": dropped,
			"reason":        reason,
		},
	}
}

// --------------------- SCANNER & STATE ---------------------

var newLogRecordPatterns = []*regexp.Regexp{
	regexp.MustCompile(`^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}`),
	regexp.MustCompile(`^\[\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}`),
	regexp.MustCompile(`^\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}`),
	regexp.MustCompile(`^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}`),
	regexp.MustCompile(`^\[(ERROR|WARN|WARNING|INFO|DEBUG|TRACE|FATAL|CRITICAL)\]`),
	regexp.MustCompile(`^(ERROR|WARN|WARNING|INFO|DEBUG|TRACE|FATAL|CRITICAL)\b`),
}

var exceptionSummaryPattern = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_.]*(Error|Exception|Warning|Fault|Panic):`)
