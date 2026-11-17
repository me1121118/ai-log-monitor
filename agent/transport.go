package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func reportLogSources(serverURL string, agentToken string, config Config) error {
	sources := make([]map[string]interface{}, 0, len(config.Logs.Paths))
	now := time.Now().UTC().Format(time.RFC3339Nano)
	for _, logPath := range config.Logs.Paths {
		classification, confidence := classifyLogPath(logPath.Path, logPath.Type)
		sourceType := logPath.Type
		if sourceType == "" {
			sourceType = classification
		}
		status := logSourceStatus(logPath.Path)
		sources = append(sources, map[string]interface{}{
			"source_id":      sourceID(config.Agent.Name, logPath.Path),
			"name":           logPath.Name,
			"path":           logPath.Path,
			"source_type":    sourceType,
			"service":        sourceType,
			"classification": classification,
			"confidence":     confidence,
			"status":         status,
			"last_seen_at":   now,
			"metadata": map[string]interface{}{
				"discovered": logPath.Discovered,
			},
		})
	}
	payload := map[string]interface{}{
		"website_id": config.Agent.WebsiteID,
		"agent_id":   config.Agent.Name,
		"sources":    sources,
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequest("POST", strings.TrimSuffix(serverURL, "/")+"/api/log-sources", bytes.NewBuffer(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Agent-Token", agentToken)
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		respBody, _ := io.ReadAll(resp.Body)
		return httpStatusError{StatusCode: resp.StatusCode, Body: string(respBody)}
	}
	return nil
}

func reportTopologyHints(serverURL string, agentToken string, config Config, hints []TopologyHint) error {
	if len(hints) == 0 {
		return nil
	}
	now := time.Now().UTC().Format(time.RFC3339Nano)
	items := make([]TopologyHint, 0, len(hints))
	for _, hint := range hints {
		if hint.LastSeenAt == "" {
			hint.LastSeenAt = now
		}
		items = append(items, hint)
	}
	payload := map[string]interface{}{
		"website_id": config.Agent.WebsiteID,
		"agent_id":   config.Agent.Name,
		"hints":      items,
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequest("POST", strings.TrimSuffix(serverURL, "/")+"/api/topology-hints", bytes.NewBuffer(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Agent-Token", agentToken)
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		respBody, _ := io.ReadAll(resp.Body)
		return httpStatusError{StatusCode: resp.StatusCode, Body: string(respBody)}
	}
	return nil
}

func sendHeartbeat(serverURL string, agentToken string, config Config) error {
	vitals := collectHostVitals()
	payload := map[string]interface{}{
		"agent_id":     config.Agent.Name,
		"agent_role":   config.Agent.Role,
		"website_id":   config.Agent.WebsiteID,
		"cluster_id":   config.Agent.ClusterID,
		"status":       "active",
		"observed_at":  time.Now().UTC().Format(time.RFC3339Nano),
		"cpu_percent":  vitals.CPUPercent,
		"ram_percent":  vitals.RAMPercent,
		"disk_percent": vitals.DiskPercent,
		"metrics": map[string]interface{}{
			"log_sources":  len(config.Logs.Paths),
			"cpu_percent":  vitals.CPUPercent,
			"ram_percent":  vitals.RAMPercent,
			"disk_percent": vitals.DiskPercent,
		},
	}
	if hostname := hostHostname(); hostname != "" {
		payload["hostname"] = hostname
	}
	if machineID := hostMachineID(); machineID != "" {
		payload["machine_id"] = machineID
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequest("POST", strings.TrimSuffix(serverURL, "/")+"/api/agents/heartbeat", bytes.NewBuffer(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Agent-Token", agentToken)
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		respBody, _ := io.ReadAll(resp.Body)
		return httpStatusError{StatusCode: resp.StatusCode, Body: string(respBody)}
	}
	return nil
}

type httpStatusError struct {
	StatusCode int
	Body       string
}

func (err httpStatusError) Error() string {
	return fmt.Sprintf("server returned status %d: %s", err.StatusCode, err.Body)
}

func isUnauthorizedStatus(err error) bool {
	var statusErr httpStatusError
	return errors.As(err, &statusErr) && statusErr.StatusCode == http.StatusUnauthorized
}

func logSourceStatus(path string) string {
	info, err := os.Stat(path)
	if err != nil {
		if os.IsNotExist(err) {
			return "missing"
		}
		return "unreadable"
	}
	if info.IsDir() {
		return "directory"
	}
	if isReadableFile(path) {
		return "readable"
	}
	return "unreadable"
}

func spoolPath(stateDir string) string {
	return filepath.Join(stateDir, "spool.jsonl")
}

func agentTokenPath(stateDir string) string {
	return filepath.Join(stateDir, "agent_token")
}

func loadAgentToken(stateDir string) (string, error) {
	data, err := os.ReadFile(agentTokenPath(stateDir))
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(data)), nil
}

func saveAgentToken(stateDir string, token string) error {
	if err := os.MkdirAll(stateDir, 0755); err != nil {
		return err
	}
	return os.WriteFile(agentTokenPath(stateDir), []byte(strings.TrimSpace(token)+"\n"), 0600)
}

func resolveAgentToken(config *Config, registrar func(*Config) (string, error)) (string, error) {
	if token, err := loadAgentToken(config.Runtime.StateDir); err == nil && token != "" {
		return token, nil
	}
	return refreshAgentToken(config, registrar)
}

func refreshAgentToken(config *Config, registrar func(*Config) (string, error)) (string, error) {
	token, err := registrar(config)
	if err != nil {
		return "", err
	}
	if err := saveAgentToken(config.Runtime.StateDir, token); err != nil {
		return "", err
	}
	return token, nil
}

func registerAgent(config *Config) (string, error) {
	vitals := collectHostVitals()
	payload := map[string]interface{}{
		"agent_id":     config.Agent.Name,
		"agent_role":   config.Agent.Role,
		"cluster_id":   config.Agent.ClusterID,
		"cpu_percent":  vitals.CPUPercent,
		"ram_percent":  vitals.RAMPercent,
		"disk_percent": vitals.DiskPercent,
	}
	if hostname := hostHostname(); hostname != "" {
		payload["hostname"] = hostname
	}
	if machineID := hostMachineID(); machineID != "" {
		payload["machine_id"] = machineID
	}
	if config.Agent.WebsiteID != "" {
		payload["website_id"] = config.Agent.WebsiteID
	}

	body, _ := json.Marshal(payload)
	url := config.Server.URL + "/api/agents/register"

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Enroll-Token", config.Enrollment.Token)

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		respBody, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("server returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var result map[string]interface{}
	err = json.NewDecoder(resp.Body).Decode(&result)
	if err != nil {
		return "", err
	}

	token, ok := result["agent_token"].(string)
	if !ok {
		return "", fmt.Errorf("missing agent_token in register response")
	}

	return token, nil
}

func hostHostname() string {
	if data, err := os.ReadFile("/host/etc/hostname"); err == nil {
		if hostname := strings.TrimSpace(string(data)); hostname != "" {
			return hostname
		}
	}
	hostname, _ := os.Hostname()
	return strings.TrimSpace(hostname)
}

func hostMachineID() string {
	if data, err := os.ReadFile("/host/sys/class/dmi/id/product_uuid"); err == nil {
		if productUUID := strings.ToLower(strings.TrimSpace(string(data))); productUUID != "" {
			fingerprint := sha256.Sum256([]byte(productUUID + "|" + hostHostname()))
			return fmt.Sprintf("dmi_%x", fingerprint[:16])
		}
	}
	for _, path := range []string{"/host/etc/machine-id", "/etc/machine-id"} {
		if data, err := os.ReadFile(path); err == nil {
			if machineID := strings.TrimSpace(string(data)); machineID != "" {
				fingerprint := sha256.Sum256([]byte(machineID + "|" + hostHostname()))
				return fmt.Sprintf("host_%x", fingerprint[:16])
			}
		}
	}
	return ""
}

func ingestEvent(serverURL string, agentToken string, event Event) error {
	body, _ := json.Marshal(event)
	url := serverURL + "/api/ingest"

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Agent-Token", agentToken)

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		respBody, _ := io.ReadAll(resp.Body)
		return httpStatusError{StatusCode: resp.StatusCode, Body: string(respBody)}
	}

	return nil
}

func isHighPriorityEvent(event Event) bool {
	if event.Metadata != nil {
		if code, ok := event.Metadata["status_code"].(int); ok {
			return code >= 500
		}
		if codeFloat, ok := event.Metadata["status_code"].(float64); ok {
			return int(codeFloat) >= 500
		}
	}
	lower := strings.ToLower(event.Message)
	for _, term := range builtInProblemTerms {
		if containsProblemTerm(lower, term) {
			return true
		}
	}
	return false
}

func prioritizeEvents(events []Event) []Event {
	if len(events) <= 1 {
		return events
	}
	high := make([]Event, 0, len(events))
	normal := make([]Event, 0, len(events))
	for _, ev := range events {
		if isHighPriorityEvent(ev) {
			high = append(high, ev)
		} else {
			normal = append(normal, ev)
		}
	}
	return append(high, normal...)
}
