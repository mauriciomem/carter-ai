# Go Networking

Read this when the work touches `net/http` servers or clients, raw `net.Conn`/TCP/UDP, QUIC, SSH, graceful shutdown, streaming/SSE/long-polling, or retries. This is Carter's highest-value Go reference: the default HTTP objects ship with **no timeouts**, which is a resource-exhaustion bug waiting to happen.

## The one rule: never use the zero-value HTTP objects in production

`http.DefaultClient` has no timeout — a single hung server can leak goroutines and file descriptors until the process dies. `http.DefaultServeMux` and the `http.ListenAndServe` convenience path give you a `Server` with every timeout unset, so a slow-loris client can hold connections open forever. Construct your own, always.

## HTTP server: set every timeout

```go
srv := &http.Server{
    Addr:    ":8080",
    Handler: mux,

    // Time to read the request headers. The single most important guard against
    // slow-loris; keep it short even if bodies are large.
    ReadHeaderTimeout: 5 * time.Second,

    // Time to read the entire request (headers + body). Set generously for uploads,
    // or set ReadHeaderTimeout only and manage body deadlines per-handler for streaming.
    ReadTimeout: 15 * time.Second,

    // Time from end-of-request-headers to end-of-response write. For streaming/SSE
    // responses this must be 0 (disabled) — otherwise the stream is cut off.
    WriteTimeout: 15 * time.Second,

    // How long an idle keep-alive connection is kept open.
    IdleTimeout: 60 * time.Second,

    // Cap header size (default is 1MB). Reject oversized header floods early.
    MaxHeaderBytes: 1 << 20,

    BaseContext: func(net.Listener) context.Context { return rootCtx },
}
```

| Timeout | Guards against | Typical value | Streaming caveat |
|---|---|---|---|
| `ReadHeaderTimeout` | slow-loris header trickle | 5s | keep short always |
| `ReadTimeout` | slow request body | 15s | raise for uploads |
| `WriteTimeout` | slow client draining response | 15s | **set 0** for SSE/streaming |
| `IdleTimeout` | keep-alive connection hoarding | 60s | — |

**Decision:** for a mixed server, set `ReadHeaderTimeout` globally, leave `WriteTimeout` at 0, and enforce per-request deadlines inside handlers via `http.ResponseController` (1.20+) so a streaming endpoint isn't strangled by a global write timeout:

```go
func handler(w http.ResponseWriter, r *http.Request) {
    rc := http.NewResponseController(w)
    _ = rc.SetWriteDeadline(time.Now().Add(30 * time.Second)) // per-request, overrides server default
    // ...
}
```

## Graceful shutdown (signal → drain → exit)

Non-negotiable for a service: on `SIGINT`/`SIGTERM`, stop accepting new connections, let in-flight requests finish within a deadline, then exit.

```go
func run(ctx context.Context) error {
    ctx, stop := signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)
    defer stop()

    srv := &http.Server{Addr: ":8080", Handler: mux, ReadHeaderTimeout: 5 * time.Second}

    errCh := make(chan error, 1)
    go func() {
        if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
            errCh <- err
        }
    }()

    select {
    case err := <-errCh:
        return err
    case <-ctx.Done(): // signal received
        shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
        defer cancel()
        return srv.Shutdown(shutdownCtx) // stops listener, drains in-flight, respects deadline
    }
}
```

- `Shutdown` returns the context's error if the drain deadline elapses — connections still open are then abandoned. Call `srv.Close()` only as a last resort (hard kill).
- `signal.NotifyContext` (1.16+) is cleaner than a manual `signal.Notify` channel.
- For non-HTTP servers, propagate the same `ctx` into your accept loop and close the listener on `ctx.Done()`.

## HTTP client & Transport: tune, pool, reuse

Create **one** client and reuse it — the `Transport` holds the connection pool. A fresh client per request defeats keep-alive and leaks connections.

```go
transport := &http.Transport{
    MaxIdleConns:        100,
    MaxIdleConnsPerHost: 10,              // default is 2 — raise for a hot upstream
    MaxConnsPerHost:     50,              // hard cap; 0 = unlimited
    IdleConnTimeout:     90 * time.Second,
    TLSHandshakeTimeout: 5 * time.Second,
    ExpectContinueTimeout: 1 * time.Second,
    ForceAttemptHTTP2:   true,
    DialContext: (&net.Dialer{
        Timeout:   5 * time.Second,       // connection establishment
        KeepAlive: 30 * time.Second,
    }).DialContext,
}
client := &http.Client{
    Transport: transport,
    Timeout:   30 * time.Second, // whole-request ceiling; prefer per-request context for finer control
}
```

**Prefer request context over `Client.Timeout`** when you need per-call deadlines or cancellation:

```go
ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
defer cancel()
req, _ := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
resp, err := client.Do(req)
```

