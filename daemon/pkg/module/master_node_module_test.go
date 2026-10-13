package module

import (
	"NodeDaemon/config"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestDisabledMonitorDoesNotQueryMissingInfluxClient(t *testing.T) {
	config.GlobalConfig.App.EnableMonitor = false
	r := gin.New()
	RegisterHandlers(r)
	for _, endpoint := range []string{"/api/resource/last/node/all", "/api/resource/last/link/all", "/api/resource/period/instance/sample"} {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, endpoint, nil))
		if w.Code != 200 || !strings.Contains(w.Body.String(), `"monitor_enabled":false`) {
			t.Fatalf("%s: %d %s", endpoint, w.Code, w.Body.String())
		}
	}
}

func TestWebRecoveryRejectsTopologyMutation(t *testing.T) {
	t.Setenv("OPENSN_WEB_ONLY", "1")
	r := gin.New()
	RegisterHandlers(r)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/api/emulation/reset", nil))
	if w.Code != http.StatusConflict {
		t.Fatalf("expected read-only recovery, got %d", w.Code)
	}
}
