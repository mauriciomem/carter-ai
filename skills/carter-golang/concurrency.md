# Go Concurrency & Context

Read this when the work spawns goroutines, uses channels/mutexes/atomics, coordinates parallel work with `errgroup`, deduplicates with `singleflight`, propagates context deadlines across network calls, or needs deterministic concurrency tests with `synctest`.

## The prime directive: every goroutine has a guaranteed exit

A goroutine you can't stop is a leak. Before you write `go f()`, answer: *how does this goroutine end?* The only acceptable answers are: it runs to completion on its own, or it observes a cancellation signal (`ctx.Done()`, a done channel, or a closed input channel).

```go
// LEAK — no way to stop it; if nobody ever reads `ch`, this blocks forever.
go func() { ch <- expensive() }()

// FIXED — respects cancellation on send.
go func() {
    select {
    case ch <- expensive():
    case <-ctx.Done():
    }
}()
```

## Channel ownership rules

The goroutine that **writes** to a channel **owns** it: it is the only one allowed to close it, and it closes it exactly once when done producing. Readers never close. This single rule prevents "send on closed channel" panics and "close of closed channel" panics.

```go
func produce(ctx context.Context) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out) // owner closes on the way out
        for i := range 10 {
            select {
            case out <- i:
            case <-ctx.Done():
                return
            }
        }
    }()
    return out
}
```

- Return a receive-only channel (`<-chan T`) so callers physically can't close it.
- A closed channel reads the zero value forever; `v, ok := <-ch` with `ok == false` signals closed.
- Never close a channel from the receiver side, and never close a channel with multiple concurrent senders without a coordinating layer (use `sync.WaitGroup` + a single closer).

## Channel vs mutex vs atomic — decision matrix

| Use | When | Example |
|---|---|---|
| **Channel** | transferring ownership of data between goroutines; signaling; pipelines | work queue, fan-in/fan-out, done signaling |
| **`sync.Mutex`/`RWMutex`** | protecting a struct's invariants across multiple fields | in-memory cache map, connection registry |
| **`atomic` (`atomic.Int64`, `atomic.Pointer`)** | a single counter/flag/pointer swapped without a surrounding invariant | request counter, feature flag, hot-path config pointer |
| **`sync.Once`** | exactly-once lazy init | singleton connection, compiled regexp |

Rule of thumb: *"Don't communicate by sharing memory; share memory by communicating"* — but a mutex around a map is often simpler and faster than a channel-guarded goroutine. Pick the one that makes the code obviously correct, not the cleverest.

```go
type Counter struct{ n atomic.Int64 }
func (c *Counter) Inc()       { c.n.Add(1) }
func (c *Counter) Value() int64 { return c.n.Load() }
```

## errgroup: bounded parallel work with error propagation

`golang.org/x/sync/errgroup` cancels sibling goroutines on the first error and returns it. **Always** bound concurrency with `SetLimit` for fan-out over external calls — unbounded fan-out exhausts file descriptors and hammers upstreams.

```go
g, ctx := errgroup.WithContext(ctx)
g.SetLimit(8) // at most 8 in flight; Go() blocks when full

for _, url := range urls {
    g.Go(func() error {
        return fetch(ctx, url) // ctx is cancelled the moment any sibling errors
    })
}
if err := g.Wait(); err != nil {
    return fmt.Errorf("fetch batch: %w", err)
}
```

| Primitive | Use it for |
|---|---|
| `sync.WaitGroup` | wait for N goroutines, no error/cancellation coordination |
| `errgroup.Group` | wait + first-error + shared cancellation |
| `errgroup` + `SetLimit(n)` | the above **plus** bounded concurrency (semaphore built in) |

- With Go 1.22+ loopvar there's no `url := url` shadowing needed — each iteration has its own variable.
- `g.Wait()` returns only the **first** error; use `errors.Join` inside the group if you need all of them.

## Worker pool (bounded, cancellable)

```go
func pool(ctx context.Context, jobs <-chan Job, workers int) error {
    g, ctx := errgroup.WithContext(ctx)
    for range workers {
        g.Go(func() error {
            for {
                select {
                case <-ctx.Done():
                    return ctx.Err()
                case job, ok := <-jobs:
                    if !ok {
                        return nil // input drained — clean exit
                    }
                    if err := process(ctx, job); err != nil {
                        return err // cancels siblings
                    }
                }
            }
        })
    }
    return g.Wait()
}
```

`errgroup.SetLimit` often replaces a hand-rolled pool entirely — prefer it unless you need long-lived workers pulling from a shared queue.

## singleflight: collapse duplicate concurrent work

`golang.org/x/sync/singleflight` ensures that N concurrent callers asking for the same key trigger the work **once** and all share the result. Ideal for cache-stampede protection.

