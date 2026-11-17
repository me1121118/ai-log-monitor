package proxy

import (
	"encoding/json"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"time"
)

func New(target *url.URL, transport http.RoundTripper) http.Handler {
	if transport == nil {
		transport = NewTransport(30 * time.Second)
	}

	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.Transport = transport

	director := proxy.Director
	proxy.Director = func(r *http.Request) {
		director(r)
		r.Header.Del("X-Internal-Auth")
	}

	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(map[string]string{"error": "upstream unavailable"})
	}

	return proxy
}

func NewTransport(upstreamTimeout time.Duration) *http.Transport {
	return &http.Transport{
		DialContext: (&net.Dialer{
			Timeout:   upstreamTimeout,
			KeepAlive: 30 * time.Second,
		}).DialContext,
		TLSHandshakeTimeout:   min(upstreamTimeout, 10*time.Second),
		ResponseHeaderTimeout: upstreamTimeout,
		MaxIdleConns:          100,
		MaxConnsPerHost:       100,
		IdleConnTimeout:       90 * time.Second,
	}
}
