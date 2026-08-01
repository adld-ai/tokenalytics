package auth

import (
	"encoding/base64"
	"encoding/json"
	"strings"
)

// DecodeJWTPayload decodes a JWT payload without verifying the
// signature — the token came straight from the provider over TLS, so
// v1 treats claims as identity metadata, not proof.
func DecodeJWTPayload(tok string) (map[string]any, error) {
	parts := strings.Split(tok, ".")
	if len(parts) != 3 {
		return nil, errBadJWT
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return nil, err
	}
	var out map[string]any
	return out, json.Unmarshal(raw, &out)
}

var errBadJWT = errString("auth: not a JWT")

type errString string

func (e errString) Error() string { return string(e) }
