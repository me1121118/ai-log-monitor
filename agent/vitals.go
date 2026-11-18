package main

import (
	"context"
	"math"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"time"
)

type HostVitals struct {
	CPUPercent  float64 `json:"cpu_percent"`
	RAMPercent  float64 `json:"ram_percent"`
	DiskPercent float64 `json:"disk_percent"`
}

func collectHostVitals() HostVitals {
	return HostVitals{
		CPUPercent:  collectCPUPercent(),
		RAMPercent:  collectRAMPercent(),
		DiskPercent: collectDiskPercent(),
	}
}

func collectRAMPercent() float64 {
	for _, path := range []string{"/host/proc/meminfo", "/proc/meminfo"} {
		if data, err := os.ReadFile(path); err == nil {
			if pct := parseMemInfo(string(data)); pct > 0 {
				return pct
			}
		}
	}
	return 0
}

func parseMemInfo(content string) float64 {
	var memTotal, memAvailable, memFree, buffers, cached float64
	hasAvailable := false

	for _, line := range strings.Split(content, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		key := strings.TrimSuffix(fields[0], ":")
		val, err := strconv.ParseFloat(fields[1], 64)
		if err != nil {
			continue
		}
		switch key {
		case "MemTotal":
			memTotal = val
		case "MemAvailable":
			memAvailable = val
			hasAvailable = true
		case "MemFree":
			memFree = val
		case "Buffers":
			buffers = val
		case "Cached":
			cached = val
		}
	}

	if memTotal <= 0 {
		return 0
	}
	avail := memAvailable
	if !hasAvailable {
		avail = memFree + buffers + cached
	}
	used := memTotal - avail
	if used < 0 {
		used = 0
	}
	pct := (used / memTotal) * 100.0
	return clampRoundPercent(pct)
}

func collectCPUPercent() float64 {
	numCPU := runtime.NumCPU()
	if numCPU <= 0 {
		numCPU = 1
	}
	for _, path := range []string{"/host/proc/loadavg", "/proc/loadavg"} {
		if data, err := os.ReadFile(path); err == nil {
			if pct, ok := parseLoadAvg(string(data), numCPU); ok {
				return pct
			}
		}
	}
	for _, path := range []string{"/host/proc/stat", "/proc/stat"} {
		if data, err := os.ReadFile(path); err == nil {
			if pct, ok := parseProcStatCPU(string(data)); ok {
				return pct
			}
		}
	}
	return 0
}

func parseLoadAvg(content string, numCPU int) (float64, bool) {
	fields := strings.Fields(content)
	if len(fields) == 0 {
		return 0, false
	}
	load1, err := strconv.ParseFloat(fields[0], 64)
	if err != nil {
		return 0, false
	}
	if numCPU <= 0 {
		numCPU = 1
	}
	pct := (load1 / float64(numCPU)) * 100.0
	return clampRoundPercent(pct), true
}

func parseProcStatCPU(content string) (float64, bool) {
	for _, line := range strings.Split(content, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 5 || fields[0] != "cpu" {
			continue
		}
		var total, idle float64
		for i := 1; i < len(fields); i++ {
			v, err := strconv.ParseFloat(fields[i], 64)
			if err != nil {
				continue
			}
			total += v
			if i == 4 { // idle only (iowait is i==5 and counts as busy I/O wait)
				idle += v
			}
		}
		if total <= 0 {
			return 0, false
		}
		busy := total - idle
		if busy < 0 {
			busy = 0
		}
		return clampRoundPercent((busy / total) * 100.0), true
	}
	return 0, false
}

func collectDiskPercent() float64 {
	if runtime.GOOS == "windows" {
		return 0
	}
	targets := []string{"/host/var/log", "/host", "/var/log", "/"}
	for _, target := range targets {
		if info, err := os.Stat(target); err != nil || !info.IsDir() {
			continue
		}
		ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
		out, err := exec.CommandContext(ctx, "df", "-P", target).Output()
		cancel()
		if err != nil {
			continue
		}
		if pct := parseDfOutput(string(out)); pct > 0 {
			return pct
		}
	}
	return 0
}

func parseDfOutput(output string) float64 {
	lines := strings.Split(strings.TrimSpace(output), "\n")
	if len(lines) < 2 {
		return 0
	}
	for _, line := range lines[1:] {
		fields := strings.Fields(line)
		if len(fields) < 5 {
			continue
		}
		for _, field := range fields {
			if strings.HasSuffix(field, "%") {
				trimmed := strings.TrimSuffix(field, "%")
				if val, err := strconv.ParseFloat(trimmed, 64); err == nil {
					return clampRoundPercent(val)
				}
			}
		}
	}
	return 0
}

func clampRoundPercent(val float64) float64 {
	if math.IsNaN(val) || math.IsInf(val, 0) || val < 0 {
		return 0
	}
	if val > 100 {
		val = 100
	}
	return math.Round(val*10) / 10
}
