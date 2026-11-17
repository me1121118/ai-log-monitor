package parser

import (
	"regexp"
	"strconv"
	"strings"
)

var (
	httpRequest = regexp.MustCompile(`(?i)"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)\s+HTTP/\d(?:\.\d)?"\s+(\d{3})`)
	latencySec  = regexp.MustCompile(`(?:request_time|response_time|rt)=(\d+(?:\.\d+)?)`)
	latencyMS   = regexp.MustCompile(`(?i)(\d+(?:\.\d+)?)\s*ms\b`)
	databaseErr = regexp.MustCompile(`(?i)\b(MY-\d{6}|SQLSTATE\[[A-Z0-9]+\]|ERROR\s+\d{3,5})\b`)
)

type EventInput struct {
	Message    string
	StatusCode *int
}

type ParsedFields struct {
	StatusCode        *int
	RequestMethod     string
	RequestPath       string
	LatencyMS         *float64
	DatabaseErrorCode string
}

func ParseSignalFields(inp EventInput) ParsedFields {
	msg := inp.Message
	if len(msg) > 8192 {
		msg = msg[:8192]
	}

	var fields ParsedFields

	if m := httpRequest.FindStringSubmatch(msg); m != nil {
		fields.RequestMethod = strings.ToUpper(m[1])
		path := m[2]
		if len(path) > 2048 {
			path = path[:2048]
		}
		fields.RequestPath = path
		if status, err := strconv.Atoi(m[3]); err == nil {
			fields.StatusCode = &status
		}
	}

	if inp.StatusCode != nil {
		fields.StatusCode = inp.StatusCode
	}

	if m := latencySec.FindStringSubmatch(msg); m != nil {
		if sec, err := strconv.ParseFloat(m[1], 64); err == nil {
			v := roundTo3(sec * 1000)
			fields.LatencyMS = &v
		}
	} else if m := latencyMS.FindStringSubmatch(msg); m != nil {
		if ms, err := strconv.ParseFloat(m[1], 64); err == nil {
			v := ms
			fields.LatencyMS = &v
		}
	}

	if m := databaseErr.FindStringSubmatch(msg); m != nil {
		code := strings.ToUpper(m[1])
		code = strings.ReplaceAll(code, "  ", " ")
		fields.DatabaseErrorCode = code
	}

	return fields
}

func roundTo3(v float64) float64 {
	return float64(int(v*1000+0.5)) / 1000
}
