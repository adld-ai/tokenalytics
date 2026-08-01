// Package pool owns account records and credentials (spec 5.2). All
// mutation is serialized through the state store's single writer, so
// the v1 race class (delete-resurrection, FK-after-delete,
// stale-list rewrite) is impossible by construction.
package pool

import (
	"database/sql"
	"errors"
	"fmt"
	"time"

	"tokenbar/internal/state"
)

// Account is one provider credential identity. Identity is keyed on
// the upstream account id (AccountID), never email (R16).
type Account struct {
	ID        int64
	Provider  string
	Email     string
	Label     string
	Plan      string
	AccountID string
	Disabled  bool
	CreatedAt float64
	UpdatedAt float64
}

// TokenSet is one account's credential material.
type TokenSet struct {
	AccessToken  string
	RefreshToken string
	IDToken      string
	ExpiresAt    float64
	LastRefresh  float64
	RawJSON      string
}

// Vault isolates token storage so M2's keychain backend is a drop-in
// (S16). Callers never touch token bytes directly.
type Vault interface {
	// Seal stores the tokens and returns a reference kept in the DB.
	Seal(ts TokenSet) (ref string, err error)
	// Open resolves a reference back to the tokens.
	Open(ref string) (TokenSet, error)
}

// PlainVault is the M1 transitional vault: tokens stay in the tokens
// table and the reference is the literal marker "db". M2 swaps in a
// keychain vault that re-seals every row.
type PlainVault struct{ st *state.Store }

func (v PlainVault) Seal(ts TokenSet) (string, error) { return "db", nil }

func (v PlainVault) Open(ref string) (TokenSet, error) {
	if ref != "db" {
		return TokenSet{}, fmt.Errorf("pool: unknown vault ref %q", ref)
	}
	return TokenSet{}, errors.New("pool: PlainVault reads go through Pool.Tokens")
}

// Pool is the account CRUD surface.
type Pool struct {
	st    *state.Store
	vault Vault
}

func New(st *state.Store, vault Vault) *Pool {
	return &Pool{st: st, vault: vault}
}

var ErrNotFound = errors.New("pool: account not found")

func now() float64 { return float64(time.Now().Unix()) }

// Add inserts an account plus its tokens in one transaction.
func (p *Pool) Add(a Account, ts TokenSet) (int64, error) {
	ref, err := p.vault.Seal(ts)
	if err != nil {
		return 0, err
	}
	var id int64
	err = p.st.Submit(func(tx *sql.Tx) error {
		res, err := tx.Exec(
			`INSERT INTO accounts(provider, email, label, plan, account_id, created_at, updated_at)
			 VALUES(?,?,?,?,?,?,?)`,
			a.Provider, a.Email, a.Label, a.Plan, a.AccountID, now(), now())
		if err != nil {
			return err
		}
		id, err = res.LastInsertId()
		if err != nil {
			return err
		}
		_, err = tx.Exec(
			`INSERT INTO tokens(account_id, vault_ref, access_token, refresh_token, id_token,
			 expires_at, last_refresh, raw_json) VALUES(?,?,?,?,?,?,?,?)`,
			id, ref, ts.AccessToken, ts.RefreshToken, ts.IDToken,
			ts.ExpiresAt, ts.LastRefresh, ts.RawJSON)
		return err
	})
	return id, err
}

// Remove deletes an account; dependent rows cascade in the same
// transaction. A delete cannot race anything: it is one op on the
// single-writer queue.
func (p *Pool) Remove(id int64) error {
	return p.st.Submit(func(tx *sql.Tx) error {
		res, err := tx.Exec("DELETE FROM accounts WHERE id = ?", id)
		if err != nil {
			return err
		}
		n, _ := res.RowsAffected()
		if n == 0 {
			return ErrNotFound
		}
		return nil
	})
}

func scanAccounts(rows *sql.Rows) ([]Account, error) {
	var out []Account
	for rows.Next() {
		var a Account
		var email, label, plan, acct sql.NullString
		var disabled int
		if err := rows.Scan(&a.ID, &a.Provider, &email, &label, &plan, &acct,
			&disabled, &a.CreatedAt, &a.UpdatedAt); err != nil {
			return nil, err
		}
		a.Email, a.Label, a.Plan, a.AccountID = email.String, label.String, plan.String, acct.String
		a.Disabled = disabled != 0
		out = append(out, a)
	}
	return out, rows.Err()
}

// List returns a point-in-time snapshot. It is read-only; no caller
// can write a stale list back (the v1 rewrite race has no API).
func (p *Pool) List() ([]Account, error) {
	rows, err := p.st.Query(
		"SELECT id, provider, email, label, plan, account_id, disabled, created_at, updated_at FROM accounts ORDER BY id")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanAccounts(rows)
}

