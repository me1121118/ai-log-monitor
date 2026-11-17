package profile

import "testing"

func TestProfileSource_KnownServicePaths(t *testing.T) {
	cases := []struct {
		name        string
		src         EventSource
		wantClass   string
		wantKind    string
		wantTraffic bool
	}{
		{
			name:        "nginx_access",
			src:         EventSource{Service: "nginx", FilePath: "/host/var/log/nginx/access.log"},
			wantClass:   "proxy",
			wantKind:    "access",
			wantTraffic: true,
		},
		{
			name:        "nginx_error",
			src:         EventSource{Service: "nginx", FilePath: "/host/var/log/nginx/error.log"},
			wantClass:   "proxy",
			wantKind:    "error",
			wantTraffic: false,
		},
		{
			name:        "mariadb_error",
			src:         EventSource{Service: "mariadb", FilePath: "/host/var/log/mysql/error.log"},
			wantClass:   "database",
			wantKind:    "error",
			wantTraffic: false,
		},
		{
			name:        "haproxy_journal",
			src:         EventSource{Service: "haproxy", LogType: "journal"},
			wantClass:   "proxy",
			wantKind:    "journal",
			wantTraffic: true,
		},
		{
			name:        "kernel_syslog",
			src:         EventSource{Service: "kernel", FilePath: "/host/var/log/syslog"},
			wantClass:   "system",
			wantKind:    "system",
			wantTraffic: false,
		},
		{
			name:        "auth_log",
			src:         EventSource{Service: "sshd", FilePath: "/host/var/log/auth.log"},
			wantClass:   "security",
			wantKind:    "audit",
			wantTraffic: false,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := ProfileSource(tc.src)
			if got.ServiceClass != tc.wantClass {
				t.Errorf("ServiceClass = %q, want %q", got.ServiceClass, tc.wantClass)
			}
			if got.SourceKind != tc.wantKind {
				t.Errorf("SourceKind = %q, want %q", got.SourceKind, tc.wantKind)
			}
			if got.TrafficCandidate != tc.wantTraffic {
				t.Errorf("TrafficCandidate = %v, want %v", got.TrafficCandidate, tc.wantTraffic)
			}
		})
	}
}

func TestProfileSource_UnknownIsNotTraffic(t *testing.T) {
	got := ProfileSource(EventSource{Service: "custom", FilePath: "/opt/custom/log.txt"})
	if got.ServiceClass != "unknown" {
		t.Errorf("ServiceClass = %q, want %q", got.ServiceClass, "unknown")
	}
	if got.TrafficCandidate {
		t.Errorf("TrafficCandidate = true, want false")
	}
}
