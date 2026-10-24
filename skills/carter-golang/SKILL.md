---
name: carter-golang
description: Go standards for backend services — CLI tools, REST/gRPC APIs, and network code (HTTP, TCP, UDP, QUIC, SSH). Covers layout, errors, concurrency & context, net/http hardening, API design, test-first QA, and profiling. Use when writing or reviewing Go, or on goroutine leaks, missing timeouts, unbounded reads, races, or panics.
argument-hint: "[Go code, service, or project to write/review]"
---

<objective>
Enforce Go standards for maintainable, testable, safe backend code. This skill is both a reference and an active review checklist. Bias: stdlib-first, minimal dependencies, test-first, explicit error handling, and code the next teammate can read. The lean core below covers universal standards; domain depth lives in sibling files loaded on demand via the routing table.
</objective>

<routing>

## Specialized References

This file covers core Go conventions. For depth in a specific domain, use `read_file` to load the appropriate sibling from the **same directory** as this SKILL.md before proceeding.

| File | Load when the request involves |
|------|-------------------------------|
| `networking.md` | `net/http` server/client hardening, all server timeouts, `http.Transport` pooling, graceful shutdown, TCP/UDP with `net.Conn`, deadlines, QUIC, SSH, long-polling/SSE/streaming, retries + backoff |
| `concurrency.md` | goroutines, goroutine-leak prevention, channels vs mutex vs atomic, worker pools, `errgroup` + `SetLimit`, `singleflight`, context deadline propagation, `sync` primitives, `testing/synctest` |
| `apis.md` | REST handlers, `ServeMux` (1.22) routing, middleware chains, request/JSON validation, `MaxBytesReader`, `DisallowUnknownFields`, error→HTTP status mapping, gRPC/protobuf + interceptors + streaming |
| `testing-qa.md` | test-first workflow, table tests + subtests, `t.Helper()`, fuzzing + seed corpus, `goleak`, `httptest`, parallel tests, coverage, golden files, integration tests via build tags, interface mocking |
| `performance.md` | `pprof` (cpu/mem/block/mutex), `benchstat`, `b.Loop()`, allocation reduction, `sync.Pool`, `GOGC`/`GOMEMLIMIT`, escape analysis, and when NOT to optimize |
| `errors-safety.md` | error wrapping (`%w`), sentinels, custom error types, `errors.Join`, `context.Cause`, nil/slice-aliasing/overflow safety, panic/recover boundaries, safety linters |

**How to load:** derive the directory path from this SKILL.md's location and read the sibling file. For example, if this file is at `~/.copilot/skills/carter-golang/SKILL.md`, read `~/.copilot/skills/carter-golang/networking.md`.

If the request does not match any specialized topic, use the core standards below without loading additional files.

</routing>

<standards>

## Project Structure

Standard Go layout for a backend service or CLI:
```
project/
├── cmd/appname/main.go   # Entry point — parse config, wire deps, start server. Minimal logic.
├── internal/             # Private packages; compiler forbids external import
│   ├── handler/          # transport (HTTP/gRPC) → calls service
│   ├── service/          # business logic; no transport or DB types leak here
│   └── repository/       # data access behind an interface
├── pkg/                  # genuinely reusable libraries only (most projects skip this)
├── go.mod / go.sum       # both committed
└── Makefile / README.md
```

- Keep `main.go` thin: it wires dependencies and starts the server; logic lives in `internal/`.
- Put interfaces at the **consumer** (`service` defines the `Repository` it needs), not the implementer.
- Reach for `pkg/` only when another module genuinely imports it. When in doubt, use `internal/`.