```go
var group singleflight.Group

func getUser(ctx context.Context, id string) (*User, error) {
    v, err, _ := group.Do(id, func() (any, error) {
        return loadUserFromDB(ctx, id) // runs once per id even under a thundering herd
    })
    if err != nil {
        return nil, err
    }
    return v.(*User), nil
}
```

- Use `DoChan` for a context-cancellable variant; the shared call itself is not cancelled by one caller leaving.
- Beware: a slow/erroring call is shared by all waiters. Add a short TTL or `Forget(key)` so a transient failure isn't cached across the herd.

## Context deadline propagation across network calls

Context is how a deadline flows from an inbound request all the way to the database and the upstream HTTP call. Propagate it; never start a fresh `context.Background()` mid-request (that severs cancellation).

```go
func (s *Service) Handle(ctx context.Context, req Req) (Resp, error) {
    // Tighten (never loosen) the deadline for a specific downstream call.
    ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
    defer cancel()

    row, err := s.db.QueryRowContext(ctx, q, req.ID) // DB honors ctx cancellation
    // ...
}
```

- Each `WithTimeout`/`WithCancel` **must** have its `cancel()` called (usually `defer`) or you leak the context's timer goroutine.
- A child deadline can only be *shorter* than its parent's; the earliest deadline wins.
- Use `context.WithValue` only for request-scoped metadata (request ID, auth principal) — never for optional function parameters.
- `context.Cause(ctx)` (1.20+) returns the specific error passed to `WithCancelCause`, useful for distinguishing timeout vs. explicit cancel — see `errors-safety.md`.

## Deterministic concurrency tests: testing/synctest (1.25)

`testing/synctest` runs a "bubble" with a fake clock: goroutines that block advance virtual time instantly, so timeout/ticker logic is tested deterministically with **zero real sleeping** and no flakiness.

```go
func TestTimeout(t *testing.T) {
    synctest.Test(t, func(t *testing.T) {
        ctx, cancel := context.WithTimeout(context.Background(), time.Hour)
        defer cancel()

        start := time.Now()
        <-ctx.Done()                 // fake clock jumps forward instantly
        if elapsed := time.Since(start); elapsed != time.Hour {
            t.Fatalf("want 1h, got %v", elapsed)
        }
    })
}
```

- Was `testing/synctest` experimental behind `GOEXPERIMENT=synctest` in 1.24; stabilized as `synctest.Test` in 1.25.
- Pair with `synctest.Wait()` to block until every goroutine in the bubble is durably blocked before asserting.

## Anti-pattern catalog

| Anti-pattern | Why it hurts | Fix |
|---|---|---|
| Fire-and-forget `go f()` | leaks on shutdown; no error surface | track with `errgroup`/`WaitGroup`; bound by `ctx` |
| goroutine that never selects on `ctx.Done()` | can't be cancelled; leaks | add a `case <-ctx.Done(): return` |
| `time.NewTicker` without `defer t.Stop()` | leaks the ticker's timer | always `defer ticker.Stop()` |
| unbounded fan-out (`for … { go call() }`) | FD/socket exhaustion, upstream overload | `errgroup` + `SetLimit(n)` |
| closing a channel from the receiver | panic on send | only the sender/owner closes |
| shared `context.Background()` mid-request | severs deadline/cancellation | thread the request's `ctx` through |
| `sync.WaitGroup` with `wg.Add` inside the goroutine | race between `Add` and `Wait` | `Add` before `go`, `Done` via `defer` inside |
| forgetting `cancel()` from `WithTimeout` | leaked timer goroutine (vet warns) | `defer cancel()` immediately |

## Pre-flight checklist

- [ ] Every `go` statement has a provable exit path (completes, `ctx.Done()`, or closed input channel)
- [ ] Channel closed only by its owning sender, exactly once; receivers get `<-chan T`
- [ ] Fan-out over external calls is bounded (`errgroup.SetLimit`, semaphore, or worker pool)
- [ ] `context.Context` threaded through every I/O hop; every `cancel()` is deferred
- [ ] Tickers/timers stopped; no orphaned timers
- [ ] Channel vs mutex vs atomic chosen for clarity, not cleverness
- [ ] Tests run with `-race`; time-dependent logic tested with `synctest` where possible
- [ ] `singleflight` (with a TTL/`Forget` guard) used for stampede-prone reads

**Source:** [Go Concurrency Patterns: Pipelines](https://go.dev/blog/pipelines), [`errgroup`](https://pkg.go.dev/golang.org/x/sync/errgroup), [`singleflight`](https://pkg.go.dev/golang.org/x/sync/singleflight), [`testing/synctest`](https://pkg.go.dev/testing/synctest), [Go Memory Model](https://go.dev/ref/mem). Structure inspired by samber/cc-skills-golang (MIT), prose original.
