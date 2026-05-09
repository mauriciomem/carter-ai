---
name: carter-golang
description: Go coding standards, best practices, and enforcement checklist
argument-hint: "[Go code or project to review]"
---

<objective>
Enforce Go coding standards focused on maintainability, extensibility, testability, and security. This skill serves as both a reference guide and an active checklist for code review.
</objective>

<standards>

## Project Structure

Follow the standard Go project layout:
```
project/
├── cmd/
│   └── appname/
│       └── main.go         # Entry point, minimal logic
├── internal/               # Private packages (not importable externally)
│   ├── handler/
│   ├── service/
│   └── repository/
├── pkg/                    # Public reusable packages (use sparingly)
├── go.mod
├── go.sum
├── Makefile
└── README.md
```

- `cmd/` — Entry points. Each subdirectory is a binary. Keep `main.go` minimal (wire dependencies, start server).
- `internal/` — Business logic. The Go compiler enforces that these packages can't be imported by other modules.
- `pkg/` — Only for genuinely reusable libraries. Most projects don't need this.

**Source:** [Standard Go Project Layout](https://github.com/golang-standards/project-layout), [Effective Go](https://go.dev/doc/effective_go)

## Design Patterns

### Interfaces Are Contracts
```go
// Define interfaces where they are USED, not where they are implemented.
type UserRepository interface {
    Get(ctx context.Context, id string) (*User, error)
    Save(ctx context.Context, user *User) error
}
```
Keep interfaces small (1-3 methods). The Go standard library's `io.Reader` (1 method) is the gold standard.

### Functional Options
```go
type Option func(*Server)

func WithPort(port int) Option {
    return func(s *Server) { s.port = port }
}

func WithTimeout(d time.Duration) Option {
    return func(s *Server) { s.timeout = d }
}

func NewServer(opts ...Option) *Server {
    s := &Server{port: 8080, timeout: 30 * time.Second}
    for _, opt := range opts {
        opt(s)
    }
    return s
}
```
Use functional options for constructors with many optional parameters.

### Dependency Injection
```go
// Pass dependencies as constructor arguments.
func NewOrderService(repo OrderRepository, notifier Notifier) *OrderService {
    return &OrderService{repo: repo, notifier: notifier}
}
```
No DI frameworks — Go's explicit wiring in `main.go` is the convention.

### Embedding for Composition
```go
type LoggingRepository struct {
    inner Repository
    log   *slog.Logger
}
```
Use struct embedding for composition, not inheritance. Embed interfaces in structs to implement decorator/wrapper patterns.

**Source:** [Effective Go](https://go.dev/doc/effective_go), [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments)

## Error Handling

### Wrap Errors with Context
```go
if err != nil {
    return fmt.Errorf("failed to fetch user %s: %w", id, err)
}
```
Always use `%w` to wrap errors so callers can use `errors.Is()` and `errors.As()`.

### Sentinel Errors
```go
var (
    ErrNotFound     = errors.New("not found")
    ErrUnauthorized = errors.New("unauthorized")
)
```

### Custom Error Types
```go
type ValidationError struct {
    Field   string
    Message string
}

func (e *ValidationError) Error() string {
    return fmt.Sprintf("validation failed on %s: %s", e.Field, e.Message)
}
```

### Rules
- Check errors immediately. Never ignore with `_`.
- Wrap with context at each level.
- Don't log AND return an error — do one or the other.
- Use `errors.Is()` and `errors.As()` for error inspection.
- Don't panic in library code. Reserve `panic` for truly unrecoverable situations.

**Source:** [Go Blog — Error handling](https://go.dev/blog/go1.13-errors), [Go Proverbs](https://go-proverbs.github.io/)

## Testing

- **Framework:** Built-in `testing` package.
- **Table-driven tests:**
  ```go
  func TestAdd(t *testing.T) {
      tests := []struct {
          name     string
          a, b     int
          expected int
      }{
          {"positive", 1, 2, 3},
          {"zero", 0, 0, 0},
          {"negative", -1, 1, 0},
      }
      for _, tt := range tests {
          t.Run(tt.name, func(t *testing.T) {
              got := Add(tt.a, tt.b)
              assert.Equal(t, tt.expected, got)
          })
      }
  }
  ```
- **Test helpers:** Use `t.Helper()` in helper functions so failure locations are correct.
- **Mocking:** Define interfaces, create mock implementations. Use `testify/mock` or hand-written mocks.
- **Subtests:** Use `t.Run()` for test organization and selective execution.
- **Benchmarks:** Use `func BenchmarkX(b *testing.B)` for performance-critical code.

**Source:** [Go testing docs](https://pkg.go.dev/testing), [testify](https://github.com/stretchr/testify)

## Security

- **Input validation:** Validate at API boundaries. Use struct tags with a validation library or manual checks.
- **Secrets:** Never hardcode. Use environment variables or secret managers.
- **Dependencies:** Scan with `govulncheck` regularly.
- **Static analysis:** Run `gosec` for security-focused linting.
- **SQL injection:** Use parameterized queries (`db.Query("SELECT ... WHERE id = $1", id)`).
- **Path traversal:** Use `filepath.Clean()` and validate paths.
- **HTTP:** Set timeouts on all HTTP clients and servers. Never use `http.DefaultClient` in production.
  ```go
  client := &http.Client{Timeout: 10 * time.Second}
  ```

**Source:** [OWASP Go Security](https://cheatsheetseries.owasp.org/cheatsheets/Go_Security_Cheat_Sheet.html), [gosec](https://github.com/securego/gosec)

## Code Quality

- **Formatting:** `gofmt` / `goimports` — non-negotiable, enforced by tooling.
- **Linting:** `golangci-lint` with a curated set of linters:
  ```yaml
  # .golangci.yml
  linters:
    enable:
      - errcheck
      - govet
      - staticcheck
      - gosec
      - ineffassign
      - unused
      - gocritic
  ```
- **Naming:** Follow Go conventions:
  - Exported: `PascalCase`
  - Unexported: `camelCase`
  - Acronyms: `HTTPServer`, not `HttpServer`
  - Single-letter receivers for simple types: `func (s *Server) Start()`
- **Documentation:** Godoc comments on all exported types and functions:
  ```go
  // Server handles incoming HTTP requests and routes them
  // to the appropriate handler.
  type Server struct { ... }
  ```

**Source:** [Effective Go](https://go.dev/doc/effective_go), [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments)

## Concurrency

- **Context propagation:** Pass `context.Context` as the first parameter to all functions that do I/O or may be cancelled.
  ```go
  func (s *Service) GetUser(ctx context.Context, id string) (*User, error)
  ```
- **Goroutines:** Always ensure goroutines can be stopped (via context, done channel, or WaitGroup).
- **Channels:** Prefer channels for communication, mutexes for state protection.
- **sync package:** Use `sync.Mutex`, `sync.RWMutex`, `sync.WaitGroup`, `sync.Once` appropriately.
- **errgroup:** Use `golang.org/x/sync/errgroup` for parallel tasks with error propagation.
- **Data races:** Run tests with `-race` flag. Zero tolerance for data races.

**Source:** [Go Concurrency Patterns](https://go.dev/blog/pipelines), [errgroup docs](https://pkg.go.dev/golang.org/x/sync/errgroup)

## Dependency Management

- **Go modules:** Always use `go mod`. Commit both `go.mod` and `go.sum`.
- **Minimal dependencies:** Go's standard library is extensive. Check if stdlib covers your need before adding a dependency.
- **Version updates:** Use `go get -u` carefully. Review changelogs.
- **Vendoring:** Use `go mod vendor` if reproducibility is critical or for air-gapped builds.

**Source:** [Go Modules Reference](https://go.dev/ref/mod)

</standards>

<checklist>

## Enforcement Checklist

When reviewing Go code, verify each item:

- [ ] Project follows standard layout (`cmd/`, `internal/`)
- [ ] `go.mod` and `go.sum` committed
- [ ] `gofmt` / `goimports` passes
- [ ] `golangci-lint` passes
- [ ] `gosec` passes (no security findings)
- [ ] `govulncheck` passes (no known vulnerabilities)
- [ ] All errors checked and wrapped with context (`%w`)
- [ ] Interfaces defined where used, not where implemented
- [ ] Interfaces are small (1-3 methods)
- [ ] Context propagated through all I/O functions
- [ ] Tests exist with table-driven pattern
- [ ] Tests pass with `-race` flag
- [ ] No hardcoded secrets
- [ ] HTTP clients have explicit timeouts
- [ ] Godoc comments on exported types and functions
- [ ] Dependencies are minimal

</checklist>