- **Always** drain and close the body, or the connection can't be reused: `defer resp.Body.Close()`, and on early return `io.Copy(io.Discard, resp.Body)`.
- `Client.Timeout` covers the whole exchange including body read; a per-request `context` can be layered under it.

### Anti-pattern → fix

| Anti-pattern | Fix |
|---|---|
| `http.Get(url)` / `http.DefaultClient` | dedicated `*http.Client` with `Transport` + timeout |
| new `http.Client{}` per request | one shared client; the `Transport` pools connections |
| forgetting `resp.Body.Close()` | `defer resp.Body.Close()`; drain with `io.Copy(io.Discard, ...)` before close on early exit |
| `MaxIdleConnsPerHost` left at 2 for a hot upstream | raise it; otherwise connections churn |
| relying on `Client.Timeout` for cancellation | use `http.NewRequestWithContext` so the caller can cancel |

## Retries, backoff, and jitter

Retry only **idempotent** requests (GET/PUT/DELETE, or POST with an idempotency key) and only on transient failures (connection errors, 429, 502/503/504). Exponential backoff with **full jitter** prevents synchronized retry storms.

```go
func doWithRetry(ctx context.Context, client *http.Client, newReq func() *http.Request) (*http.Response, error) {
    const maxAttempts = 4
    base := 100 * time.Millisecond
    var lastErr error
    for attempt := range maxAttempts {
        resp, err := client.Do(newReq().WithContext(ctx))
        if err == nil && resp.StatusCode < 500 && resp.StatusCode != http.StatusTooManyRequests {
            return resp, nil
        }
        if resp != nil {
            io.Copy(io.Discard, resp.Body)
            resp.Body.Close()
        }
        lastErr = err
        // full jitter: sleep in [0, base*2^attempt)
        backoff := base * (1 << attempt)
        sleep := time.Duration(rand.Int64N(int64(backoff)))
        select {
        case <-ctx.Done():
            return nil, ctx.Err()
        case <-time.After(sleep):
        }
    }
    return nil, fmt.Errorf("exhausted retries: %w", lastErr)
}
```

- Honor a `Retry-After` header when present instead of your own backoff.
- Cap total attempts *and* respect the parent context deadline — never retry past the caller's budget.
- `rand.Int64N` is `math/rand/v2` (1.22+); no seeding needed.

## Raw connections: TCP & UDP with deadlines

Every raw `net.Conn` read/write can block forever. Set deadlines — there is no equivalent of a server-level timeout.

```go
conn, err := net.DialTimeout("tcp", addr, 5*time.Second)
if err != nil {
    return fmt.Errorf("dial %s: %w", addr, err)
}
defer conn.Close()

conn.SetReadDeadline(time.Now().Add(10 * time.Second))   // absolute time, not duration
conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
// SetDeadline sets both at once. Refresh before each op for a rolling timeout.
```

- Deadlines are **absolute instants** and do not reset; re-arm before each read/write for a per-op timeout.
- A hit deadline yields an error where `errors.Is(err, os.ErrDeadlineExceeded)` is true (and `netErr.Timeout()` reports true).
- Prefer `net.Dialer{}.DialContext(ctx, ...)` over `DialTimeout` so cancellation propagates from the caller.

### TCP server accept loop

```go
ln, err := net.Listen("tcp", ":9000")
if err != nil {
    return err
}
defer ln.Close()
go func() { <-ctx.Done(); ln.Close() }() // unblock Accept on shutdown

for {
    conn, err := ln.Accept()
    if err != nil {
        if errors.Is(err, net.ErrClosed) {
            return nil // clean shutdown
        }
        return fmt.Errorf("accept: %w", err)
    }
    go handleConn(ctx, conn) // handleConn MUST set deadlines and honor ctx — see concurrency.md
}
```

### UDP

UDP is connectionless — use `net.ListenPacket`/`ReadFrom`/`WriteTo`. There is no accept loop and no built-in reliability; you own retransmission and ordering.

```go
pc, err := net.ListenPacket("udp", ":9001")
if err != nil {
    return err
}
defer pc.Close()
buf := make([]byte, 65507) // max UDP payload
for {
    pc.SetReadDeadline(time.Now().Add(time.Second))
    n, addr, err := pc.ReadFrom(buf)
    if err != nil {
        var ne net.Error
        if errors.As(err, &ne) && ne.Timeout() {
            select {
            case <-ctx.Done():
                return nil
            default:
                continue // deadline tick, loop to re-check ctx
            }
        }
        return err
    }
    handlePacket(buf[:n], addr)
}
```

## QUIC (quic-go)

QUIC is UDP-based, gives you TLS 1.3 + multiplexed streams with no head-of-line blocking. The stdlib has no QUIC server; use `github.com/quic-go/quic-go` (the de-facto library). HTTP/3 rides on it via `quic-go/http3`.

