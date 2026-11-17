package parser

import (
	"strings"
	"testing"
)

func TestParseSignalFields_HTTPRequestStatusAndLatency(t *testing.T) {
	got := ParseSignalFields(EventInput{
		Message: `10.0.0.1 - - "GET /api/orders HTTP/1.1" 503 120 request_time=0.250`,
	})
	if got.RequestMethod != "GET" {
		t.Errorf("RequestMethod = %q, want %q", got.RequestMethod, "GET")
	}
	if got.RequestPath != "/api/orders" {
		t.Errorf("RequestPath = %q, want %q", got.RequestPath, "/api/orders")
	}
	if got.StatusCode == nil || *got.StatusCode != 503 {
		t.Errorf("StatusCode = %v, want %d", got.StatusCode, 503)
	}
	if got.LatencyMS == nil || *got.LatencyMS != 250.0 {
		t.Errorf("LatencyMS = %v, want %f", got.LatencyMS, 250.0)
	}
}

func TestParseSignalFields_DatabaseErrorCode(t *testing.T) {
	got := ParseSignalFields(EventInput{
		Message: "[ERROR] [MY-010119] Aborting due to too many connections",
	})
	if got.DatabaseErrorCode != "MY-010119" {
		t.Errorf("DatabaseErrorCode = %q, want %q", got.DatabaseErrorCode, "MY-010119")
	}
}

func TestParseSignalFields_ExistingStatusCodeHasPrecedence(t *testing.T) {
	statusCode := 502
	got := ParseSignalFields(EventInput{
		StatusCode: &statusCode,
		Message:    `"GET / HTTP/1.1" 200 10`,
	})
	if got.StatusCode == nil || *got.StatusCode != 502 {
		t.Errorf("StatusCode = %v, want %d", got.StatusCode, 502)
	}
}

func TestParseSignalFields_DoesNotInspectPastEightKiB(t *testing.T) {
	got := ParseSignalFields(EventInput{
		Message: strings.Repeat("x", 8192) + ` "GET /hidden HTTP/1.1" 503 10`,
	})
	if got.StatusCode != nil || got.RequestPath != "" {
		t.Fatalf("parser inspected fields beyond the 8 KiB limit: %+v", got)
	}
}
