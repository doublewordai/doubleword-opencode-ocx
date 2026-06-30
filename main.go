// Minimal static server for the Doubleword ocx registry.
// Serves the built `dist/` (embedded into the binary) so `ocx registry add`
// can pull it from http://localhost:PORT. No dependencies — stdlib only.
package main

import (
	"embed"
	"io/fs"
	"log"
	"net/http"
	"os"
)

//go:embed all:dist
var dist embed.FS

func main() {
	sub, err := fs.Sub(dist, "dist")
	if err != nil {
		log.Fatalf("embed dist: %v", err)
	}

	port := os.Getenv("PORT")
	if port == "" {
		port = "8077"
	}

	mux := http.NewServeMux()
	mux.Handle("/", http.FileServer(http.FS(sub)))

	log.Printf("Doubleword ocx registry serving on :%s", port)
	log.Printf("Install with:  ocx registry add http://localhost:%s --name dw --global && ocx add dw/doubleword --global", port)
	if err := http.ListenAndServe(":"+port, logRequests(mux)); err != nil {
		log.Fatal(err)
	}
}

func logRequests(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		log.Printf("%s %s", r.Method, r.URL.Path)
		h.ServeHTTP(w, r)
	})
}