**Source:** [Effective Go](https://go.dev/doc/effective_go), [Organizing a Go module](https://go.dev/doc/modules/layout)

## Naming & Documentation

- Exported `PascalCase`, unexported `camelCase`. Initialisms stay uppercase: `HTTPServer`, `ID`, `URL` — not `HttpServer`.
- Short receiver names (`func (s *Server) Start()`), consistent per type. No `this`/`self`.
- Godoc on every exported symbol; the comment starts with the symbol's name and is a full sentence.
  ```go
  // Server routes incoming HTTP requests to their handlers.
  // The zero value is not usable; construct one with NewServer.
  type Server struct{ /* ... */ }
  ```
- Package names are short, lower-case, no underscores; avoid stutter (`http.Server`, not `http.HTTPServer`).

**Source:** [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments), [Go Doc Comments](https://go.dev/doc/comment)

## Design Idioms

- **Small interfaces (1-3 methods)** defined where used. `io.Reader` is the gold standard.
- **Constructor injection** — pass dependencies as arguments; wire explicitly in `main.go`. No DI frameworks.
- **Functional options** for constructors with many optional params (`NewServer(WithPort(8080), WithTimeout(d))`).
- **Composition via embedding**, not inheritance; embed an interface to build decorators/wrappers.
- **Accept interfaces, return concrete types.** Let callers depend on behavior, not implementations.

**Source:** [Effective Go](https://go.dev/doc/effective_go)

## Error Handling (core — see `errors-safety.md` for depth)

- Wrap with context using `%w` so callers can `errors.Is`/`errors.As`: `fmt.Errorf("fetch user %s: %w", id, err)`.
- Sentinels (`var ErrNotFound = errors.New("not found")`) and custom error types for structured cases.
- Check errors immediately; never discard with `_`. Do **not** both log *and* return the same error.
- Don't `panic` in library code — return an error. Reserve panic for truly unrecoverable programmer bugs.

## Concurrency & Context (core — see `concurrency.md` for depth)

- `context.Context` is the **first** parameter of any function that does I/O or may be cancelled.
- **Every goroutine must have a guaranteed exit** — bound it by `ctx.Done()`, a done channel, or a `WaitGroup`.
- Channels for handing off ownership of data; mutex/atomic for protecting shared state. Pick one per datum.
- Use `errgroup` (with `SetLimit` for bounded fan-out) for parallel work with error propagation.
- Run tests with `-race`. Zero tolerance for data races.

## Networking, APIs & Performance (see sibling files)

- **Never** use `http.DefaultClient`/`http.DefaultServeMux` in production. Construct an `http.Server` with
  `ReadHeaderTimeout`, `ReadTimeout`, `WriteTimeout`, and `IdleTimeout` set; give clients an explicit `Transport`.
- Implement **graceful shutdown**: trap `SIGINT`/`SIGTERM` and call `Server.Shutdown(ctx)`.
- Validate all input at the boundary; cap request bodies with `http.MaxBytesReader`; map errors to HTTP status.
- Profile before optimizing — `pprof` + `benchstat` prove a hotspot before you spend effort on it.

## Tooling & Dependencies

- `gofmt`/`goimports` are non-negotiable. Lint with `golangci-lint` (`errcheck`, `govet`, `staticcheck`, `gosec`, `ineffassign`, `unused`, `gocritic`).
- Scan with `govulncheck` (known CVEs) and `gosec` (security smells) in CI.
- Use `go mod`; commit `go.mod` and `go.sum`. Target a supported toolchain in `go.mod` (`go 1.26` or newer — Go supports the two latest majors; 1.27 is current as of 2026-10). Prefer stdlib; add a dependency only when it clearly beats it.
- Modern Go you should reach for: `slog` structured logging, `min`/`max`/`clear` (1.21), `ServeMux` method+wildcard routing (1.22), iterators (1.23), `b.Loop` (1.24), `testing/synctest` (1.25).

**Source:** [Go Modules Reference](https://go.dev/ref/mod), [govulncheck](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck)

</standards>

<checklist>

## Enforcement Checklist

Verify each item when writing or reviewing Go:

**Structure & style**
- [ ] Standard layout (`cmd/`, `internal/`); `main.go` is thin
- [ ] `go.mod` and `go.sum` committed; dependencies minimal
- [ ] `gofmt`/`goimports`, `golangci-lint`, `gosec`, `govulncheck` all pass
- [ ] Godoc on exported symbols; interfaces small and defined where used

**Errors & safety**
- [ ] Every error checked and wrapped with `%w`; no `_`-discarded errors
- [ ] No `panic` in library code; panics recovered at goroutine boundaries
- [ ] Nil, slice-aliasing, and integer-overflow hazards considered

**Concurrency**
- [ ] `context.Context` propagated through all I/O functions
- [ ] Every goroutine has a guaranteed exit; no leaks
- [ ] Tests pass with `-race`

**Networking**
- [ ] `http.Server` sets `ReadHeaderTimeout`/`ReadTimeout`/`WriteTimeout`/`IdleTimeout`
- [ ] HTTP clients use an explicit `Transport` with a timeout; no `http.DefaultClient`
- [ ] Graceful shutdown via signal handling + `Server.Shutdown(ctx)`
- [ ] Connection deadlines set on raw `net.Conn` I/O

**APIs**
- [ ] Input validated at the boundary; request bodies capped (`MaxBytesReader`)
- [ ] JSON decoded with `DisallowUnknownFields` where strictness matters
- [ ] Errors mapped to correct HTTP status codes / gRPC codes

**QA & performance**
- [ ] Test-first; table-driven tests with subtests and `t.Helper()`
- [ ] Fuzzing on parsers/boundaries; `goleak` guards goroutine leaks
- [ ] Hotspots proven with `pprof`/`benchstat` before optimizing

</checklist>
