package main

import (
	"bytes"
	"crypto/sha1"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

func discoverLogPaths(configured []LogPath) []LogPath {
	return discoverLogPathsWithRoots(configured, defaultDiscoveryRoots, defaultDiscoveryMaxFiles)
}

func discoverLogPathsWithRoots(configured []LogPath, roots []string, maxFiles int) []LogPath {
	merged := append([]LogPath(nil), configured...)
	seenPaths := make(map[string]bool)
	seenNames := make(map[string]bool)

	for _, item := range merged {
		seenPaths[item.Path] = true
		seenNames[item.Name] = true
	}

	for _, item := range discoverInstalledServiceSources(roots) {
		if seenPaths[item.Path] || !isReadableFile(item.Path) {
			continue
		}
		item.Name = uniqueName(item.Name, item.Path, seenNames)
		merged = append(merged, item)
		seenPaths[item.Path] = true
		seenNames[item.Name] = true
	}

	for _, cand := range defaultLogCandidates {
		expanded, err := filepath.Glob(cand.path)
		if err != nil {
			continue
		}
		for _, path := range expanded {
			if seenPaths[path] || !isReadableFile(path) {
				continue
			}
			name := uniqueName(cand.name, path, seenNames)
			merged = append(merged, LogPath{Name: name, Path: path, Type: cand.logType, Discovered: true})
			seenPaths[path] = true
			seenNames[name] = true
		}
	}

	if maxFiles <= 0 {
		maxFiles = defaultDiscoveryMaxFiles
	}
	for _, path := range discoverRecursiveLogFiles(roots, seenPaths, maxFiles) {
		classification, confidence := classifyLogPath(path, "")
		name := uniqueName("auto_"+safeSuffix(filepath.Base(path)), path, seenNames)
		merged = append(merged, LogPath{
			Name:           name,
			Path:           path,
			Type:           classification,
			Discovered:     true,
			Classification: classification,
			Confidence:     confidence,
		})
		seenPaths[path] = true
		seenNames[name] = true
		if len(merged)-len(configured) >= maxFiles {
			break
		}
	}

	return merged
}

func discoverInstalledServiceSources(roots []string) []LogPath {
	var sources []LogPath
	for _, root := range roots {
		cleaned := filepath.Clean(strings.TrimSpace(root))
		if filepath.Base(cleaned) != "etc" {
			continue
		}
		if info, err := os.Stat(filepath.Join(cleaned, "mysql")); err != nil || !info.IsDir() {
			continue
		}
		syslog := filepath.Join(filepath.Dir(cleaned), "var", "log", "syslog")
		if isReadableFile(syslog) {
			sources = append(sources, LogPath{
				Name:           "mariadb_journal",
				Path:           syslog,
				Type:           "mariadb",
				Includes:       []string{"mariadbd", "mysqld"},
				Discovered:     true,
				Classification: "known_service",
				Confidence:     0.95,
			})
		}
	}
	return sources
}

func discoverRecursiveLogFiles(roots []string, seenPaths map[string]bool, maxFiles int) []string {
	discovered := make([]string, 0)
	if maxFiles <= 0 {
		return discovered
	}
	for _, root := range roots {
		if len(discovered) >= maxFiles {
			break
		}
		root = strings.TrimSpace(root)
		if root == "" {
			continue
		}
		// /var/log contains many package-management and installer logs. Known
		// service candidates above cover this tree without flooding the server.
		if isSystemLogRoot(root) {
			continue
		}
		info, err := os.Stat(root)
		if err != nil || !info.IsDir() {
			continue
		}
		_ = filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
			if err != nil {
				return nil
			}
			if len(discovered) >= maxFiles {
				return filepath.SkipAll
			}
			if entry.IsDir() {
				if shouldSkipDiscoveryDir(entry.Name()) && path != root {
					return filepath.SkipDir
				}
				return nil
			}
			if seenPaths[path] || !looksLikeLogFile(path) || !isReadableFile(path) {
				return nil
			}
			discovered = append(discovered, path)
			return nil
		})
	}
	return discovered
}

func isSystemLogRoot(path string) bool {
	cleaned := filepath.ToSlash(filepath.Clean(path))
	return cleaned == "/var/log" || cleaned == "/host/var/log"
}

