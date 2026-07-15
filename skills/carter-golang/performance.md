# Go Performance

Read this when the work involves profiling, benchmarking, reducing allocations, `sync.Pool`, GC tuning (`GOGC`/`GOMEMLIMIT`), or escape analysis. **First rule: don't.** Measure before you optimize — most "obvious" optimizations target code that isn't hot, and they cost readability. Prove the hotspot with a profile, then optimize the one thing that matters, then re-measure.

## When NOT to optimize

- You have **no profile** showing this code is hot. Intuition about Go performance is wrong more often than right.
- The code isn't on a hot path (runs once at startup, or handles rare requests).
- The optimization trades clarity for a gain you can't measure. Readable code your team maintains beats a clever micro-optimization.
- You haven't set a **target**. "Faster" is not a goal; "p99 latency under 50ms" or "allocs/op < 5" is.

The order is always: **benchmark → profile → optimize the proven hotspot → benchmark again to confirm the win.**

## Benchmarks (with b.Loop, 1.24+)

`b.Loop()` (Go 1.24) is the modern benchmark loop: it prevents the compiler from optimizing away the work and handles ramp-up correctly, replacing the error-prone `for i := 0; i < b.N; i++` pattern.

```go
func BenchmarkParse(b *testing.B) {
    input := loadFixture() // setup outside the measured loop
    b.ReportAllocs()       // report allocs/op alongside ns/op
    for b.Loop() {         // 1.24+: keeps `input` alive, excludes setup automatically
        _ = Parse(input)
    }
}
```

```bash
go test -bench=BenchmarkParse -benchmem -count=10 -run=^$ ./...
```

- `-benchmem` (or `b.ReportAllocs()`) shows `B/op` and `allocs/op` — allocations are usually the real story, not raw ns.
- `-count=10` gives multiple samples so `benchstat` can judge significance.
- Pre-1.24 loops must use `b.N` and guard against dead-code elimination with a package-level sink; prefer `b.Loop` on 1.24+.

## benchstat — is the change real?

Never eyeball two benchmark runs. `benchstat` reports the delta with a confidence interval, so you don't chase noise.

```bash
go test -bench=. -benchmem -count=10 -run=^$ ./... > old.txt
# ... make the change ...
go test -bench=. -benchmem -count=10 -run=^$ ./... > new.txt
benchstat old.txt new.txt   # shows % change + p-value; "~" means no significant difference
```

If `benchstat` says the change is `~` (not significant), you didn't make it faster — revert it if it cost readability.

## pprof — find the hotspot

Four profiles, each answering a different question:

| Profile | Answers | Enable |
|---|---|---|
| **CPU** | where is time spent? | `go test -cpuprofile=cpu.out -bench=.` or `pprof.StartCPUProfile` |
| **Heap/mem** | what allocates / stays resident? | `-memprofile=mem.out`, or `/debug/pprof/heap` |
| **Block** | where do goroutines block on sync? | `runtime.SetBlockProfileRate(1)` |
| **Mutex** | where is lock contention? | `runtime.SetMutexProfileFraction(1)` |

```go
import _ "net/http/pprof" // registers /debug/pprof/* on the DefaultServeMux
// Expose on a SEPARATE, internal-only listener — never on your public mux.
go func() { log.Println(http.ListenAndServe("localhost:6060", nil)) }()
```

```bash
go tool pprof -http=:8081 cpu.out           # interactive flame graph in the browser
go tool pprof http://localhost:6060/debug/pprof/heap
# in the REPL: top, list <func>, web
```

- **Never** expose `net/http/pprof` on a public listener — it leaks internals and is a DoS vector. Bind it to `localhost` or an admin port.
- Start with `top` to find the heaviest functions, then `list <func>` to see line-level cost.

## Allocation reduction & pre-allocation

Allocations drive GC pressure, which drives tail latency. The cheapest win is allocating less.

```go
// Pre-size slices/maps when the final size is known — avoids repeated growth+copy.
out := make([]Item, 0, len(in)) // cap hint; no reallocation as it fills
m := make(map[string]int, len(keys))

// Reuse buffers instead of allocating per call.
var buf bytes.Buffer
buf.Reset() // reuse across iterations

// strings.Builder avoids the []byte↔string copies of naive concatenation.
var sb strings.Builder
sb.Grow(estimatedLen)
for _, s := range parts {
    sb.WriteString(s)
}
```

