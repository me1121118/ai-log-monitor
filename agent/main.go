package main

import (
	"flag"
	"log"
	"time"
)

func main() {
	configFlag := flag.String("config", "/etc/ai-log-agent/agent.yaml", "Path to agent config file")
	onceFlag := flag.Bool("once", false, "Run scan once and exit")
	flag.Parse()

	cfg, err := loadConfig(*configFlag)
	if err != nil {
		log.Fatalf("failed to load config: %v", err)
	}

	// Discover logs
	if cfg.Logs.AutoDiscover {
		cfg.Logs.Paths = discoverLogPathsWithRoots(
			cfg.Logs.Paths,
			cfg.Logs.DiscoveryRoots,
			cfg.Logs.DiscoveryMaxFiles,
		)
	}

	agentToken, err := resolveAgentToken(cfg, registerAgent)
	if err != nil {
		log.Fatalf("failed to prepare agent token: %v", err)
	}
	log.Print("Agent token ready.")
	if err := reportLogSources(cfg.Server.URL, agentToken, *cfg); err != nil {
		if isUnauthorizedStatus(err) {
			refreshedToken, refreshErr := refreshAgentToken(cfg, registerAgent)
			if refreshErr != nil {
				log.Printf("failed to refresh agent token after source report rejection: %v", refreshErr)
			} else {
				agentToken = refreshedToken
				if retryErr := reportLogSources(cfg.Server.URL, agentToken, *cfg); retryErr != nil {
					log.Printf("failed to report log sources after token refresh: %v", retryErr)
				}
			}
		} else {
			log.Printf("failed to report log sources: %v", err)
		}
	}
	topologyHints := discoverTopologyHintsWithRoots(topologyDiscoveryRoots(cfg.Logs.DiscoveryRoots), cfg.Logs.DiscoveryMaxFiles)
	if err := reportTopologyHints(cfg.Server.URL, agentToken, *cfg, topologyHints); err != nil {
		if isUnauthorizedStatus(err) {
			refreshedToken, refreshErr := refreshAgentToken(cfg, registerAgent)
			if refreshErr != nil {
				log.Printf("failed to refresh agent token after topology report rejection: %v", refreshErr)
			} else {
				agentToken = refreshedToken
				if retryErr := reportTopologyHints(cfg.Server.URL, agentToken, *cfg, topologyHints); retryErr != nil {
					log.Printf("failed to report topology hints after token refresh: %v", retryErr)
				}
			}
		} else {
			log.Printf("failed to report topology hints: %v", err)
		}
	}

	scanInterval := time.Duration(cfg.Runtime.ScanIntervalSeconds) * time.Second
	if scanInterval <= 0 {
		scanInterval = 3 * time.Second
	}
	heartbeatInterval := time.Duration(cfg.Runtime.HeartbeatIntervalSeconds) * time.Second
	if heartbeatInterval <= 0 {
		heartbeatInterval = 30 * time.Second
	}
	var lastHeartbeat time.Time

	for {
		if lastHeartbeat.IsZero() || time.Since(lastHeartbeat) >= heartbeatInterval {
			if err := sendHeartbeat(cfg.Server.URL, agentToken, *cfg); err != nil {
				if isUnauthorizedStatus(err) {
					refreshedToken, refreshErr := refreshAgentToken(cfg, registerAgent)
					if refreshErr != nil {
						log.Printf("failed to refresh agent token after heartbeat rejection: %v", refreshErr)
					} else {
						agentToken = refreshedToken
						if retryErr := sendHeartbeat(cfg.Server.URL, agentToken, *cfg); retryErr != nil {
							log.Printf("failed to send heartbeat after token refresh: %v", retryErr)
						}
					}
				} else {
					log.Printf("failed to send heartbeat: %v", err)
				}
			}
			lastHeartbeat = time.Now()
		}
		events, err := scanOnce(cfg)
		if err != nil {
			log.Printf("error scanning logs: %v", err)
		} else {
			if sent, err := flushSpoolEvents(cfg.Runtime.StateDir, func(event Event) error {
				return ingestEvent(cfg.Server.URL, agentToken, event)
			}); err != nil {
				log.Printf("failed to flush %d queued event(s): %v", sent, err)
			}
			for _, event := range prioritizeEvents(events) {
				err := ingestEvent(cfg.Server.URL, agentToken, event)
				if err != nil {
					if isUnauthorizedStatus(err) {
						refreshedToken, refreshErr := refreshAgentToken(cfg, registerAgent)
						if refreshErr != nil {
							log.Printf("failed to refresh agent token after ingest rejection: %v", refreshErr)
						} else {
							agentToken = refreshedToken
							err = ingestEvent(cfg.Server.URL, agentToken, event)
						}
					}
				}
				if err != nil {
					log.Printf("failed to ingest event: %v", err)
					if spoolErr := appendSpoolEvent(cfg.Runtime.StateDir, event, cfg.Runtime.SpoolMaxBytes); spoolErr != nil {
						log.Printf("failed to spool event: %v", spoolErr)
					}
				}
			}
		}

		if *onceFlag {
			break
		}
		time.Sleep(scanInterval)
	}
}

// --------------------- CONFIG LOADER ---------------------
