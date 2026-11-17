package shadow

import (
	"bytes"
	"encoding/json"
	"io"
	"mime"
	"net/http"
	"strings"
	"sync/atomic"

	"ai-log-server/server/gateway/internal/classifier"
)

type Metrics struct {
	Inspected  atomic.Int64
	Matched    atomic.Int64
	Mismatched atomic.Int64
	Bypassed   atomic.Int64
}

type MetricsSnapshot struct {
	Inspected  int64 `json:"inspected"`
	Matched    int64 `json:"matched"`
	Mismatched int64 `json:"mismatched"`
	Bypassed   int64 `json:"bypassed"`
}

func (m *Metrics) Snapshot() MetricsSnapshot {
	return MetricsSnapshot{
		Inspected:  m.Inspected.Load(),
		Matched:    m.Matched.Load(),
		Mismatched: m.Mismatched.Load(),
		Bypassed:   m.Bypassed.Load(),
	}
}

func New(next http.Handler, maxBodyBytes int64, metrics *Metrics) http.Handler {
	if metrics == nil {
		metrics = &Metrics{}
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/api/ingest" {
			next.ServeHTTP(w, r)
			return
		}

		mediaType, _, contentTypeErr := mime.ParseMediaType(r.Header.Get("Content-Type"))
		if contentTypeErr != nil || !strings.EqualFold(mediaType, "application/json") || maxBodyBytes <= 0 {
			metrics.Bypassed.Add(1)
			next.ServeHTTP(w, r)
			return
		}
		if r.ContentLength > maxBodyBytes {
			metrics.Bypassed.Add(1)
			next.ServeHTTP(w, r)
			return
		}

		originalBody := r.Body
		body, err := readBody(originalBody, maxBodyBytes+1)
		r.Body = &replayReadCloser{
			Reader: io.MultiReader(bytes.NewReader(body), originalBody),
			Closer: originalBody,
		}

		if err != nil {
			metrics.Bypassed.Add(1)
			next.ServeHTTP(w, r)
			return
		}

		if int64(len(body)) > maxBodyBytes {
			metrics.Bypassed.Add(1)
			next.ServeHTTP(w, r)
			return
		}

		trimmed := bytes.TrimLeft(body, " \t\r\n")
		if len(trimmed) > 0 && trimmed[0] == '[' {
			metrics.Bypassed.Add(1)
			next.ServeHTTP(w, r)
			return
		}

		var ev classifier.Event
		if err := json.Unmarshal(body, &ev); err != nil || strings.TrimSpace(ev.Message) == "" {
			metrics.Bypassed.Add(1)
			next.ServeHTTP(w, r)
			return
		}

		metrics.Inspected.Add(1)

		crw := &captureWriter{ResponseWriter: w, buf: new(bytes.Buffer)}
		next.ServeHTTP(crw, r)

		var respData struct {
			Severity string `json:"severity"`
			Category string `json:"category"`
		}
		if json.Unmarshal(crw.buf.Bytes(), &respData) == nil && respData.Severity != "" && respData.Category != "" {
			result := classifier.ClassifyEvent(ev)
			if respData.Severity == result.Severity && respData.Category == result.Category {
				metrics.Matched.Add(1)
			} else {
				metrics.Mismatched.Add(1)
			}
		} else {
			metrics.Mismatched.Add(1)
		}
	})
}

type replayReadCloser struct {
	io.Reader
	io.Closer
}

type captureWriter struct {
	http.ResponseWriter
	buf *bytes.Buffer
}

func (w *captureWriter) Write(p []byte) (int, error) {
	remaining := 64*1024 - w.buf.Len()
	if remaining > 0 {
		if len(p) > remaining {
			w.buf.Write(p[:remaining])
		} else {
			w.buf.Write(p)
		}
	}
	return w.ResponseWriter.Write(p)
}

func (w *captureWriter) Unwrap() http.ResponseWriter {
	return w.ResponseWriter
}

func readBody(r io.Reader, limit int64) ([]byte, error) {
	var buf bytes.Buffer
	_, err := io.Copy(&buf, io.LimitReader(r, limit))
	return buf.Bytes(), err
}
