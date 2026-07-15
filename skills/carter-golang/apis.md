# Go APIs — REST & gRPC

Read this when the work builds or reviews an HTTP/REST API (routing, middleware, request/JSON validation, error→status mapping) or a gRPC service (protobuf, interceptors, streaming). Carter's default: **stdlib `net/http` first** — the 1.22 `ServeMux` covers method + path-parameter routing without a framework. Reach for gRPC when you own both ends and want typed contracts + streaming.

## REST with stdlib net/http (1.22 routing)

Go 1.22's `ServeMux` matches HTTP methods and wildcards — no third-party router needed for most services.

```go
mux := http.NewServeMux()
mux.HandleFunc("GET /users/{id}", getUser)     // method + path parameter
mux.HandleFunc("POST /users", createUser)
mux.HandleFunc("GET /users/{id}/orders/{oid}", getOrder)

func getUser(w http.ResponseWriter, r *http.Request) {
    id := r.PathValue("id") // typed path segment, no regex router required
    // ...
}
```

- Patterns: `"GET /path"`, wildcards `{name}`, trailing `{path...}` for catch-all, `{$}` to match exactly (no subtree).
- More specific patterns win; a conflict panics at registration (fail-fast, good).
- Add a framework (chi, echo) only when you need grouping/param-middleware ergonomics the stdlib lacks — and say why.

### Handler shape: keep handlers thin

A handler decodes the request, calls a service, and encodes the response. Business logic lives in `internal/service`, not the handler.

```go
func createUser(w http.ResponseWriter, r *http.Request) {
    var req CreateUserRequest
    if err := decodeJSON(w, r, &req); err != nil {
        writeError(w, err) // maps error → status; see below
        return
    }
    if err := req.Validate(); err != nil {
        writeError(w, err)
        return
    }
    user, err := userService.Create(r.Context(), req.toDomain())
    if err != nil {
        writeError(w, err)
        return
    }
    writeJSON(w, http.StatusCreated, toUserResponse(user))
}
```

## JSON safety at the boundary

Two footguns: unbounded bodies (memory exhaustion) and silently-ignored unknown fields (typos, injected data). Guard both.

```go
func decodeJSON(w http.ResponseWriter, r *http.Request, dst any) error {
    r.Body = http.MaxBytesReader(w, r.Body, 1<<20) // cap at 1 MiB — reject oversized bodies
    dec := json.NewDecoder(r.Body)
    dec.DisallowUnknownFields()                     // reject unexpected keys instead of ignoring them
    if err := dec.Decode(dst); err != nil {
        return &APIError{Status: http.StatusBadRequest, Msg: "invalid JSON: " + err.Error()}
    }
    if dec.More() {                                 // reject trailing garbage / multiple JSON values
        return &APIError{Status: http.StatusBadRequest, Msg: "body must contain a single JSON object"}
    }
    return nil
}
```

- `MaxBytesReader` also sets the response to 413 semantics and stops reading past the limit.
- `DisallowUnknownFields` turns typos and unexpected keys into 400s — invaluable for API contracts.
- On encode, set `Content-Type: application/json` and check the `Encode` error; don't leak internal structs — map domain → response DTOs.

## Request validation

Validate at the boundary, in domain terms, before touching a service. Prefer explicit methods for clarity; a struct-tag validator (`go-playground/validator`) is fine for large DTOs — state the dependency.

```go
func (r CreateUserRequest) Validate() error {
    var errs []error
    if strings.TrimSpace(r.Email) == "" {
        errs = append(errs, errors.New("email is required"))
    } else if !strings.Contains(r.Email, "@") {
        errs = append(errs, errors.New("email is malformed"))
    }
    if len(r.Password) < 12 {
        errs = append(errs, errors.New("password must be at least 12 characters"))
    }
    return errors.Join(errs...) // nil if no errors; aggregates all failures — see errors-safety.md
}
```

## Error → HTTP status mapping

Centralize the mapping so every handler is consistent and internal errors never leak. Match on sentinels/typed errors from the domain (see `errors-safety.md`).

```go
type APIError struct {
    Status int    `json:"-"`
    Msg    string `json:"error"`
}
func (e *APIError) Error() string { return e.Msg }

func writeError(w http.ResponseWriter, err error) {
    var apiErr *APIError
    switch {
    case errors.As(err, &apiErr):
        writeJSON(w, apiErr.Status, apiErr)
    case errors.Is(err, domain.ErrNotFound):
        writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
    case errors.Is(err, domain.ErrConflict):
        writeJSON(w, http.StatusConflict, map[string]string{"error": "already exists"})
    case errors.Is(err, domain.ErrUnauthorized):
        writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
    default:
        slog.Error("unhandled error", "err", err)                    // log the detail server-side
        writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal error"}) // opaque to client
    }
}
```

| Domain condition | HTTP status |
|---|---|
| malformed input / validation failure | 400 Bad Request |
| missing/invalid credentials | 401 Unauthorized |
| authenticated but not permitted | 403 Forbidden |
| resource absent | 404 Not Found |
| uniqueness/version conflict | 409 Conflict |
| body too large | 413 Payload Too Large |
| upstream timeout / `context.DeadlineExceeded` | 504 Gateway Timeout |
| unexpected / unmapped | 500 Internal Server Error (opaque message) |

