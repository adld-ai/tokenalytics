package routing

import (
	"os/exec"
	"strings"
	"testing"
)

// TestRoutingNeverReadsQuotaModel enforces the S4/13.3 package
// boundary: modeled quota is display-only; routing reacts only to
// real upstream signals.
func TestRoutingNeverReadsQuotaModel(t *testing.T) {
	out, err := exec.Command("go", "list", "-f", `{{join .Deps "\n"}}`, "tokenbar/internal/routing").Output()
	if err != nil {
		t.Fatalf("go list: %v", err)
	}
	for _, banned := range []string{"tokenbar/internal/quota", "tokenbar/internal/harvest"} {
		if strings.Contains(string(out), banned) {
			t.Fatalf("S4 violation: routing depends on %s", banned)
		}
	}
}