```go
listener, err := quic.ListenAddr(":4242", tlsConf, &quic.Config{
    MaxIdleTimeout:  30 * time.Second,
    KeepAlivePeriod: 15 * time.Second,
})
// conn, _ := listener.Accept(ctx); stream, _ := conn.AcceptStream(ctx)
```

- A QUIC *connection* multiplexes many *streams*; open a stream per logical request. Streams are `io.ReadWriteCloser`.
- TLS is mandatory — QUIC has no cleartext mode. Set `MaxIdleTimeout` and `KeepAlivePeriod`.
- Reach for QUIC when you need low-latency, connection-migration (mobile), or multiplexing over one UDP flow. Otherwise TCP/HTTP2 is simpler.

## SSH (golang.org/x/crypto/ssh)

For SSH clients/servers, use `golang.org/x/crypto/ssh`. **Never** use `ssh.InsecureIgnoreHostKey()` outside throwaway tests — it defeats MITM protection.

```go
signer, err := ssh.ParsePrivateKey(keyPEM)
if err != nil {
    return fmt.Errorf("parse key: %w", err)
}
hostKeyCB, err := knownhosts.New(knownHostsPath) // golang.org/x/crypto/ssh/knownhosts
if err != nil {
    return err
}
cfg := &ssh.ClientConfig{
    User:            "deploy",
    Auth:            []ssh.AuthMethod{ssh.PublicKeys(signer)},
    HostKeyCallback: hostKeyCB, // verify the host key — required
    Timeout:         5 * time.Second,
}
client, err := ssh.Dial("tcp", "host:22", cfg)
```

- Pin host keys with `knownhosts`; treat an unknown host key as a hard failure to approve, not to ignore.
- Prefer key auth over passwords. Set `Timeout` so the handshake can't hang.
- Per-session I/O still needs deadlines — set them on the underlying `net.Conn` you dial before wrapping.

## Streaming, SSE & long-polling

For Server-Sent Events or chunked streaming you must **flush** after each write and **disable the write timeout** for that connection.

```go
func sse(w http.ResponseWriter, r *http.Request) {
    w.Header().Set("Content-Type", "text/event-stream")
    w.Header().Set("Cache-Control", "no-cache")
    w.Header().Set("Connection", "keep-alive")
    rc := http.NewResponseController(w)
    _ = rc.SetWriteDeadline(time.Time{}) // no write deadline for the stream

    for {
        select {
        case <-r.Context().Done(): // client disconnected — always watch this
            return
        case ev := <-events:
            fmt.Fprintf(w, "data: %s\n\n", ev)
            if err := rc.Flush(); err != nil { // push bytes to the client now
                return
            }
        case <-time.After(15 * time.Second):
            fmt.Fprint(w, ": keep-alive\n\n") // comment frame keeps proxies from closing idle conns
            _ = rc.Flush()
        }
    }
}
```

- Watch `r.Context().Done()` to detect client disconnects and stop producing.
- Send periodic keep-alive comment frames so intermediary proxies don't drop an idle connection.
- **Long-polling**: hold the request open with a `select` on `ctx.Done()` + a data channel + a max-hold `time.After`; return 204/empty when the hold expires so the client re-polls. Prefer SSE or WebSockets for high-frequency updates.
- `http.NewResponseController` (1.20+) replaces the old `w.(http.Flusher)` type assertion and also exposes `SetReadDeadline`/`SetWriteDeadline`.

## Pre-flight checklist

- [ ] No `http.DefaultClient`/`DefaultServeMux`/`http.Get` in production paths
- [ ] Server sets `ReadHeaderTimeout` (always), plus `ReadTimeout`/`WriteTimeout`/`IdleTimeout` as appropriate
- [ ] `WriteTimeout` disabled (or per-request via `ResponseController`) for streaming endpoints
- [ ] Graceful shutdown wired: `signal.NotifyContext` + `Server.Shutdown(ctx)` with a drain deadline
- [ ] One shared `*http.Client` with a tuned `Transport`; bodies always drained + closed
- [ ] Retries limited to idempotent requests with exponential backoff + jitter, capped by ctx
- [ ] Every raw `net.Conn`/UDP op has a deadline; accept loops close the listener on `ctx.Done()`
- [ ] SSH verifies host keys (`knownhosts`), never `InsecureIgnoreHostKey`; TLS mandatory for QUIC
- [ ] SSE/streaming flushes each frame, watches `r.Context().Done()`, sends keep-alives

**Source:** [`net/http` docs](https://pkg.go.dev/net/http), [Cloudflare — The complete guide to Go net/http timeouts](https://blog.cloudflare.com/the-complete-guide-to-golang-net-http-timeouts/), [`http.ResponseController`](https://pkg.go.dev/net/http#ResponseController), [quic-go](https://github.com/quic-go/quic-go), [`x/crypto/ssh`](https://pkg.go.dev/golang.org/x/crypto/ssh). Structure inspired by samber/cc-skills-golang (MIT), prose original.
