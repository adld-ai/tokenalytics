// soak replays recorded codex request shapes against a running
// tokenbar-core relay: streaming, non-streaming, and abort-mid-stream.
// It can also host a mock upstream so the harness is self-contained:
//
//	soak -mock :19417 &                 # mock provider
//	tokenbar-core -upstream http://127.0.0.1:19417 -strip-prefix /v1 -token-file ...
//	soak -relay http://127.0.0.1:9417 -n 100
package main

import (
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"time"
)

var chunks = []string{
	": keepalive\n\n",
	"event: response.created\ndata: {\"type\":\"response.created\"}\n\n",
	"event: response.output_text.delta\ndata: {\"delta\":\"Hello\"}\n\n",
	"event: response.completed\ndata: {\"type\":\"response.completed\"}\n\n",
}

func startMock(addr string) *httptest.Server {
	return httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body)
		r.Body.Close()
		if r.URL.Query().Get("stream") == "false" {
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprint(w, `{"id":"resp_x","status":"completed"}`)
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		f, _ := w.(http.Flusher)
		for _, c := range chunks {
			fmt.Fprint(w, c)
			if f != nil {
				f.Flush()
			}
			time.Sleep(5 * time.Millisecond)
		}
	}))
}

func main() {
	mock := flag.String("mock", "", "host a mock upstream on this addr and block")
	relay := flag.String("relay", "http://127.0.0.1:9417", "relay base URL")
	n := flag.Int("n", 100, "sequential streams")
	flag.Parse()

	if *mock != "" {
		srv := startMock(*mock)
		l := srv.Listener
		fmt.Println("mock upstream on", l.Addr())
		srv.Start()
		select {}
	}

	client := &http.Client{Timeout: 30 * time.Second}
	var bytesTotal int64
	start := time.Now()
	for i := 0; i < *n; i++ {
		switch i % 3 {
		case 0: // streaming
			req, _ := http.NewRequest("POST", *relay+"/v1/responses?stream=true",
				strings.NewReader(`{"model":"gpt-5","stream":true}`))
			resp, err := client.Do(req)
			if err != nil {
				fmt.Printf("iter %d: %v\n", i, err)
				continue
			}
			b, _ := io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
			bytesTotal += b
		case 1: // non-streaming
			req, _ := http.NewRequest("POST", *relay+"/v1/responses?stream=false",
				strings.NewReader(`{"model":"gpt-5"}`))
			resp, err := client.Do(req)
			if err != nil {
				fmt.Printf("iter %d: %v\n", i, err)
				continue
			}
			b, _ := io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
			bytesTotal += b
		case 2: // abort mid-stream
			req, _ := http.NewRequest("POST", *relay+"/v1/responses?stream=true",
				strings.NewReader(`{"model":"gpt-5","stream":true}`))
			resp, err := client.Do(req)
			if err != nil {
				fmt.Printf("iter %d: %v\n", i, err)
				continue
			}
			buf := make([]byte, 16)
			resp.Body.Read(buf)
			resp.Body.Close()
		}
	}
	fmt.Printf("soak: %d iterations, %d bytes relayed, %s wall\n",
		*n, bytesTotal, time.Since(start).Round(time.Millisecond))
}
