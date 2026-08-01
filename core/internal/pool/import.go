// Importers migrate v1 credential stores into the pool. Both are
// dry-run by default and print the identity mapping; identity is
// keyed on the upstream account id, never email (R16).
package pool

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	_ "modernc.org/sqlite"
)

// Mapping is one row of the import preview/result.
type Mapping struct {
	Provider   string
	Email      string
	UpstreamID string // identity key
	Plan       string
	Label      string
	Action     string // "import" | "skip-duplicate" | "skip-no-identity"
	Tokens     TokenSet
}

func (p *Pool) existingIdentities() (map[string]bool, error) {
	seen := map[string]bool{}
	accts, err := p.List()
	if err != nil {
		return nil, err
	}
	for _, a := range accts {
		if a.AccountID != "" {
			seen[a.Provider+"|"+a.AccountID] = true
		}
	}
	return seen, nil
}

func (p *Pool) apply(mappings []Mapping, dryRun bool, w io.Writer) (imported int, err error) {
	sort.Slice(mappings, func(i, j int) bool {
		if mappings[i].Provider != mappings[j].Provider {
			return mappings[i].Provider < mappings[j].Provider
		}
		return mappings[i].UpstreamID < mappings[j].UpstreamID
	})
	fmt.Fprintf(w, "%-12s %-34s %-38s %-8s %s\n", "provider", "email", "upstream-account-id", "plan", "action")
	for _, m := range mappings {
		fmt.Fprintf(w, "%-12s %-34s %-38s %-8s %s\n", m.Provider, m.Email, m.UpstreamID, m.Plan, m.Action)
		if dryRun || m.Action != "import" {
			continue
		}
		_, err := p.Add(Account{
			Provider: m.Provider, Email: m.Email, Label: m.Label,
			Plan: m.Plan, AccountID: m.UpstreamID,
		}, m.Tokens)
		if err != nil {
			return imported, fmt.Errorf("pool: import %s/%s: %w", m.Provider, m.Email, err)
		}
		imported++
	}
	return imported, nil
}

// ImportV1DB reads a v1 pool.db (read-only) and imports its accounts.
func (p *Pool) ImportV1DB(path string, dryRun bool, w io.Writer) (int, error) {
	db, err := sql.Open("sqlite", "file:"+path+"?mode=ro&_pragma=busy_timeout(5000)")
	if err != nil {
		return 0, err
	}
	defer db.Close()

	seen, err := p.existingIdentities()
	if err != nil {
		return 0, err
	}

	rows, err := db.Query(`
		SELECT a.provider, a.email, COALESCE(a.plan,''), COALESCE(a.account_id,''), COALESCE(a.label,''),
		       COALESCE(t.access_token,''), COALESCE(t.refresh_token,''), COALESCE(t.id_token,''),
		       COALESCE(t.expires_at,0), COALESCE(t.last_refresh,0), COALESCE(t.raw_json,'')
		FROM accounts a LEFT JOIN tokens t ON t.account_id = a.id
		WHERE a.disabled = 0`)
	if err != nil {
		return 0, fmt.Errorf("pool: read v1 db: %w", err)
	}
	defer rows.Close()

	var ms []Mapping
	for rows.Next() {
		var m Mapping
		var ts TokenSet
		if err := rows.Scan(&m.Provider, &m.Email, &m.Plan, &m.UpstreamID, &m.Label,
			&ts.AccessToken, &ts.RefreshToken, &ts.IDToken,
			&ts.ExpiresAt, &ts.LastRefresh, &ts.RawJSON); err != nil {
			return 0, err
		}
		m.Tokens = ts
		switch {
		case m.UpstreamID == "":
			m.Action = "skip-no-identity"
		case seen[m.Provider+"|"+m.UpstreamID]:
			m.Action = "skip-duplicate"
		default:
			m.Action = "import"
		}
		ms = append(ms, m)
	}
	return p.apply(ms, dryRun, w)
}

// cliproxyDoc is the ~/.cli-proxy-api/*.json shape.
type cliproxyDoc struct {
	Type         string `json:"type"`
	Email        string `json:"email"`
	AccountID    string `json:"account_id"`
	Disabled     bool   `json:"disabled"`
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	IDToken      string `json:"id_token"`
	Expired      string `json:"expired"`
	LastRefresh  string `json:"last_refresh"`
	APIKey       string `json:"api_key"`
}

// ImportCliproxyDir imports ~/.cli-proxy-api/*.json credentials.
func (p *Pool) ImportCliproxyDir(dir string, dryRun bool, w io.Writer) (int, error) {
	files, err := filepath.Glob(filepath.Join(dir, "*.json"))
	if err != nil {
		return 0, err
	}
	seen, err := p.existingIdentities()
	if err != nil {
		return 0, err
	}
	var ms []Mapping
	for _, f := range files {
		raw, err := os.ReadFile(f)
		if err != nil {
			return 0, err
		}
		var doc cliproxyDoc
		if err := json.Unmarshal(raw, &doc); err != nil {
			fmt.Fprintf(w, "skip %s: %v\n", filepath.Base(f), err)
			continue
		}
		if doc.Disabled {
			continue
		}
		m := Mapping{
			Provider:   doc.Type,
			Email:      doc.Email,
			UpstreamID: doc.AccountID,
			Label:      strings.TrimSuffix(filepath.Base(f), ".json"),
			Tokens: TokenSet{
				AccessToken:  doc.AccessToken,
				RefreshToken: doc.RefreshToken,
				IDToken:      doc.IDToken,
				RawJSON:      string(raw),
			},
		}
		if m.UpstreamID == "" {
			// API-key providers have no upstream id; the email/login is
			// the only identity available. Keyed import still avoids
			// email-based routing: the account row keeps account_id
			// empty and routing uses the row id.
			if doc.APIKey != "" {
				m.Action = "import"
				m.Tokens.AccessToken = doc.APIKey
			} else {
				m.Action = "skip-no-identity"
			}
		} else if seen[m.Provider+"|"+m.UpstreamID] {
			m.Action = "skip-duplicate"
		} else {
			m.Action = "import"
		}
		ms = append(ms, m)
	}
	return p.apply(ms, dryRun, w)
}
