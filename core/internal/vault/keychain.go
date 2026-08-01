// Package vault implements the pool.Vault interface against macOS
// Keychain via /usr/bin/security (cgo-free, S16). The DB stores only
// references; token bytes live in the login keychain.
package vault

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os/exec"
	"strings"

	"tokenbar/internal/pool"
)

const securityBin = "/usr/bin/security"

// Keychain stores TokenSets as generic-password items.
type Keychain struct {
	Service string // keychain service name, e.g. "com.tonye.tokenbar"
}

// NewKeychain returns a Keychain vault with the production service.
func NewKeychain() *Keychain { return &Keychain{Service: "com.tonye.tokenbar"} }

func (k *Keychain) run(args ...string) (string, error) {
	cmd := exec.Command(securityBin, args...)
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("vault: security %s: %v: %s", args[0], err, strings.TrimSpace(errb.String()))
	}
	return strings.TrimRight(out.String(), "\n"), nil
}

// Seal stores the tokens in the keychain and returns the item ref.
func (k *Keychain) Seal(ts pool.TokenSet) (string, error) {
	raw, err := json.Marshal(ts)
	if err != nil {
		return "", err
	}
	ref := fmt.Sprintf("tok-%d", timeNowNano())
	if _, err := k.run("add-generic-password", "-s", k.Service, "-a", ref, "-w", string(raw), "-U"); err != nil {
		return "", err
	}
	return "keychain:" + ref, nil
}

// Open resolves a keychain ref back to the tokens.
func (k *Keychain) Open(ref string) (pool.TokenSet, error) {
	item, ok := strings.CutPrefix(ref, "keychain:")
	if !ok {
		return pool.TokenSet{}, fmt.Errorf("vault: not a keychain ref %q", ref)
	}
	out, err := k.run("find-generic-password", "-s", k.Service, "-a", item, "-w")
	if err != nil {
		return pool.TokenSet{}, err
	}
	var ts pool.TokenSet
	if err := json.Unmarshal([]byte(out), &ts); err != nil {
		return pool.TokenSet{}, fmt.Errorf("vault: decode %q: %w", ref, err)
	}
	return ts, nil
}

// Delete removes a sealed item (account removal).
func (k *Keychain) Delete(ref string) error {
	item, ok := strings.CutPrefix(ref, "keychain:")
	if !ok {
		return nil
	}
	_, err := k.run("delete-generic-password", "-s", k.Service, "-a", item)
	return err
}
