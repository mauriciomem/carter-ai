# Go Testing & QA

Read this when the work involves writing tests, choosing a testing strategy, fuzzing, guarding goroutine leaks, testing HTTP handlers, running tests in parallel, measuring coverage, golden/snapshot files, or integration tests. Carter's stance: **test-first** — the test is the executable spec you write before the implementation, and it must fail for the right reason before it passes.

## Test-first workflow

1. Write the test that describes the behavior you want. Name it as a spec: `TestParse_RejectsTrailingComma`.
2. Run it — confirm it **fails** (and fails because the behavior is missing, not because it won't compile).
3. Write the minimal implementation to make it pass.
4. Refactor with the test as your safety net.

The test name is documentation: `Test<Unit>_<Condition>_<ExpectedOutcome>`. A reader should understand the contract from the test names alone.

## Table-driven tests + subtests

The default shape for Go tests. Each case is a row; `t.Run` gives each a name and lets you run one in isolation.

```go
func TestValidateEmail(t *testing.T) {
    tests := []struct {
        name    string
        input   string
        wantErr bool
    }{
        {"valid", "a@b.com", false},
        {"missing at", "ab.com", true},
        {"empty", "", true},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            err := ValidateEmail(tt.input)
            if (err != nil) != tt.wantErr {
                t.Errorf("ValidateEmail(%q) error = %v, wantErr = %v", tt.input, err, tt.wantErr)
            }
        })
    }
}
```

- With Go 1.22+ loopvar, no `tt := tt` copy is needed — each iteration binds a fresh `tt`.
- Use `t.Helper()` in assertion/setup helpers so failures report the **caller's** line, not the helper's.
- Prefer stdlib `testing` for assertions in this repo's style; `testify` is acceptable but keep dependencies minimal and consistent within a project. `google/go-cmp`'s `cmp.Diff` is the best way to compare structs (readable diffs, `cmpopts` for tolerances).

```go
if diff := cmp.Diff(want, got); diff != "" {
    t.Errorf("mismatch (-want +got):\n%s", diff)
}
```

## Parallel tests

Mark independent tests `t.Parallel()` to shrink wall-clock time and surface hidden shared-state races.

```go
func TestThing(t *testing.T) {
    t.Parallel()
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            t.Parallel() // subtests run concurrently within the parent
            // ...
        })
    }
}
```

- Enforce with the `paralleltest` and `tparallel` linters so new tests don't silently opt out.
- Parallel tests must not share mutable globals; give each its own `t.TempDir()`, fixtures, and ports (`:0` for an OS-assigned port).

## httptest — testing handlers and clients

Test handlers without a real socket via `httptest.NewRecorder`; test clients against a fake server via `httptest.NewServer`.

```go
func TestGetUser(t *testing.T) {
    req := httptest.NewRequest(http.MethodGet, "/users/42", nil)
    req.SetPathValue("id", "42") // populate 1.22 path params in unit tests
    rec := httptest.NewRecorder()

    getUser(rec, req)

    if rec.Code != http.StatusOK {
        t.Fatalf("status = %d, want 200", rec.Code)
    }
}

func TestClient(t *testing.T) {
    srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.WriteHeader(http.StatusOK)
        io.WriteString(w, `{"ok":true}`)
    }))
    defer srv.Close()
    // point the client under test at srv.URL
}
```

## goleak — catch leaked goroutines

A goroutine leak (see `concurrency.md`) is invisible to a passing test. `go.uber.org/goleak` fails the package if goroutines outlive the tests.

```go
func TestMain(m *testing.M) {
    goleak.VerifyTestMain(m) // fails the run if any goroutine leaks
}
```

- Add it to any package that spawns goroutines (servers, workers, pipelines).
- Use `goleak.VerifyNone(t)` inside a single test for pinpoint checks; `goleak.IgnoreTopFunction(...)` to whitelist known-benign background goroutines (e.g. a persistent connection pool).

## Fuzzing

Native since Go 1.18. Fuzz any function that parses untrusted input — decoders, tokenizers, validators, protocol handlers. Seed the corpus with known tricky cases; the engine mutates from there and saves any crasher to `testdata/fuzz/`.

```go
func FuzzParseHeader(f *testing.F) {
    f.Add("Content-Type: text/plain") // seed corpus
    f.Add("")                          // edge case
    f.Fuzz(func(t *testing.T, in string) {
        h, err := ParseHeader(in)
        if err != nil {
            return // errors are fine; we're hunting panics + invariant violations
        }
        // Property: re-serializing a parsed header must round-trip.
        if got := h.String(); got != canonical(in) {
            t.Errorf("round-trip: %q -> %q", in, got)
        }
    })
}
```

- Run locally/CI: `go test -fuzz=FuzzParseHeader -fuzztime=30s`.
- Assert **properties** (no panic, round-trip, invariants hold), not exact outputs — you don't know the mutated input ahead of time.
- Commit discovered crashers (the files under `testdata/fuzz/`) so they become permanent regression cases.

## Golden / snapshot files

For large or structured output (rendered templates, serialized reports), compare against a checked-in golden file updated via a flag.

```go
var update = flag.Bool("update", false, "update golden files")

func TestRender(t *testing.T) {
    got := Render(input)
    golden := filepath.Join("testdata", t.Name()+".golden")
    if *update {
        os.WriteFile(golden, got, 0o644)
    }
    want, _ := os.ReadFile(golden)
    if !bytes.Equal(got, want) {
        t.Errorf("output differs from golden; run with -update to refresh")
    }
}
```

Review golden-file diffs like code — a blind `-update` defeats the purpose.

## Integration tests via build tags

Keep slow/external tests out of the fast unit run with a build tag.

```go
//go:build integration

package store_test
// ... tests that hit a real DB / container (testcontainers-go)
```

Run with `go test -tags=integration ./...`. Unit tests stay fast and hermetic; integration tests run in a dedicated CI stage.

## Mocking via interfaces

Mock at your **own** small interfaces (defined at the consumer, see SKILL.md), not concrete third-party types. Hand-written fakes are often clearer than generated mocks; `mockgen`/`moq` are fine for wide interfaces.

```go
type userRepo interface {
    Get(ctx context.Context, id string) (*User, error)
}

type fakeRepo struct{ users map[string]*User }
func (f *fakeRepo) Get(_ context.Context, id string) (*User, error) {
    u, ok := f.users[id]
    if !ok {
        return nil, domain.ErrNotFound
    }
    return u, nil
}
```

Prefer real implementations where cheap (an in-memory store, `sqlite` file, `httptest` server) over mocks — they test more and drift less.

## Coverage & the race detector

```bash
go test -race ./...                          # ALWAYS run with -race in CI
go test -cover ./...                         # coverage summary
go test -coverprofile=cover.out ./...        # then: go tool cover -html=cover.out
go test -coverpkg=./... ./...                # cross-package coverage
```

- `-race` is non-negotiable in CI. A data race is a bug even if the test passes today.
- Coverage is a **floor, not a target** — 100% coverage of trivial getters proves nothing; test behavior and edge cases, not lines.
- `testing/synctest` (1.25, see `concurrency.md`) makes time-dependent tests deterministic — use it instead of real `time.Sleep`.

## Pre-flight checklist

- [ ] Test written first; confirmed to fail for the right reason before implementation
- [ ] Table-driven with subtests (`t.Run`); helpers call `t.Helper()`
- [ ] Independent tests marked `t.Parallel()` (enforced by `paralleltest`)
- [ ] Handlers tested with `httptest`; comparisons use `cmp.Diff`
- [ ] Packages spawning goroutines guarded by `goleak.VerifyTestMain`
- [ ] Parsers/boundary code fuzzed; discovered crashers committed as regressions
- [ ] Large output covered by golden files reviewed on diff
- [ ] Slow/external tests behind an `integration` build tag
- [ ] Mocks defined at small consumer interfaces; real impls preferred where cheap
- [ ] `go test -race ./...` is green in CI; coverage treated as a floor

**Source:** [`testing` package](https://pkg.go.dev/testing), [Go Fuzzing](https://go.dev/doc/security/fuzz/), [`goleak`](https://github.com/uber-go/goleak), [`net/http/httptest`](https://pkg.go.dev/net/http/httptest), [`go-cmp`](https://pkg.go.dev/github.com/google/go-cmp/cmp). Structure inspired by samber/cc-skills-golang (MIT), prose original.
