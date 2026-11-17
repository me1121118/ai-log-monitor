package classifier

import (
	"testing"

	"ai-log-server/server/gateway/internal/profile"
)

func TestClassifyEvent(t *testing.T) {
	cases := []struct {
		name         string
		ev           Event
		wantSignal   string
		wantSeverity string
		wantCategory string
		wantRuleID   string
		wantConf     float64
		wantFpPrefix string
		wantBasis    []string
	}{
		{
			name: "nginx_200_access",
			ev: Event{
				Service:           "nginx",
				FilePath:          "/var/log/nginx/access.log",
				Message:           `10.0.0.1 - - "GET /api/orders HTTP/1.1" 200 120`,
				NormalizedMessage: `10.0.0.1 - - "GET /api/orders HTTP/1.1" 200 120`,
			},
			wantSignal:   "traffic",
			wantSeverity: "normal",
			wantCategory: "traffic_request",
			wantRuleID:   "traffic.http_success.v1",
			wantConf:     0.98,
			wantFpPrefix: "fp_nginx_traffic_request",
			wantBasis:    []string{"service_name", "source_path", "status_code"},
		},
		{
			name: "nginx_upstream_timeout",
			ev: Event{
				Service:           "nginx",
				FilePath:          "/var/log/nginx/error.log",
				NormalizedMessage: "upstream timed out while reading response from upstream",
			},
			wantSignal:   "proxy",
			wantSeverity: "problem",
			wantCategory: "upstream_timeout",
			wantRuleID:   "proxy.upstream_timeout.v1",
			wantConf:     0.96,
			wantFpPrefix: "fp_nginx_upstream_timeout",
			wantBasis:    []string{"service_name", "source_path", "message_keyword"},
		},
		{
			name: "mariadb_too_many_connections",
			ev: Event{
				Service:  "mariadb",
				FilePath: "/var/log/mysql/error.log",
				Message:  "[ERROR] Aborting due to too many connections",
			},
			wantSignal:   "database",
			wantSeverity: "problem",
			wantCategory: "db_too_many_connections",
			wantRuleID:   "db.connection_limit.v1",
			wantConf:     0.98,
			wantFpPrefix: "fp_mariadb_db_too_many_connections",
			wantBasis:    []string{"service_name", "source_path", "message_keyword"},
		},
		{
			name: "kernel_oom",
			ev: Event{
				Service:           "kernel",
				FilePath:          "/var/log/syslog",
				NormalizedMessage: "out of memory: killed process 1234",
			},
			wantSignal:   "system",
			wantSeverity: "critical",
			wantCategory: "out_of_memory",
			wantRuleID:   "system.resource_critical.v1",
			wantConf:     0.99,
			wantFpPrefix: "fp_kernel_out_of_memory",
			wantBasis:    []string{"service_name", "source_path", "message_keyword"},
		},
		{
			name: "permission_denied_auth_failure",
			ev: Event{
				Service:           "sshd",
				FilePath:          "/var/log/auth.log",
				NormalizedMessage: "permission denied (publickey,password)",
			},
			wantSignal:   "security",
			wantSeverity: "problem",
			wantCategory: "permission_denied",
			wantRuleID:   "signal.problem.v1",
			wantConf:     0.78,
			wantFpPrefix: "fp_sshd_permission_denied",
			wantBasis:    []string{"service_name", "source_path", "message_keyword"},
		},
		{
			name: "warning_retry",
			ev: Event{
				Service:           "app",
				NormalizedMessage: "retrying connection after failure",
			},
			wantSignal:   "application",
			wantSeverity: "warning",
			wantCategory: "warning",
			wantRuleID:   "signal.warning.v1",
			wantConf:     0.82,
			wantFpPrefix: "fp_app_warning",
			wantBasis:    []string{"service_name", "message_keyword"},
		},
		{
			name: "unknown_normal",
			ev: Event{
				Service:           "weird-custom",
				NormalizedMessage: "everything is fine",
			},
			wantSignal:   "unknown",
			wantSeverity: "normal",
			wantCategory: "normal",
			wantRuleID:   "source.unknown_normal.v1",
			wantConf:     0.5,
			wantFpPrefix: "fp_weird_custom_normal",
			wantBasis:    []string{"fallback"},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := ClassifyEvent(tc.ev)
			if got.SignalType != tc.wantSignal {
				t.Errorf("SignalType = %q, want %q", got.SignalType, tc.wantSignal)
			}
			if got.Severity != tc.wantSeverity {
				t.Errorf("Severity = %q, want %q", got.Severity, tc.wantSeverity)
			}
			if got.Category != tc.wantCategory {
				t.Errorf("Category = %q, want %q", got.Category, tc.wantCategory)
			}
			if got.Classification.RuleID != tc.wantRuleID {
				t.Errorf("RuleID = %q, want %q", got.Classification.RuleID, tc.wantRuleID)
			}
			if got.Classification.Confidence != tc.wantConf {
				t.Errorf("Confidence = %v, want %v", got.Classification.Confidence, tc.wantConf)
			}
			if got.Fingerprint != tc.wantFpPrefix {
				t.Errorf("Fingerprint = %q, want %q", got.Fingerprint, tc.wantFpPrefix)
			}
			if !stringSliceEqual(got.Classification.Basis, tc.wantBasis) {
				t.Errorf("Basis = %v, want %v", got.Classification.Basis, tc.wantBasis)
			}
			if tc.name == "nginx_200_access" {
				if got.ParsedFields == nil {
					t.Errorf("ParsedFields should not be nil for nginx_200_access")
				} else if got.ParsedFields.StatusCode == nil || *got.ParsedFields.StatusCode != 200 {
					t.Errorf("ParsedFields.StatusCode = %v, want 200", got.ParsedFields.StatusCode)
				}
			}
		})
	}
}

func TestEnrichClassification(t *testing.T) {
	t.Run("db_too_many_connections", func(t *testing.T) {
		ev := Event{Service: "mariadb"}
		prof := profileOrNil(t, "mariadb", "", "/var/log/mysql/error.log")
		signal, cat, class := EnrichClassification(ev, "problem", "db_too_many_connections", prof)
		if signal != "database" {
			t.Errorf("signal = %q, want %q", signal, "database")
		}
		if cat != "db_too_many_connections" {
			t.Errorf("category = %q, want %q", cat, "db_too_many_connections")
		}
		if class.RuleID != "db.connection_limit.v1" {
			t.Errorf("RuleID = %q, want %q", class.RuleID, "db.connection_limit.v1")
		}
	})
}

func profileOrNil(t *testing.T, service, logType, filePath string) *profile.SourceProfile {
	p := profile.ProfileSource(profile.EventSource{
		Service:  service,
		LogType:  logType,
		FilePath: filePath,
	})
	return &p
}

func stringSliceEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
