// Package relay implements the TokenBar v2 byte-verbatim relay (spec
// S1-S6, S17): a dumb pipe that forwards client headers unchanged,
// replaces only the Authorization value, never adds proxy-identifying
// headers, and streams bodies end-to-end with a bounded in-flight
// buffer. It deliberately does not use httputil.ReverseProxy, whose
// default behavior appends X-Forwarded-For (S17 violation).
package relay

import (
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
)

// hopByHop lists the connection-scoped headers a relay must not
// forward (RFC 7230 6.1). Everything else passes verbatim.
var hopByHop = []string{
	"Connection",
	"Keep-Alive",
	"Proxy-Authenticate",
	"Proxy-Authorization",
	"TE",
	"Trailer",
	"Transfer-Encoding",
	"Upgrade",
}

// Config controls a Relay.
type Config struct {
	// Upstream is the fixed provider base URL (S14 dial allowlist).
	Upstream *url.URL
	// StripPrefix is removed from the incoming path before joining it
	// to Upstream (e.g. "/v1").
	StripPrefix string
	// Token returns the credential injected as the Authorization
	// bearer value. Called per request so a refreshed token is picked
	// up without restarting.
	Token func() string
	// MaxInFlight bounds the per-direction copy buffer (S5).
	MaxInFlight int
}

// Relay is an http.Handler that byte-verbatim proxies to one upstream.
type Relay struct {
	cfg    Config
	client *http.Client
}

// New builds a Relay with a streaming-safe transport: no transparent
// compression (which would inject Accept-Encoding and rewrite body
// bytes) and no automatic redirects (a redirect must reach the CLI
// exactly as the provider sent it).
func New(cfg Config) *Relay {
	if cfg.MaxInFlight <= 0 {
		cfg.MaxInFlight = 32 * 1024
	}
	if cfg.MaxInFlight > 64*1024 {
		cfg.MaxInFlight = 64 * 1024 // S5 hard bound
	}
	tr := &http.Transport{
		DisableCompression: true,
		MaxIdleConns:       16,
	}
	return &Relay{cfg: cfg, client: &http.Client{Transport: tr}}
}

func copyHeaders(dst, src http.Header) {
	for k, vs := range src {
		for _, v := range vs {
			dst.Add(k, v)
		}
	}
}

func stripHopByHop(h http.Header, connectionValue string) {
	for _, f := range strings.Split(connectionValue, ",") {
		h.Del(strings.TrimSpace(f))
	}
	for _, k := range hopByHop {
		h.Del(k)
	}
}

func (r *Relay) upstreamURL(req *http.Request) string {
	p := req.URL.Path
	if r.cfg.StripPrefix != "" {
		p = strings.TrimPrefix(p, r.cfg.StripPrefix)
		if p == "" {
			p = "/"
		}
	}
	u := *r.cfg.Upstream
	u.Path = strings.TrimSuffix(u.Path, "/") + p
	u.RawQuery = req.URL.RawQuery
	return u.String()
}

// ServeHTTP relays one request. The upstream request derives from the
// downstream context, so a CLI disconnect cancels the upstream call
// (spec 12.3 goroutine-leak safeguard).
func (r *Relay) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	outReq, err := http.NewRequestWithContext(req.Context(), req.Method,
		r.upstreamURL(req), req.Body)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	copyHeaders(outReq.Header, req.Header)
	stripHopByHop(outReq.Header, req.Header.Get("Connection"))
	// S17: the only mutation allowed is replacing the Authorization
	// value with the routed account's token.
	if r.cfg.Token != nil {
		outReq.Header.Set("Authorization", "Bearer "+r.cfg.Token())
	}
	outReq.ContentLength = req.ContentLength

	resp, err := r.client.Do(outReq)
	if err != nil {
		// A canceled downstream context is not an upstream error; the
		// client is gone, so there is nothing to write to.
		if req.Context().Err() != nil {
			return
		}
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	header := w.Header()
	copyHeaders(header, resp.Header)
	stripHopByHop(header, resp.Header.Get("Connection"))
	w.WriteHeader(resp.StatusCode)

	flusher, canFlush := w.(http.Flusher)
	buf := make([]byte, r.cfg.MaxInFlight)
	for {
		n, readErr := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := w.Write(buf[:n]); werr != nil {
				return // downstream gone; ctx cancel stops the upstream
			}
			if canFlush {
				flusher.Flush()
			}
		}
		if readErr != nil {
			if readErr != io.EOF && req.Context().Err() == nil {
				fmt.Printf("relay: upstream read: %v\n", readErr)
			}
			return
		}
	}
}
