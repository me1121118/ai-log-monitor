package main

import (
	"os"
	"strings"

	"gopkg.in/yaml.v3"
)

func loadConfig(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	// Environment variable substitution (equivalent to os.ExpandEnv)
	substituted := os.ExpandEnv(string(data))

	var cfg Config
	// Set defaults
	cfg.Logs.AutoDiscover = true
	cfg.Logs.DiscoveryRoots = append([]string(nil), defaultDiscoveryRoots...)
	cfg.Logs.DiscoveryMaxFiles = defaultDiscoveryMaxFiles
	cfg.Filter.SendOnlyMatched = true
	cfg.Filter.IncludeTraffic = true
	cfg.Runtime.StateDir = "/state"
	cfg.Runtime.ScanIntervalSeconds = 3
	cfg.Runtime.HeartbeatIntervalSeconds = 30
	cfg.Runtime.SpoolMaxBytes = 10 * 1024 * 1024

	err = yaml.Unmarshal([]byte(substituted), &cfg)
	if err != nil {
		return nil, err
	}

	cfg.Server.URL = strings.TrimSuffix(cfg.Server.URL, "/")
	if cfg.Agent.Name == "" {
		hostname, _ := os.Hostname()
		cfg.Agent.Name = hostname
	}
	if cfg.Agent.Role == "" {
		cfg.Agent.Role = "unknown"
	}
	if cfg.Runtime.ScanIntervalSeconds <= 0 {
		cfg.Runtime.ScanIntervalSeconds = 3
	}
	if cfg.Runtime.HeartbeatIntervalSeconds <= 0 {
		cfg.Runtime.HeartbeatIntervalSeconds = 30
	}
	if cfg.Logs.DiscoveryMaxFiles <= 0 {
		cfg.Logs.DiscoveryMaxFiles = defaultDiscoveryMaxFiles
	}
	if len(cfg.Logs.DiscoveryRoots) == 0 {
		cfg.Logs.DiscoveryRoots = append([]string(nil), defaultDiscoveryRoots...)
	}

	// Normalize keywords to lowercase
	for i, kw := range cfg.Filter.Keywords {
		cfg.Filter.Keywords[i] = strings.ToLower(kw)
	}

	return &cfg, nil
}

// --------------------- LOG DISCOVERY ---------------------

var defaultLogCandidates = []struct {
	name    string
	path    string
	logType string
}{
	{"syslog", "/host/var/log/syslog", "system"},
	{"auth_log", "/host/var/log/auth.log", "auth"},
	{"kernel_log", "/host/var/log/kern.log", "kernel"},
	{"messages", "/host/var/log/messages", "system"},
	{"nginx_error", "/host/var/log/nginx/error.log", "nginx"},
	{"nginx_access", "/host/var/log/nginx/access.log", "nginx"},
	{"apache_error", "/host/var/log/apache2/error.log", "apache"},
	{"apache_access", "/host/var/log/apache2/access.log", "apache"},
	{"httpd_error", "/host/var/log/httpd/error_log", "apache"},
	{"httpd_access", "/host/var/log/httpd/access_log", "apache"},
	{"mysql_error", "/host/var/log/mysql/error.log", "mysql"},
	{"mariadb_error", "/host/var/log/mysql/mariadb.log", "mariadb"},
	{"mariadb_error", "/host/var/log/mysql/mariadb.err", "mariadb"},
	{"mariadb_error", "/host/var/log/mysql/error.log", "mariadb"},
	{"mariadb", "/host/var/log/mariadb/mariadb.log", "mariadb"},
	{"mariadb_error", "/host/var/log/mariadb/error.log", "mariadb"},
	{"mariadb_error", "/host/var/log/mariadb/mariadb.err", "mariadb"},
	{"postgresql", "/host/var/log/postgresql/*.log", "postgresql"},
	{"redis", "/host/var/log/redis/redis-server.log", "redis"},
	{"haproxy", "/host/var/log/haproxy.log", "haproxy"},
	{"syslog", "/var/log/syslog", "system"},
	{"auth_log", "/var/log/auth.log", "auth"},
	{"kernel_log", "/var/log/kern.log", "kernel"},
	{"messages", "/var/log/messages", "system"},
	{"nginx_error", "/var/log/nginx/error.log", "nginx"},
	{"nginx_access", "/var/log/nginx/access.log", "nginx"},
	{"apache_error", "/var/log/apache2/error.log", "apache"},
	{"apache_access", "/var/log/apache2/access.log", "apache"},
	{"httpd_error", "/var/log/httpd/error_log", "apache"},
	{"httpd_access", "/var/log/httpd/access_log", "apache"},
	{"mysql_error", "/var/log/mysql/error.log", "mysql"},
	{"mariadb_error", "/var/log/mysql/mariadb.log", "mariadb"},
	{"mariadb_error", "/var/log/mysql/mariadb.err", "mariadb"},
	{"mariadb", "/var/log/mariadb/mariadb.log", "mariadb"},
	{"mariadb_error", "/var/log/mariadb/error.log", "mariadb"},
	{"mariadb_error", "/var/log/mariadb/mariadb.err", "mariadb"},
	{"postgresql", "/var/log/postgresql/*.log", "postgresql"},
	{"redis", "/var/log/redis/redis-server.log", "redis"},
	{"haproxy", "/var/log/haproxy.log", "haproxy"},
}

var defaultDiscoveryRoots = []string{
	"/host/var/log",
	"/var/log",
	"/host/etc",
	"/host/opt",
	"/opt",
	"/host/srv",
	"/srv",
}

var defaultTopologyRoots = []string{
	"/host/etc/nginx",
	"/host/etc/apache2",
	"/host/etc/httpd",
	"/host/etc/mysql",
	"/host/etc/haproxy",
	"/host/etc/keepalived",
	"/host/opt",
	"/host/srv",
	"/etc/nginx",
	"/etc/apache2",
	"/etc/httpd",
	"/etc/mysql",
	"/etc/haproxy",
	"/etc/keepalived",
	"/opt",
	"/srv",
}

const defaultDiscoveryMaxFiles = 200