func shouldSkipDiscoveryDir(name string) bool {
	lower := strings.ToLower(name)
	return lower == ".git" || lower == "node_modules" || lower == "vendor" || lower == "cache" || lower == "tmp"
}

func looksLikeLogFile(path string) bool {
	name := strings.ToLower(filepath.Base(path))
	if strings.HasSuffix(name, ".gz") || strings.HasSuffix(name, ".zip") ||
		strings.HasSuffix(name, ".xz") || strings.HasSuffix(name, ".bz2") {
		return false
	}
	if strings.HasSuffix(name, ".log") || strings.HasSuffix(name, ".err") || strings.HasSuffix(name, ".out") {
		return true
	}
	switch name {
	case "syslog", "messages", "auth.log", "kern.log", "error_log", "access_log":
		return true
	}
	return strings.Contains(name, "error.log") || strings.Contains(name, "slow.log")
}

func topologyDiscoveryRoots(configured []string) []string {
	roots := append([]string{}, defaultTopologyRoots...)
	seen := map[string]bool{}
	for _, root := range roots {
		seen[root] = true
	}
	for _, root := range configured {
		root = strings.TrimSpace(root)
		if root == "" || seen[root] {
			continue
		}
		roots = append(roots, root)
		seen[root] = true
	}
	return roots
}

func discoverTopologyHintsWithRoots(roots []string, maxFiles int) []TopologyHint {
	if maxFiles <= 0 {
		maxFiles = defaultDiscoveryMaxFiles
	}
	hints := make([]TopologyHint, 0)
	seenHints := map[string]bool{}
	files := discoverTopologyConfigFiles(roots, maxFiles)
	for _, path := range files {
		for _, hint := range parseTopologyHintsFromFile(path) {
			key := hint.HintType + "|" + hint.Target + "|" + hint.Source
			if seenHints[key] {
				continue
			}
			seenHints[key] = true
			hints = append(hints, hint)
		}
	}
	return hints
}

func discoverTopologyConfigFiles(roots []string, maxFiles int) []string {
	files := make([]string, 0)
	seen := map[string]bool{}
	for _, root := range roots {
		if len(files) >= maxFiles {
			break
		}
		root = strings.TrimSpace(root)
		if root == "" {
			continue
		}
		info, err := os.Stat(root)
		if err != nil {
			continue
		}
		if !info.IsDir() {
			if looksLikeTopologyConfigFile(root) && isReadableFile(root) {
				files = append(files, root)
			}
			continue
		}
		_ = filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
			if err != nil {
				return nil
			}
			if len(files) >= maxFiles {
				return filepath.SkipAll
			}
			if entry.IsDir() {
				if shouldSkipDiscoveryDir(entry.Name()) && path != root {
					return filepath.SkipDir
				}
				return nil
			}
			if seen[path] || !looksLikeTopologyConfigFile(path) || !isReadableFile(path) {
				return nil
			}
			seen[path] = true
			files = append(files, path)
			return nil
		})
	}
	return files
}

func looksLikeTopologyConfigFile(path string) bool {
	name := strings.ToLower(filepath.Base(path))
	if strings.HasSuffix(name, ".gz") || strings.HasSuffix(name, ".zip") ||
		strings.HasSuffix(name, ".xz") || strings.HasSuffix(name, ".bz2") {
		return false
	}
	if name == ".env" || strings.HasSuffix(name, ".env") {
		return true
	}
	for _, suffix := range []string{".conf", ".cnf", ".config", ".cfg", ".ini", ".yaml", ".yml", ".toml", ".properties"} {
		if strings.HasSuffix(name, suffix) {
			return true
		}
	}
	return false
}

