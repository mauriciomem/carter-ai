# Go Errors & Safety

Read this when the work involves error wrapping/inspection, sentinel or custom error types, aggregating errors, distinguishing cancellation from timeout, or the memory-safety hazards Go still lets you write: nil dereferences, slice aliasing / `append` surprises, integer overflow, and panic/recover boundaries. This deepens the error-handling core in SKILL.md.

## Wrap with context using %w

Every error crossing a function boundary should gain context, wrapped with `%w` so callers can still inspect the cause with `errors.Is`/`errors.As`.

```go
if err != nil {
    return fmt.Errorf("fetch user %s: %w", id, err) // %w preserves the chain; %v would flatten it
}
```

- Use `%w` when the caller might want to inspect the cause; `%v` only when you deliberately want to *hide* the underlying error type (a boundary abstraction).
- One `%w` per `Errorf` for a single cause; wrap multiple causes with `errors.Join` (below), not multiple `%w`.
- Message convention: lowercase, no trailing punctuation, describes *what this layer was doing* ("fetch user 42: connection refused"), so the chain reads as a stack.

## Sentinels vs custom types — decision

| Kind | Use when | Inspect with |
|---|---|---|
| **Sentinel** (`var ErrNotFound = errors.New(...)`) | callers only need to know *which* error, no data | `errors.Is(err, ErrNotFound)` |
| **Custom type** (`type ValidationError struct{...}`) | callers need structured data (field, code, retry-after) | `errors.As(err, &ve)` |

```go
// Sentinel — identity only.
var ErrNotFound = errors.New("not found")

// Custom type — carries data. Pointer receiver so errors.As can populate it.
type ValidationError struct {
    Field, Message string
}
func (e *ValidationError) Error() string { return fmt.Sprintf("%s: %s", e.Field, e.Message) }

// Inspection:
if errors.Is(err, ErrNotFound) { /* ... */ }
var ve *ValidationError
if errors.As(err, &ve) {
    log.Printf("bad field %s", ve.Field)
}
```

- **Never** compare errors with `==` across a wrap boundary — `err == ErrNotFound` fails once wrapped; use `errors.Is`.
- Give sentinels a package-qualified feel in messages so logs are greppable.

## errors.Join — aggregate multiple failures

`errors.Join` (1.20+) combines several errors into one; `errors.Is`/`As` see through to each. Ideal for validation (report all failures at once) and cleanup (close several resources, surface every failure).

```go
func (r Req) Validate() error {
    var errs []error
    if r.Name == "" {
        errs = append(errs, errors.New("name required"))
    }
    if r.Age < 0 {
        errs = append(errs, errors.New("age must be non-negative"))
    }
    return errors.Join(errs...) // nil if the slice is empty/all-nil
}
```

```go
func closeAll(closers ...io.Closer) error {
    var err error
    for _, c := range closers {
        err = errors.Join(err, c.Close()) // accumulate; nil Close() is skipped
    }
    return err
}
```

## context.Cause — timeout vs explicit cancel

`context.Cause(ctx)` (1.20+) returns the specific reason a context ended — distinguishing a deadline from a deliberate cancel, which `ctx.Err()` alone can't.

```go
ctx, cancel := context.WithCancelCause(parent)
// somewhere: cancel(ErrUserAborted)

<-ctx.Done()
switch {
case errors.Is(context.Cause(ctx), ErrUserAborted):
    // user pressed stop
case errors.Is(ctx.Err(), context.DeadlineExceeded):
    // timed out
}
```

- `context.WithTimeoutCause`/`WithDeadlineCause` (1.21+) attach a custom cause to a deadline, so a timeout surfaces a meaningful error instead of the generic `context.DeadlineExceeded`.
- Map `context.DeadlineExceeded` to a 504 at API boundaries (see `apis.md`).

## The rules (kept from the core, expanded)

- Check every error immediately; never discard with `_` (except documented no-op cases like `defer f.Close()` on a read-only file — even then, prefer handling it).
- Wrap with context at each layer; don't wrap the *same* error twice at one layer.
- **Don't log *and* return** the same error — pick one owner. Log at the top of the stack where you handle it; return everywhere below.
- Don't `panic` in library code. Return an error. Panic is for truly unrecoverable programmer bugs (a violated invariant that means the program is corrupt).

## Nil safety

Go's most common runtime panic is a nil dereference. The traps that bite:

```go
// A nil map READS fine but PANICS on write.
var m map[string]int
_ = m["x"]        // ok, returns 0
m["x"] = 1        // panic: assignment to entry in nil map — must make() first

// A typed nil in an interface is NOT == nil.
func do() error {
    var e *MyError // nil pointer
    return e       // returns a non-nil interface wrapping a nil pointer!
}
if do() != nil { /* TRUE — surprising bug */ }
```

