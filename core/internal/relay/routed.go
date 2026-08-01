// routed.go wires the byte-verbatim relay to the pool and routing
// table (phase M1): credentials come from the routed account instead
// of one static token, and a hard upstream rejection may trigger one
// failover retry — only for session-initial requests (S19) and only
// when the provider's policy opts in (S9).
package relay

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
)

// RoutedCred is the credential material for one routed account.
type RoutedCred struct {
	AccountID int64
	Token     string
	// PairName/PairValue pair with the token for providers that
	// require it (S17: e.g. ChatGPT-Account-Id). Empty = untouched.
	PairName  string
	PairValue string
}

// CredentialSource adapts routing+pool to the relay.
type CredentialSource interface {
	Pick(ctx context.Context) (RoutedCred, error)
	// Next returns the failover candidate after prev (S8: one retry).
	Next(ctx context.Context, prev RoutedCred) (RoutedCred, error)
	// ReportHardFailure enters prev into cooldown (S10).
	ReportHardFailure(prev RoutedCred, status int)
	// FailoverAllowed reports whether the provider's policy opts into
	// automatic failover (S9: pin never fails over automatically).
	FailoverAllowed() bool
}

// Routed is the pool-backed relay handler.
type Routed struct {
	Upstream    *url.URL
	StripPrefix string
	Source      CredentialSource
	MaxInFlight int
	client      *http.Client
}

func NewRouted(upstream *url.URL, stripPrefix string, src CredentialSource) *Routed {
	base := New(Config{Upstream: upstream, StripPrefix: stripPrefix, MaxInFlight: 32 * 1024})
	return &Routed{
		Upstream:    upstream,
		StripPrefix: stripPrefix,
		Source:      src,
		MaxInFlight: 32 * 1024,
		client:      base.client,
	}
}

// maxBodyPeek bounds how much of a request body we buffer to detect
// continuity markers. Bodies beyond this are relayed without failover
// eligibility (safe default: no retry).
const maxBodyPeek = 1 << 20

// continuityMarkers are JSON keys marking a request as the
// continuation of a provider-side session (S19).
var continuityMarkers = []string{
	"previous_response_id",
	"conversation",
	"conversation_id",
	"session_id",
}

func hasContinuityMarker(body []byte) bool {
	var doc map[string]json.RawMessage
	if err := json.Unmarshal(body, &doc); err != nil {
		return false // not JSON: cannot inspect, treat as initial
	}
	for _, k := range continuityMarkers {
		if v, ok := doc[k]; ok && len(v) > 0 && string(v) != "null" && string(v) != `""` {
			return true
		}
	}
	return false
}

// HardSignalForFailover reports definitive quota/auth rejections (S7).
// Timeouts and 5xx are never failover triggers.
func HardSignalForFailover(status int) bool {
	return status == 429 || status == 401 || status == 403
}

func (r *Routed) upstreamURL(req *http.Request) string {
	rr := &Relay{cfg: Config{Upstream: r.Upstream, StripPrefix: r.StripPrefix}}
	return rr.upstreamURL(req)
}

// attempt performs one verbatim relay try. When commit is false and
// the upstream answers a hard signal, the error body is discarded
// (nothing reaches the client) and the call returns retryable=true;
// in every other case the response is streamed verbatim.
func (r *Routed) attempt(w http.ResponseWriter, req *http.Request, body io.Reader, cred RoutedCred, commit bool) (status int, retryable bool) {
	outReq, err := http.NewRequestWithContext(req.Context(), req.Method,
		r.upstreamURL(req), body)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return 0, false
	}
	copyHeaders(outReq.Header, req.Header)
	stripHopByHop(outReq.Header, req.Header.Get("Connection"))
	outReq.Header.Set("Authorization", "Bearer "+cred.Token)
	if cred.PairName != "" {
		outReq.Header.Set(cred.PairName, cred.PairValue)
	}
	outReq.ContentLength = req.ContentLength

	resp, err := r.client.Do(outReq)
	if err != nil {
		if req.Context().Err() != nil {
			return 0, false
		}
		http.Error(w, err.Error(), http.StatusBadGateway)
		return 0, false
	}
	defer resp.Body.Close()

	if !commit && HardSignalForFailover(resp.StatusCode) {
		io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<20))
		return resp.StatusCode, true
	}

	header := w.Header()
	copyHeaders(header, resp.Header)
	stripHopByHop(header, resp.Header.Get("Connection"))
	w.WriteHeader(resp.StatusCode)

	flusher, canFlush := w.(http.Flusher)
	buf := make([]byte, r.MaxInFlight)
	for {
		n, readErr := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := w.Write(buf[:n]); werr != nil {
				return resp.StatusCode, false
			}
			if canFlush {
				flusher.Flush()
			}
		}
		if readErr != nil {
			return resp.StatusCode, false
		}
	}
}

func (r *Routed) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	// Buffer small bodies so they can be replayed on a failover retry
	// and inspected for continuity markers (S19). The bytes are
	// forwarded unchanged — inspection never transforms (S1).
	var bodyBytes []byte
	if req.Body != nil && req.ContentLength >= 0 && req.ContentLength <= maxBodyPeek {
		b, err := io.ReadAll(req.Body)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		req.Body.Close()
		bodyBytes = b
	}
	sessionInitial := bodyBytes == nil || !hasContinuityMarker(bodyBytes)

	cred, err := r.Source.Pick(req.Context())
	if err != nil {
		http.Error(w, err.Error(), http.StatusServiceUnavailable)
		return
	}

	newBody := func() io.Reader {
		if bodyBytes != nil {
			return bytes.NewReader(bodyBytes)
		}
		return req.Body
	}

	// Retry is only on the table for session-initial requests on
	// providers that opted into failover (S8/S9/S19).
	mayRetry := sessionInitial && r.Source.FailoverAllowed() && bodyBytes != nil
	status, retryable := r.attempt(w, req, newBody(), cred, !mayRetry)
	if HardSignalForFailover(status) {
		r.Source.ReportHardFailure(cred, status)
	}
	if !retryable {
		return
	}
	next, err := r.Source.Next(req.Context(), cred)
	if err != nil {
		// No other candidate: replay the original failure verbatim by
		// re-attempting against the same (now cooling) account would
		// lie; return the recorded status with an empty body.
		w.WriteHeader(status)
		return
	}
	status, _ = r.attempt(w, req, newBody(), next, true)
	if HardSignalForFailover(status) {
		r.Source.ReportHardFailure(next, status)
	}
}
