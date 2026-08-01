// tokenbar-core is the TokenBar v2 single-writer core. Phase M0 ships
// only the byte-verbatim relay with one configured credential; pool,
// routing, and the management API land in M1+.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync/atomic"

	"tokenbar/internal/relay"
)

// tokenSource reloads the credential lazily from disk so a refreshed
// token file is honored without a restart. M0 accepts either a raw
// bearer string or a codex auth.json document.
type tokenSource struct {
	path string
	cur  atomic.Value
}

func (t *tokenSource) load() (string, error) {
	raw, err := os.ReadFile(t.path)
	if err != nil {
		return "", err
	}
	s := strings.TrimSpace(string(raw))
	if strings.HasPrefix(s, "{") {
		var doc struct {
			APIKey string `json:"OPENAI_API_KEY"`
			Tokens struct {
				AccessToken string `json:"access_token"`
			} `json:"tokens"`
		}
		if err := json.Unmarshal([]byte(s), &doc); err != nil {
			return "", err
		}
		if doc.Tokens.AccessToken != "" {
			return doc.Tokens.AccessToken, nil
		}
		return doc.APIKey, nil
	}
	return s, nil
}

func (t *tokenSource) get() string {
	if v, ok := t.cur.Load().(string); ok && v != "" {
		return v
	}
	s, err := t.load()
	if err != nil {
		log.Printf("tokenbar-core: token load: %v", err)
		return ""
	}
	t.cur.Store(s)
	return s
}

func main() {
	port := flag.Int("port", 9417, "loopback listen port")
	upstream := flag.String("upstream", "https://chatgpt.com/backend-api/codex",
		"fixed upstream base URL (dial allowlist)")
	stripPrefix := flag.String("strip-prefix", "/v1",
		"path prefix removed before joining to the upstream base")
	tokenFile := flag.String("token-file", "", "raw bearer token or codex auth.json path")
	flag.Parse()

	if *tokenFile == "" {
		log.Fatal("tokenbar-core: -token-file is required")
	}
	up, err := url.Parse(*upstream)
	if err != nil || up.Scheme == "" || up.Host == "" {
		log.Fatalf("tokenbar-core: bad -upstream %q", *upstream)
	}

	tok := &tokenSource{path: *tokenFile}
	if tok.get() == "" {
		log.Fatalf("tokenbar-core: no token readable from %s", *tokenFile)
	}

	r := relay.New(relay.Config{
		Upstream:    up,
		StripPrefix: *stripPrefix,
		Token:       tok.get,
	})

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		fmt.Fprintln(w, `{"ok":true}`)
	})
	mux.Handle("/", r)

	addr := fmt.Sprintf("127.0.0.1:%d", *port)
	log.Printf("tokenbar-core: relay on %s -> %s", addr, up)
	log.Fatal(http.ListenAndServe(addr, mux))
}
