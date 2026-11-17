package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"net/url"
	"os/signal"
	"syscall"
	"time"

	"ai-log-server/server/gateway/internal/config"
	"ai-log-server/server/gateway/internal/contextbuffer"
	"ai-log-server/server/gateway/internal/ingest"
	"ai-log-server/server/gateway/internal/proxy"
	"ai-log-server/server/gateway/internal/router"
	"ai-log-server/server/gateway/internal/shadow"
	"ai-log-server/server/gateway/internal/traffic"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	if err := run(ctx, cfg); err != nil {
		log.Fatalf("server: %v", err)
	}
}

func run(ctx context.Context, cfg config.Config) error {
	target, err := url.Parse(cfg.PythonBaseURL)
	if err != nil {
		return err
	}

	proxyHandler := proxy.New(target, proxy.NewTransport(cfg.UpstreamTimeout))

	client := &http.Client{
		Timeout: cfg.UpstreamTimeout,
	}

	var dataHandler http.Handler
	var metricsSnapshot func() any
	statsKey := "shadow"
	if cfg.IngestMode == "" || cfg.IngestMode == "shadow" {
		shadowMetrics := &shadow.Metrics{}
		dataHandler = shadow.New(proxyHandler, cfg.MaxInspectBodyBytes, shadowMetrics)
		metricsSnapshot = func() any { return shadowMetrics.Snapshot() }
	} else {
		statsKey = "evidence"
		context := contextbuffer.New()
		trafficDetector := traffic.New()
		ingestMetrics := &ingest.Metrics{}
		dataHandler, err = ingest.New(
			proxyHandler,
			cfg.PythonBaseURL,
			client,
			cfg.GatewayInternalToken,
			cfg.MaxInspectBodyBytes,
			cfg.AgentAuthCacheTTL,
			context,
			trafficDetector,
			ingestMetrics,
		)
		if err != nil {
			return err
		}
		metricsSnapshot = func() any {
			return map[string]any{"ingest": ingestMetrics.Snapshot(), "context": context.Snapshot(), "traffic": trafficDetector.Snapshot()}
		}
	}

	healthURL := target.ResolveReference(&url.URL{Path: "/health"}).String()
	handler := router.NewWithRuntimeStats(
		dataHandler,
		healthURL,
		client,
		statsKey,
		metricsSnapshot,
	)

	server := &http.Server{
		Addr:              cfg.ListenAddress,
		Handler:           handler,
		ReadHeaderTimeout: cfg.ReadHeaderTimeout,
		IdleTimeout:       cfg.IdleTimeout,
	}

	errCh := make(chan error, 1)
	go func() {
		log.Printf("listening on %s", cfg.ListenAddress)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
	}()

	select {
	case <-ctx.Done():
	case err := <-errCh:
		return err
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	return server.Shutdown(shutdownCtx)
}