var proxyPassPattern = regexp.MustCompile(`(?i)\bproxy_pass\s+https?://([^/;\s]+)`)
var upstreamServerPattern = regexp.MustCompile(`(?i)\bserver\s+([A-Za-z0-9_.-]+(?::\d+)?)\s*;`)
var dbHostPattern = regexp.MustCompile(`(?i)\b(?:DB_HOST|DATABASE_HOST|MYSQL_HOST|POSTGRES_HOST|PGHOST)\b\s*[:=]\s*["']?([A-Za-z0-9_.-]+(?::\d+)?)`)
var databaseURLPattern = regexp.MustCompile(`(?i)\b(?:DATABASE_URL|DB_URL)\b\s*[:=]\s*["']?[a-z][a-z0-9+.-]*://(?:[^:@/\s]+(?::[^@/\s]+)?@)?([^/\s'"]+)`)
var galeraClusterPattern = regexp.MustCompile(`(?i)wsrep_cluster_address\s*=\s*["']?gcomm://([^"'\s#]+)`)
var peerDirectivePattern = regexp.MustCompile(`(?i)\bpeer\s+([A-Za-z0-9_.-]+)`)
var httpAccessLogPattern = regexp.MustCompile(`^(\S+) \S+ \S+ \[[^\]]+\] "(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS) ([^"\s]+)[^"]*" (\d{3})`)

func parseTopologyHintsFromFile(path string) []TopologyHint {
	info, err := os.Stat(path)
	if err != nil || info.IsDir() || info.Size() > 256*1024 {
		return nil
	}
	data, err := os.ReadFile(path)
	if err != nil || bytes.IndexByte(data, 0) >= 0 {
		return nil
	}
	lines := strings.Split(string(data), "\n")
	hints := make([]TopologyHint, 0)
	for index, line := range lines {
		lineNumber := index + 1
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "#") {
			continue
		}
		if match := proxyPassPattern.FindStringSubmatch(line); len(match) == 2 {
			if target := cleanTopologyTarget(match[1]); target != "" {
				hints = append(hints, topologyHint(path, "http_upstream", target, 0.9, lineNumber, "proxy_pass"))
			}
		}
		if match := upstreamServerPattern.FindStringSubmatch(line); len(match) == 2 {
			if target := cleanTopologyTarget(match[1]); target != "" {
				hints = append(hints, topologyHint(path, "http_upstream", target, 0.86, lineNumber, "upstream_server"))
			}
		}
		if match := dbHostPattern.FindStringSubmatch(line); len(match) == 2 {
			if target := cleanTopologyTarget(match[1]); target != "" {
				hints = append(hints, topologyHint(path, "database", target, 0.82, lineNumber, "db_host"))
			}
		}
		if match := databaseURLPattern.FindStringSubmatch(line); len(match) == 2 {
			if target := cleanTopologyTarget(match[1]); target != "" {
				hints = append(hints, topologyHint(path, "database", target, 0.86, lineNumber, "database_url"))
			}
		}
		if match := galeraClusterPattern.FindStringSubmatch(line); len(match) == 2 {
			for _, rawPeer := range strings.Split(match[1], ",") {
				if target := cleanTopologyTarget(rawPeer); target != "" {
					hints = append(hints, topologyHint(path, "peer_sync", target, 0.92, lineNumber, "wsrep_cluster_address"))
				}
			}
		}
		if match := peerDirectivePattern.FindStringSubmatch(line); len(match) == 2 {
			if target := cleanTopologyTarget(match[1]); target != "" {
				hints = append(hints, topologyHint(path, "peer_sync", target, 0.88, lineNumber, "peer"))
			}
		}
	}
	return hints
}

func topologyHint(path string, hintType string, target string, confidence float64, lineNumber int, directive string) TopologyHint {
	return TopologyHint{
		Source:     path,
		HintType:   hintType,
		Target:     target,
		Confidence: confidence,
		Metadata: map[string]interface{}{
			"line":      lineNumber,
			"directive": directive,
		},
	}
}

func cleanTopologyTarget(target string) string {
	target = strings.TrimSpace(target)
	target = strings.Trim(target, `"'`)
	target = strings.TrimSuffix(target, ";")
	target = strings.TrimSuffix(target, "/")
	if strings.Contains(target, "$") || target == "" {
		return ""
	}
	return target
}

func isReadableFile(path string) bool {
	info, err := os.Stat(path)
	if err != nil || info.IsDir() {
		return false
	}
	f, err := os.Open(path)
	if err != nil {
		return false
	}
	f.Close()
	return true
}

func uniqueName(base string, path string, seen map[string]bool) string {
	if !seen[base] {
		return base
	}
	suffix := safeSuffix(filepath.Base(path))
	candidate := fmt.Sprintf("%s_%s", base, suffix)
	counter := 2
	for seen[candidate] {
		candidate = fmt.Sprintf("%s_%s_%d", base, suffix, counter)
		counter++
	}
	return candidate
}

