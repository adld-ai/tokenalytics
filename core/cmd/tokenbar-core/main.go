// tokenbar-core is the TokenBar v2 single-writer core. M1: pool,
// routing, and the management API are live behind the M0 relay.
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"flag"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"

	"tokenbar/internal/api"
	"tokenbar/internal/pool"
	"tokenbar/internal/relay"
	"tokenbar/internal/routing"
	"tokenbar/internal/state"
)

// credSource adapts pool+routing to relay.CredentialSource.
type credSource struct {
	pool     *pool.Pool
	router   *routing.Router
	provider string
}

func (c *credSource) build(id int64) (relay.RoutedCred, error) {
	ts, err := c.pool.Tokens(id)
	if err != nil {
		return relay.RoutedCred{}, err
	}
	cred := relay.RoutedCred{AccountID: id, Token: ts.AccessToken}
	if c.provider == "codex" {
		if a, err := c.pool.Get(id); err == nil && a.AccountID != "" {
			// S17: replace the provider account-id header that pairs
			// with the token.
			cred.PairName = "ChatGPT-Account-Id"
			cred.PairValue = a.AccountID
		}
	}
	return cred, nil
}

func (c *credSource) Pick(ctx context.Context) (relay.RoutedCred, error) {
	pick, err := c.router.Pick(c.provider)
	if err != nil {
		return relay.RoutedCred{}, err
	}
	return c.build(pick.AccountID)
}

func (c *credSource) Next(ctx context.Context, prev relay.RoutedCred) (relay.RoutedCred, error) {
	pick, err := c.router.NextAfter(c.provider, prev.AccountID)
	if err != nil {
		return relay.RoutedCred{}, err
	}
	return c.build(pick.AccountID)
}

func (c *credSource) ReportHardFailure(prev relay.RoutedCred, status int) {
	c.router.Cooldown(prev.AccountID, fmt.Sprintf("upstream %d", status), 0)
}

func (c *credSource) FailoverAllowed() bool {
	ri, ok := c.router.Routes()[c.provider]
	return ok && ri.Policy == routing.PolicyFillFirst
}

func adminToken(path string) (string, error) {
	if raw, err := os.ReadFile(path); err == nil && len(raw) > 0 {
		return string(raw[:len(raw)-1]), nil // trailing newline
	}
	buf := make([]byte, 24)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	tok := hex.EncodeToString(buf)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return "", err
	}
	if err := os.WriteFile(path, []byte(tok+"\n"), 0o600); err != nil {
		return "", err
	}
	return tok, nil
}

func main() {
	port := flag.Int("port", 9417, "loopback listen port")
	upstream := flag.String("upstream", "https://chatgpt.com/backend-api/codex",
		"fixed upstream base URL (dial allowlist)")
	stripPrefix := flag.String("strip-prefix", "/v1",
		"path prefix removed before joining to the upstream base")
	provider := flag.String("provider", "codex", "provider routed on the strip-prefix surface")
	dbPath := flag.String("db", "", "v2 SQLite DB path (e.g. ~/.tokenbar/pool.db)")
	adminTokenFile := flag.String("admin-token-file", "", "management bearer token file (0600)")
	initDB := flag.Bool("init", false, "create a fresh DB at -db and exit")
	importV1 := flag.String("import-v1", "", "import a v1 pool.db and exit")
	importCliproxy := flag.String("import-cliproxy", "", "import a cliproxy auth dir and exit")
	dryRun := flag.Bool("dry-run", true, "print the identity mapping without writing")
	flag.Parse()

	if *dbPath == "" {
		log.Fatal("tokenbar-core: -db is required")
	}

	if *initDB {
		st, err := state.Init(*dbPath)
		if err != nil {
			log.Fatal(err)
		}
		st.Close()
		fmt.Println("initialized", *dbPath)
		return
	}

	st, err := state.Open(*dbPath)
	if err != nil {
		log.Fatal(err)
	}
	defer st.Close()
	p := pool.New(st, pool.PlainVault{})

	if *importV1 != "" {
		n, err := p.ImportV1DB(*importV1, *dryRun, os.Stdout)
		if err != nil {
			log.Fatal(err)
		}
		fmt.Printf("imported %d accounts (dry-run=%v)\n", n, *dryRun)
		return
	}
	if *importCliproxy != "" {
		n, err := p.ImportCliproxyDir(*importCliproxy, *dryRun, os.Stdout)
		if err != nil {
			log.Fatal(err)
		}
		fmt.Printf("imported %d accounts (dry-run=%v)\n", n, *dryRun)
		return
	}

	if *adminTokenFile == "" {
		log.Fatal("tokenbar-core: -admin-token-file is required to serve")
	}
	tok, err := adminToken(*adminTokenFile)
	if err != nil {
		log.Fatal(err)
	}

	up, err := url.Parse(*upstream)
	if err != nil || up.Scheme == "" || up.Host == "" {
		log.Fatalf("tokenbar-core: bad -upstream %q", *upstream)
	}

	r := routing.New()
	srv := api.New(p, r, tok)
	srv.RebuildRoutes()

	src := &credSource{pool: p, router: r, provider: *provider}
	mux := http.NewServeMux()
	mux.Handle("/api/", srv.Mux)
	mux.Handle("/", relay.NewRouted(up, *stripPrefix, src))

	addr := fmt.Sprintf("127.0.0.1:%d", *port)
	log.Printf("tokenbar-core: relay+api on %s -> %s (provider %s)", addr, up, *provider)
	log.Fatal(http.ListenAndServe(addr, mux))
}