**Never** put internal error strings, stack traces, or SQL in the response body — log them, return an opaque message.

## Middleware chains

Middleware is `func(http.Handler) http.Handler`. Compose in order; wrap the whole mux.

```go
func Chain(h http.Handler, mws ...func(http.Handler) http.Handler) http.Handler {
    for i := len(mws) - 1; i >= 0; i-- { // apply so the first listed runs outermost
        h = mws[i](h)
    }
    return h
}

func RequestID(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        id := r.Header.Get("X-Request-ID")
        if id == "" {
            id = uuid.NewString()
        }
        ctx := context.WithValue(r.Context(), ctxKeyReqID{}, id) // request-scoped metadata only
        w.Header().Set("X-Request-ID", id)
        next.ServeHTTP(w, r.WithContext(ctx))
    })
}

// srv.Handler = Chain(mux, RequestID, Recover, Logging, Auth)
```

- Standard set: request-ID → panic recovery → structured logging (`slog`) → auth → rate-limit.
- A `Recover` middleware that turns a panic into 500 is the last-resort boundary — but fix the panic, don't rely on it (see `errors-safety.md`).
- Use a **private struct key** for context values (`type ctxKeyReqID struct{}`), never a bare string, to avoid collisions.

## gRPC & protobuf

Reach for gRPC when you own both client and server, want a typed contract, or need bidirectional streaming. Define the contract in `.proto`, generate with `buf` (preferred) or `protoc`.

```proto
service UserService {
  rpc GetUser(GetUserRequest) returns (User);
  rpc ListUsers(ListUsersRequest) returns (stream User); // server-streaming
}
```

```go
func (s *server) GetUser(ctx context.Context, req *pb.GetUserRequest) (*pb.User, error) {
    if req.GetId() == "" {
        return nil, status.Error(codes.InvalidArgument, "id is required")
    }
    u, err := s.svc.Get(ctx, req.GetId())
    if errors.Is(err, domain.ErrNotFound) {
        return nil, status.Error(codes.NotFound, "user not found")
    }
    if err != nil {
        return nil, status.Error(codes.Internal, "internal error") // opaque, like REST
    }
    return toProto(u), nil
}
```

### gRPC status codes (mirror the REST table)

| Condition | gRPC code |
|---|---|
| bad input | `codes.InvalidArgument` |
| unauthenticated | `codes.Unauthenticated` |
| not permitted | `codes.PermissionDenied` |
| missing | `codes.NotFound` |
| conflict | `codes.AlreadyExists` / `codes.Aborted` |
| deadline | `codes.DeadlineExceeded` |
| unexpected | `codes.Internal` (opaque) |

### Interceptors (gRPC middleware)

```go
grpc.NewServer(
    grpc.ChainUnaryInterceptor(recoveryInterceptor, loggingInterceptor, authInterceptor),
    grpc.ChainStreamInterceptor(streamLoggingInterceptor),
)
```

- Unary interceptors wrap request/response RPCs; stream interceptors wrap streaming RPCs — you usually need both chains.
- `context` carries the deadline and metadata (`metadata.FromIncomingContext`) — propagate it into downstream calls exactly as in REST.
- For streaming, always watch `stream.Context().Done()` to stop producing when the client disconnects (same discipline as SSE in `networking.md`).

## OpenAPI note

For REST, treat the OpenAPI spec as the contract. Two workflows: **spec-first** (write OpenAPI, generate server stubs + types with `oapi-codegen`) keeps handlers honest against the contract; **code-first** (generate the spec from annotated handlers with `swag`) is lighter but drifts more easily. Spec-first is preferred for public/partner APIs; validate requests against the spec in a middleware if the stakes are high.

## Pre-flight checklist

- [ ] Stdlib `ServeMux` (1.22 method+wildcard) used unless a framework is justified in writing
- [ ] Handlers are thin: decode → validate → call service → encode; logic lives in `internal/service`
- [ ] Request bodies capped with `http.MaxBytesReader`; JSON decoded with `DisallowUnknownFields` + single-value check
- [ ] Input validated at the boundary; aggregate errors with `errors.Join`
- [ ] Errors mapped centrally to status codes; internal detail logged, never returned to the client
- [ ] Middleware chain includes request-ID, panic recovery, structured logging, auth; context keys are private types
- [ ] gRPC returns proper `status.Error(codes.…)`; interceptor chains for unary + stream; deadlines propagated
- [ ] Streaming handlers/RPCs watch the request context for client disconnect

**Source:** [`net/http`](https://pkg.go.dev/net/http), [Routing enhancements for Go 1.22](https://go.dev/blog/routing-enhancements), [`encoding/json`](https://pkg.go.dev/encoding/json), [gRPC-Go](https://grpc.io/docs/languages/go/), [`google.golang.org/grpc/codes`](https://pkg.go.dev/google.golang.org/grpc/codes). Structure inspired by samber/cc-skills-golang (MIT), prose original.