- Passing large structs by value copies them; pass a pointer for big structs on hot paths (but small structs by value are often *faster* — they stay on the stack).
- Avoid `interface{}`/`any` boxing in hot loops — it allocates. Generics (1.18+) keep types concrete without boxing.
- `[]byte(s)` and `string(b)` conversions allocate; minimize round-trips on hot paths.

## sync.Pool — recycle short-lived allocations

For frequently allocated, short-lived objects (buffers, per-request scratch) on a proven hot path, `sync.Pool` amortizes allocation across requests.

```go
var bufPool = sync.Pool{New: func() any { return new(bytes.Buffer) }}

func handle() {
    buf := bufPool.Get().(*bytes.Buffer)
    buf.Reset()               // pooled objects are dirty — reset before use
    defer bufPool.Put(buf)
    // ... use buf ...
}
```

- Only worth it under a profile showing allocation pressure — `sync.Pool` adds complexity and pooled objects can be GC'd at any time.
- Always `Reset()` on Get: a pooled object retains its old contents. Forgetting this leaks data between requests — a real security bug.

## Escape analysis

A value "escapes" to the heap when the compiler can't prove it stays within the function's lifetime (e.g. it's returned by pointer, stored in an interface, or captured by a goroutine). Heap allocation → GC work.

```bash
go build -gcflags='-m' ./...    # prints "escapes to heap" / "does not escape" decisions
```

- Returning `*T` from a constructor forces a heap allocation — usually fine and idiomatic; don't fight it without a profile.
- Passing a value to an `interface{}` parameter (`fmt.Println`, logging) boxes and escapes it — a reason structured logging with typed fields (`slog`) beats `fmt.Sprintf` on hot paths.
- Closures that capture variables can force those variables to the heap.

## GC tuning: GOGC and GOMEMLIMIT

Tune the GC only after allocation reduction has been exhausted and a profile shows GC as the bottleneck.

| Knob | Effect | When |
|---|---|---|
| `GOGC` (default 100) | GC runs when heap grows GOGC% since last GC. Higher = less frequent GC, more memory. | Raise (e.g. 200) for throughput on a box with spare RAM; lower for memory-constrained. |
| `GOMEMLIMIT` (1.19+) | soft memory ceiling; GC works harder as you approach it | **Set this in containers** to avoid OOM-kills — combine with `GOGC=off` for a hard-limit-driven GC. |

```bash
GOMEMLIMIT=900MiB GOGC=off ./server   # GC driven purely by the memory ceiling
```

- In a container, set `GOMEMLIMIT` to ~90% of the memory limit so the GC reclaims before the kernel OOM-kills the process.
- `GOMAXPROCS` should match the CPU quota (use `automaxprocs` when running under a cgroup CPU limit, or set it explicitly) — otherwise the scheduler assumes all host cores.

## Pre-flight checklist

- [ ] A profile (not intuition) shows this code is actually hot before optimizing
- [ ] A concrete target exists (latency/allocs/throughput number), not just "faster"
- [ ] Benchmarks use `b.Loop()` (1.24+) with `-benchmem`; compared via `benchstat -count>=10`
- [ ] `benchstat` confirms the change is statistically significant (not `~`)
- [ ] Allocations reduced first: pre-sized slices/maps, reused buffers, `strings.Builder`
- [ ] `sync.Pool` only under proven allocation pressure; pooled objects `Reset()` on Get
- [ ] `pprof` never exposed on a public listener
- [ ] Containers set `GOMEMLIMIT` (and `GOMAXPROCS`/automaxprocs under a CPU quota)
- [ ] The optimization was re-benchmarked to confirm the win; readability trade-off justified

**Source:** [Profiling Go Programs](https://go.dev/blog/pprof), [`runtime/pprof`](https://pkg.go.dev/runtime/pprof), [`benchstat`](https://pkg.go.dev/golang.org/x/perf/cmd/benchstat), [A Guide to the Go Garbage Collector](https://go.dev/doc/gc-guide), [`testing.B.Loop`](https://pkg.go.dev/testing#B.Loop). Structure inspired by samber/cc-skills-golang (MIT), prose original.