func safeSuffix(filename string) string {
	reg, _ := regexp.Compile("[^A-Za-z0-9]+")
	suffix := reg.ReplaceAllString(strings.ToLower(filename), "_")
	return strings.Trim(suffix, "_")
}

func sourceID(agentName string, path string) string {
	basis := fmt.Sprintf("%s|%s", agentName, filepath.Clean(path))
	sum := sha1.Sum([]byte(basis))
	return fmt.Sprintf("src_%x", sum[:10])
}

func classifyLogPath(path string, explicitType string) (string, float64) {
	explicit := strings.ToLower(strings.TrimSpace(explicitType))
	if explicit == "custom_app" || explicit == "app" || explicit == "application" {
		return "custom_app", 0.85
	}
	if explicit == "system" || explicit == "auth" || explicit == "kernel" {
		return "system", 0.85
	}
	text := strings.ToLower(filepath.ToSlash(path + " " + explicitType))
	known := []string{"nginx", "apache", "httpd", "mysql", "mariadb", "postgresql", "php", "redis", "haproxy"}
	for _, item := range known {
		if strings.Contains(text, item) {
			return "known_service", 0.90
		}
	}
	if strings.Contains(text, "/opt/") || strings.Contains(text, "/srv/") || strings.Contains(text, "/logs/") {
		return "custom_app", 0.65
	}
	if strings.Contains(text, "/var/log/") {
		return "system", 0.55
	}
	return "candidate", 0.35
}

func eventUID(agentName string, path string, timestamp string, message string) string {
	basis := fmt.Sprintf("%s|%s|%s|%s", agentName, filepath.Clean(path), timestamp, message)
	sum := sha1.Sum([]byte(basis))
	return fmt.Sprintf("evtuid_%x", sum[:12])
}

func isTrafficLogPath(logPath LogPath) bool {
	name := strings.ToLower(strings.TrimSpace(logPath.Name))
	switch name {
	case "nginx_access", "apache_access", "httpd_access":
		return true
	}
	if strings.HasSuffix(name, "_access") {
		return true
	}
	base := strings.ToLower(filepath.Base(logPath.Path))
	return base == "access.log" || base == "access_log"
}

func parseHTTPAccessMetadata(message string) map[string]interface{} {
	firstLine := strings.TrimSpace(message)
	if idx := strings.IndexByte(firstLine, '\n'); idx >= 0 {
		firstLine = strings.TrimSpace(firstLine[:idx])
	}
	match := httpAccessLogPattern.FindStringSubmatch(firstLine)
	if len(match) != 5 {
		return nil
	}
	statusCode, err := strconv.Atoi(match[4])
	if err != nil {
		return nil
	}
	return map[string]interface{}{
		"client_ip":   match[1],
		"method":      match[2],
		"path":        match[3],
		"status_code": statusCode,
	}
}

func buildEvent(config Config, logPath LogPath, timestamp string, record LogRecord) Event {
	_, confidence := classifyLogPath(logPath.Path, logPath.Type)
	agentName := config.Agent.Name
	if record.LineCount <= 0 && record.Message != "" {
		record.LineCount = strings.Count(record.Message, "\n") + 1
	}
	if record.LineCount > 1 {
		record.Multiline = true
	}
	metadata := parseHTTPAccessMetadata(record.Message)
	if config.Agent.ClusterID != "" {
		if metadata == nil {
			metadata = make(map[string]interface{})
		}
		metadata["cluster_id"] = config.Agent.ClusterID
	}
	return Event{
		WebsiteID:        config.Agent.WebsiteID,
		AgentID:          agentName,
		AgentRole:        config.Agent.Role,
		LogType:          logPath.Name,
		Service:          logPath.Type,
		FilePath:         logPath.Path,
		Timestamp:        timestamp,
		Message:          record.Message,
		SourceID:         sourceID(agentName, logPath.Path),
		SourceConfidence: confidence,
		EventUID:         eventUID(agentName, logPath.Path, timestamp, record.Message),
		Multiline:        record.Multiline,
		LineCount:        record.LineCount,
		Metadata:         metadata,
	}
}
