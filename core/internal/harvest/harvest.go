// Package harvest is the request-path quota tap (S4): a read-only tee
// on bytes already transiting the relay. A harvest failure is logged
// and dropped, never propagated.
package harvest

import (
	"bufio"
	"bytes"
	"encoding/json"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"tokenbar/internal/quota"
)

// Observation is one response's harvested state.
type Observation struct {
	AccountID int64
	At        time.Time
	Windows   []quota.Window
	Usage     *Usage
	Source    string // "headers" | "body"
}

// Usage is metered token usage from a response body.
type Usage struct {
	InputTokens  int64 `json:"input_tokens"`
	OutputTokens int64 `json:"output_tokens"`
}

// Sink consumes observations off the relay critical path.
type Sink interface {
	Observe(Observation)
}

// LogSink drops observations into the log (M2 default until the quota
// engine is wired in main).
type LogSink struct{}

func (LogSink) Observe(o Observation) {
	log.Printf("harvest: account=%d source=%s windows=%d usage=%+v",
		o.AccountID, o.Source, len(o.Windows), o.Usage)
}

// FromHeaders extracts rate-limit windows from response headers.
// Anthropic: anthropic-ratelimit-*; OpenAI-style: x-ratelimit-*.
// Unknown shapes yield nothing — harvest never errors upward (S4).
func FromHeaders(accountID int64, h http.Header) Observation {
	o := Observation{AccountID: accountID, At: time.Now(), Source: "headers"}
	get := func(k string) string { return h.Get(k) }
	f64 := func(s string) (float64, bool) {
		v, err := strconv.ParseFloat(strings.TrimSpace(s), 64)
		return v, err == nil
	}
	add := func(kind string, usedPct float64, reset string) {
		w := quota.Window{Kind: kind, UsedPct: &usedPct}
		if reset != "" {
			if ts, err := time.Parse(time.RFC3339, reset); err == nil {
				epoch := float64(ts.Unix())
				w.ResetAt = &epoch
			} else if v, ok := f64(reset); ok {
				w.ResetAt = &v
			}
		}
		o.Windows = append(o.Windows, w)
	}
	// Anthropic unified 5h/7d utilization headers (0..1 fractions).
	if v, ok := f64(get("Anthropic-Ratelimit-Unified-5h-Utilization")); ok {
		add("5h", v*100, get("Anthropic-Ratelimit-Unified-5h-Reset"))
	}
	if v, ok := f64(get("Anthropic-Ratelimit-Unified-7d-Utilization")); ok {
		add("weekly", v*100, get("Anthropic-Ratelimit-Unified-7d-Reset"))
	}
	// Generic x-ratelimit buckets.
	if lim, ok1 := f64(get("X-Ratelimit-Limit-Requests")); ok1 {
		if rem, ok2 := f64(get("X-Ratelimit-Remaining-Requests")); ok2 && lim > 0 {
			add("requests", (1-rem/lim)*100, get("X-Ratelimit-Reset-Requests"))
		}
	}
	return o
}

// sseParser incrementally scans a relayed SSE stream for metered body
// fields (OpenAI response.completed usage; Anthropic message usage).
type sseParser struct {
	accountID int64
	sink      Sink
	buf       bytes.Buffer
	usage     *Usage
}

// TeeBody wraps an upstream response body: every byte read is also fed
// to the harvest parser. Parsing happens on the relay goroutine but is
// bounded (SSE line scan); model updates go to the sink only at Close.
func TeeBody(accountID int64, body interface{ Read([]byte) (int, error) }, sink Sink) *Tee {
	return &Tee{body: body, p: &sseParser{accountID: accountID, sink: sink}}
}

// Tee is a read-only stream tap.
type Tee struct {
	body interface{ Read([]byte) (int, error) }
	p    *sseParser
}

func (t *Tee) Read(b []byte) (int, error) {
	n, err := t.body.Read(b)
	if n > 0 {
		t.p.feed(b[:n])
	}
	return n, err
}

// Close flushes the observation to the sink. Failures are dropped.
func (t *Tee) Close() {
	if t.p.usage != nil {
		t.p.sink.Observe(Observation{
			AccountID: t.p.accountID, At: time.Now(),
			Usage: t.p.usage, Source: "body",
		})
	}
}

func (p *sseParser) feed(chunk []byte) {
	p.buf.Write(chunk)
	snapshot := append([]byte(nil), p.buf.Bytes()...)
	sc := bufio.NewScanner(bytes.NewReader(snapshot))
	sc.Buffer(make([]byte, 0, 256*1024), 256*1024)
	for sc.Scan() {
		p.parseLine(sc.Text())
	}
	// Keep only the trailing partial line for the next feed.
	if idx := bytes.LastIndexByte(p.buf.Bytes(), '\n'); idx >= 0 {
		keep := append([]byte(nil), p.buf.Bytes()[idx+1:]...)
		p.buf.Reset()
		p.buf.Write(keep)
	}
}

func (p *sseParser) parseLine(line string) {
	if !strings.HasPrefix(line, "data:") {
		return
	}
	data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
	if data == "" || data == "[DONE]" {
		return
	}
	var ev struct {
		Type     string `json:"type"`
		Response struct {
			Usage *Usage `json:"usage"`
		} `json:"response"`
		Usage *Usage `json:"usage"`
	}
	if err := json.Unmarshal([]byte(data), &ev); err != nil {
		return
	}
	switch {
	case ev.Type == "response.completed" && ev.Response.Usage != nil:
		p.usage = ev.Response.Usage
	case (ev.Type == "message_start" || ev.Type == "message_delta") && ev.Usage != nil:
		p.usage = ev.Usage
	}
}