- Initialize maps with `make` before writing. Slices are safe to `append` to when nil (append allocates).
- Return the `error` interface as literal `nil`, never a typed nil pointer — return `nil` explicitly on the success path.
- Guard pointer fields before dereferencing; a nil embedded interface method call panics.

## Slice aliasing & append gotchas

Slices share backing arrays. `append` may or may not allocate a new array depending on capacity — so a mutation can silently corrupt a slice someone else holds.

```go
a := []int{1, 2, 3, 4}
b := a[:2]              // b shares a's backing array
b = append(b, 99)      // OVERWRITES a[2]! b had spare capacity -> a is now [1,2,99,4]

// Fix: full-slice expression caps capacity, forcing append to allocate.
b := a[:2:2]           // len 2, cap 2 — append now copies, leaving `a` untouched
```

- Sub-slicing a large slice keeps the **entire** backing array alive (a memory leak). Copy out the piece you need: `keep := append([]T(nil), src[i:j]...)`.
- When returning a slice derived from a caller's input, use the three-index slice `s[lo:hi:hi]` or copy, so the caller can't later corrupt your data (and vice versa).
- `slices.Clone` (1.21+) is the clear way to make an independent copy.

## Integer overflow & conversions

Go integer arithmetic **wraps silently** — no panic, no error.

```go
var x int8 = 127
x++            // -128, silently wrapped

n := len(data) // int
u := uint32(n) // TRUNCATES if n > math.MaxUint32 — validate before narrowing
```

- Validate bounds before narrowing conversions (`int` → `int32`/`uint32`), especially with lengths/sizes from untrusted input — a truncated length is a classic vuln.
- Watch multiplications that can overflow (`w * h * 4` for image buffers); check against `math.MaxInt` first.
- The `gosec` linter (G115) flags risky integer conversions — keep it enabled.

## Panic / recover boundaries

Panics unwind the stack and, if unrecovered, crash the process — including taking down every other in-flight request in a server. Recover only at **boundaries** you own.

```go
// Recover at the goroutine boundary — an un-recovered panic in ANY goroutine kills the process.
go func() {
    defer func() {
        if r := recover(); r != nil {
            slog.Error("worker panic", "panic", r, "stack", string(debug.Stack()))
        }
    }()
    doWork()
}()
```

- `net/http` recovers panics **per request** for the default server, but a panic in a **background goroutine** you spawned is *not* caught — it crashes the whole process. Add recovery there yourself.
- Recover to log + convert to an error/500, then let the request fail cleanly — don't swallow a panic and continue as if nothing happened; the state may be corrupt.
- Never use panic/recover as control flow. It's a last-resort safety net, not a `try/catch`.

## Safety linters

Enable in `golangci-lint` and treat findings as blockers:

- `errcheck` — unchecked errors
- `gosec` — security smells incl. G115 integer conversions, hardcoded creds, weak crypto
- `staticcheck` — a large class of correctness bugs (SA rules), incl. nil and unreachable-code checks
- `nilerr` / `nilnil` — returning nil error with a non-nil result or vice versa
- `bodyclose` — unclosed HTTP response bodies (ties to `networking.md`)
- `govet` (built into `go test`) — `copylocks`, `lostcancel` (leaked context cancel), `printf`
- `exhaustive` — non-exhaustive enum switches

## Pre-flight checklist

- [ ] Errors wrapped with `%w` and lowercase context; inspected via `errors.Is`/`errors.As`, never `==`
- [ ] Sentinels for identity, custom types (pointer receiver) for structured data
- [ ] Multiple failures aggregated with `errors.Join`; cleanup errors surfaced
- [ ] No log-and-return of the same error; no `panic` in library code
- [ ] Maps `make`-initialized before write; `error` returned as literal `nil`, never a typed nil
- [ ] Slice aliasing guarded (`s[lo:hi:hi]` or copy); large-backing-array leaks avoided
- [ ] Narrowing integer conversions bounds-checked (untrusted lengths especially)
- [ ] Every spawned goroutine has a `recover` boundary that logs + fails cleanly
- [ ] `errcheck`, `gosec`, `staticcheck`, `bodyclose`, `govet` enabled and green

**Source:** [Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors), [`errors` package](https://pkg.go.dev/errors), [`context.Cause`](https://pkg.go.dev/context#Cause), [Go Slices: usage and internals](https://go.dev/blog/slices-intro), [`gosec`](https://github.com/securego/gosec). Structure inspired by samber/cc-skills-golang (MIT), prose original.