func (p *Pool) Get(id int64) (Account, error) {
	rows, err := p.st.Query(
		"SELECT id, provider, email, label, plan, account_id, disabled, created_at, updated_at FROM accounts WHERE id = ?", id)
	if err != nil {
		return Account{}, err
	}
	defer rows.Close()
	accts, err := scanAccounts(rows)
	if err != nil {
		return Account{}, err
	}
	if len(accts) == 0 {
		return Account{}, ErrNotFound
	}
	return accts[0], nil
}

func (p *Pool) SetDisabled(id int64, disabled bool) error {
	return p.st.Submit(func(tx *sql.Tx) error {
		res, err := tx.Exec("UPDATE accounts SET disabled = ?, updated_at = ? WHERE id = ?",
			boolToInt(disabled), now(), id)
		if err != nil {
			return err
		}
		if n, _ := res.RowsAffected(); n == 0 {
			return ErrNotFound
		}
		return nil
	})
}

// Tokens resolves an account's credentials through the vault. Rows
// sealed into an external vault hold no plaintext columns; the vault
// is the only read path (S16).
func (p *Pool) Tokens(id int64) (TokenSet, error) {
	rows, err := p.st.Query(
		"SELECT vault_ref, access_token, refresh_token, id_token, expires_at, last_refresh, raw_json FROM tokens WHERE account_id = ?", id)
	if err != nil {
		return TokenSet{}, err
	}
	defer rows.Close()
	if !rows.Next() {
		return TokenSet{}, ErrNotFound
	}
	var ref string
	var at, rt, it, raw sql.NullString
	var exp, lr sql.NullFloat64
	if err := rows.Scan(&ref, &at, &rt, &it, &exp, &lr, &raw); err != nil {
		return TokenSet{}, err
	}
	if ref != "db" {
		ts, err := p.vault.Open(ref)
		if err != nil {
			return TokenSet{}, err
		}
		ts.ExpiresAt, ts.LastRefresh, ts.RawJSON = exp.Float64, lr.Float64, raw.String
		return ts, nil
	}
	var ts TokenSet
	ts.AccessToken, ts.RefreshToken, ts.IDToken = at.String, rt.String, it.String
	ts.ExpiresAt, ts.LastRefresh, ts.RawJSON = exp.Float64, lr.Float64, raw.String
	return ts, nil
}

// UpdateTokens re-seals an account's tokens (refresh-on-use writes
// through here).
func (p *Pool) UpdateTokens(id int64, ts TokenSet) error {
	ref, err := p.vault.Seal(ts)
	if err != nil {
		return err
	}
	return p.st.Submit(func(tx *sql.Tx) error {
		// After the keychain migration the plaintext columns stay
		// cleared; before it (M1 plain vault) they carry the tokens.
		at, rt, it := ts.AccessToken, ts.RefreshToken, ts.IDToken
		if ref != "db" {
			at, rt, it = "", "", ""
		}
		res, err := tx.Exec(
			`UPDATE tokens SET vault_ref=?, access_token=?, refresh_token=?, id_token=?,
			 expires_at=?, last_refresh=?, raw_json=? WHERE account_id=?`,
			ref, at, rt, it, ts.ExpiresAt, ts.LastRefresh, ts.RawJSON, id)
		if err != nil {
			return err
		}
		if n, _ := res.RowsAffected(); n == 0 {
			return ErrNotFound
		}
		return nil
	})
}

// MigrateToVault re-seals every plaintext token row into v and clears
// the plaintext columns (S16). Returns the number of rows migrated.
func (p *Pool) MigrateToVault(v Vault) (int, error) {
	rows, err := p.st.Query(
		"SELECT account_id, access_token, refresh_token, id_token, expires_at, last_refresh, raw_json FROM tokens WHERE vault_ref = 'db'")
	if err != nil {
		return 0, err
	}
	type row struct {
		id int64
		ts TokenSet
	}
	var pending []row
	for rows.Next() {
		var r row
		var at, rt, it, raw sql.NullString
		if err := rows.Scan(&r.id, &at, &rt, &it, &r.ts.ExpiresAt, &r.ts.LastRefresh, &raw); err != nil {
			rows.Close()
			return 0, err
		}
		r.ts.AccessToken, r.ts.RefreshToken, r.ts.IDToken = at.String, rt.String, it.String
		r.ts.RawJSON = raw.String
		pending = append(pending, r)
	}
	rows.Close()

	old := p.vault
	p.vault = v
	migrated := 0
	for _, r := range pending {
		if err := p.UpdateTokens(r.id, r.ts); err != nil {
			p.vault = old
			return migrated, fmt.Errorf("pool: migrate account %d: %w", r.id, err)
		}
		migrated++
	}
	return migrated, nil
}

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
}
