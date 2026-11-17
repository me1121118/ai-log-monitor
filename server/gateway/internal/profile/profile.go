package profile

import "strings"

type EventSource struct {
	Service  string
	LogType  string
	FilePath string
}

type SourceProfile struct {
	ServiceClass     string
	SourceKind       string
	TrafficCandidate bool
}

func ProfileSource(src EventSource) SourceProfile {
	service := strings.ToLower(strings.ReplaceAll(src.Service, "-", "_"))
	logType := strings.ToLower(strings.ReplaceAll(src.LogType, "-", "_"))
	filePath := strings.ToLower(strings.ReplaceAll(src.FilePath, "\\", "/"))
	source := strings.Join([]string{service, logType, filePath}, " ")

	serviceClass := serviceClass(source)
	sourceKind := sourceKind(source, serviceClass)
	trafficCandidate := sourceKind == "access" || (strings.Contains(source, "haproxy") && sourceKind == "journal")

	return SourceProfile{
		ServiceClass:     serviceClass,
		SourceKind:       sourceKind,
		TrafficCandidate: trafficCandidate,
	}
}

func serviceClass(source string) string {
	if containsAny(source, "mysql", "mariadb", "postgres", "postgresql", "redis", "database") {
		return "database"
	}
	if containsAny(source, "haproxy", "nginx", "apache", "httpd", "proxy") {
		return "proxy"
	}
	if containsAny(source, "auth", "audit", "security", "login") {
		return "security"
	}
	if containsAny(source, "kernel", "syslog", "journalctl", "system", "dmesg") {
		return "system"
	}
	if containsAny(source, "app", "application", "django", "node", "gunicorn", "uvicorn") {
		return "application"
	}
	return "unknown"
}

func sourceKind(source string, serviceClass string) string {
	if strings.Contains(source, "access") {
		return "access"
	}
	if strings.Contains(source, "error") {
		return "error"
	}
	if strings.Contains(source, "journal") {
		return "journal"
	}
	if serviceClass == "system" {
		return "system"
	}
	if strings.Contains(source, "audit") || strings.Contains(source, "auth") {
		return "audit"
	}
	return "generic"
}

func containsAny(s string, needles ...string) bool {
	for _, n := range needles {
		if strings.Contains(s, n) {
			return true
		}
	}
	return false
}
