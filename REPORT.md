# StreamSocket — Technical Network Programming Report

**Project:** Secure Web-Based Remote Desktop Viewer
**Date:** March 2026
**Authors:** Development Team (4 Members)

---

## Division of Labor

| Section | Developer | Scope |
|---------|-----------|-------|
| **Section 1 — TCP Socket Architecture & Connection Lifecycle** | Developer A | Socket creation, binding, listening, accepting; socket option tuning (`SO_REUSEADDR`, `TCP_NODELAY`, `SO_SNDBUF`, `SO_RCVBUF`); TCP state transitions; TLS handshake and encryption layer |
| **Section 2 — Custom Framing Protocol & Data Transfer Pipeline** | Developer B | 4-byte length-prefixed framing; `recv_exact()` reassembly logic; JPEG frame encoding and delivery; frame capture module; performance benchmarking and throughput analysis |
| **Section 3 — WebSocket Bridge, Client Communication & Authentication** | Developer C | WebSocket Secure (WSS) handshake; FastAPI/uvicorn bridge server; TCP-to-WebSocket relay; browser client rendering; bcrypt authentication flow across both transport layers |
| **Section 4 — Concurrency, Database Logging & Failure Handling** | Developer D | Threading model for TCP server; asyncio model for WebSocket bridge; MySQL session/event logging; congestion handling; disconnection cleanup; resource leak prevention |

---

## Project Architecture Diagram

```
                          ┌─────────────────────────────┐
                          │     Browser Client (JS)      │
                          │  index.html + app.js         │
                          │  Canvas renderer, FPS meter  │
                          └─────────────┬───────────────┘
                                        │ WSS (TLS 1.2+, Port 8000)
                                        │ Binary WebSocket Frames
                          ┌─────────────▼───────────────┐
                          │   WebSocket Bridge Server    │
                          │   websocket_bridge/server.py │
                          │   FastAPI + uvicorn (asyncio)│
                          └─────────────┬───────────────┘
                                        │ TLS-encrypted TCP (Port 9999)
                                        │ 4-byte framed JPEG payloads
                          ┌─────────────▼───────────────┐
                          │    TCP Streaming Server      │
                          │    tcp_server/server.py      │
                          │    Threading + TLS + Auth    │
                          └──────┬──────────────┬───────┘
                                 │              │
                    ┌────────────▼──┐    ┌──────▼────────────┐
                    │ Frame Capture │    │   MySQL Database   │
                    │ capture/      │    │   (MariaDB)        │
                    │ screen.py     │    │   users + logs     │
                    │ OpenCV 30 FPS │    │   tables           │
                    └───────────────┘    └───────────────────┘
```

---

## Key Functionalities Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                    FUNCTIONAL COMPONENTS                          │
├──────────────┬──────────────┬───────────────┬────────────────────┤
│  Frame       │  Transport   │  Security     │  Observability     │
│  Pipeline    │  Layer       │  Layer        │  Layer             │
├──────────────┼──────────────┼───────────────┼────────────────────┤
│ OpenCV gen   │ TCP socket   │ TLS 1.2+     │ MySQL event logs   │
│ JPEG encode  │ 4-byte frame │ bcrypt auth  │ Per-event INSERT   │
│ Thread-safe  │ TCP_NODELAY  │ Self-signed  │ Log viewer (8080)  │
│ buffer       │ 1MB buffers  │ certificates │ FPS/Mbps metrics   │
│ 30 FPS @     │ WebSocket    │ AUTH proto   │ Color-coded UI     │
│ 1280×720     │ Secure (WSS) │ SQL injection│                    │
│              │              │ prevention   │                    │
└──────────────┴──────────────┴───────────────┴────────────────────┘
```

---

## Data / Packet Transfer Flow Diagram

```
Frame Generation          TCP Server              WS Bridge            Browser
      │                       │                       │                   │
      │  JPEG bytes (lock)    │                       │                   │
      ├──────────────────────►│                       │                   │
      │                       │                       │                   │
      │                       │◄──── TCP 3-Way Handshake (SYN/SYN-ACK/ACK)
      │                       │◄──── TLS Handshake (ClientHello/ServerHello)
      │                       │◄──── AUTH admin admin123\n                │
      │                       │────► AUTH_SUCCESS ───►│                   │
      │                       │                       │                   │
      │                       │                       │◄── WSS Handshake ─┤
      │                       │                       │    (HTTP Upgrade)  │
      │                       │                       │◄── AUTH via query  │
      │                       │                       │    params          │
      │                       │                       │                   │
      │                  ┌────┴────┐                  │                   │
      │                  │Broadcast│                  │                   │
      │                  │  Loop   │                  │                   │
      │                  └────┬────┘                  │                   │
      │                       │                       │                   │
      │                       │  [4B len][JPEG data]  │                   │
      │                       ├──────────────────────►│                   │
      │                       │  (TLS encrypted)      │  WS binary frame  │
      │                       │                       ├──────────────────►│
      │                       │                       │  (WSS encrypted)  │
      │                       │                       │                   │
      │                       │  Repeated at 30 FPS   │  Canvas render    │
      │                       │  ──────────────────►  │  ────────────────►│
      │                       │                       │                   │
      │                       │──── DB: log_event() ──┤──── DB: auth() ──┤
      │                       │     (async, non-      │                   │
      │                       │      blocking)        │                   │
```

---

## Section 1 — TCP Socket Architecture & Connection Lifecycle

### 1.1 Socket Creation and Binding

The TCP server (`tcp_server/server.py`) creates a standard IPv4 stream socket using `socket.AF_INET` and `socket.SOCK_STREAM`. The socket binds to `0.0.0.0:9999`, accepting connections on all network interfaces. A listen backlog of 5 is configured, defining the kernel queue size for pending connections before `accept()` is called.

### 1.2 Socket Option Configuration

Four socket options are applied to optimize the server for real-time streaming:

| Option | Level | Value | Purpose |
|--------|-------|-------|---------|
| `SO_REUSEADDR` | `SOL_SOCKET` | `1` | Permits immediate port rebinding after server restart by bypassing the TCP `TIME_WAIT` state. Without this, the 2MSL (Maximum Segment Lifetime) timeout — typically 60 seconds on Linux — would prevent rapid restarts during development or crash recovery. |
| `TCP_NODELAY` | `IPPROTO_TCP` | `1` | Disables Nagle's algorithm, which normally coalesces small writes into larger segments to improve bandwidth utilization. For video streaming, Nagle introduces unacceptable latency — buffering frame fragments until an MSS-sized segment accumulates or a delayed ACK timer fires (~40ms). With `TCP_NODELAY`, each `sendall()` call transmits immediately. |
| `SO_SNDBUF` | `SOL_SOCKET` | `1,048,576` (1 MB) | Enlarges the kernel send buffer from the default (~128 KB on Linux). JPEG frames range from 100–400 KB; a 1 MB buffer prevents `sendall()` from blocking when multiple frames are queued. |
| `SO_RCVBUF` | `SOL_SOCKET` | `1,048,576` (1 MB) | Enlarges the kernel receive buffer. On the bridge side, this absorbs jitter when the TCP backend sends frames faster than the WebSocket broadcast can relay them. |

Benchmark data from `experiments/ANALYSIS.md` quantifies the impact of `TCP_NODELAY`:

- **Enabled:** 32.41 ms average inter-frame time, 4.12 ms jitter, 24.5 Mbps throughput
- **Disabled:** 34.10 ms average inter-frame time, 68.55 ms jitter (16× worse), 142.10 ms max spike

The jitter increase without `TCP_NODELAY` is the critical metric — it causes visible stutter in the video stream despite only marginally lower throughput.

### 1.3 TLS Encryption Layer

After `accept()` returns a raw TCP socket, the server wraps it in TLS before any application data is exchanged. The implementation uses Python's `ssl` module:

```python
context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')
tls_sock = context.wrap_socket(raw_sock, server_side=True)
```

The TLS handshake sequence — ClientHello, ServerHello, Certificate, Key Exchange, Finished — completes before the authentication protocol begins. Self-signed RSA-2048 certificates with SHA-256 signatures are generated by `experiments/generate_certs.py` using the `cryptography` library. The Subject Alternative Name (SAN) extension includes `localhost` to satisfy modern TLS validation requirements.

**Measured TLS overhead** (from benchmark experiments):
- Throughput reduction: 25.2 Mbps → 23.8 Mbps (−5.5%)
- Latency increase: 31.10 ms → 34.50 ms (+3.40 ms per frame)
- FPS impact: 30.85 → 28.90 (−6.3%)

This overhead is acceptable for a security-critical application transmitting potentially sensitive screen content.

### 1.4 TCP State Transitions

The server manages the full TCP state machine. On connection:
1. **LISTEN** → Server socket waits for SYN
2. **SYN-RECEIVED** → Kernel responds with SYN-ACK
3. **ESTABLISHED** → Three-way handshake complete; TLS handshake begins

On disconnection, the `finally` block in `_handle_client` calls `socket.close()`, initiating:
1. **FIN_WAIT_1** → Server sends FIN
2. **FIN_WAIT_2** → Server receives ACK
3. **TIME_WAIT** → Server waits 2×MSL before releasing the 4-tuple

The `SO_REUSEADDR` option on the listening socket ensures the port can be rebound even while prior connections remain in `TIME_WAIT`.

---

## Section 2 — Custom Framing Protocol & Data Transfer Pipeline

### 2.1 The TCP Stream Problem

TCP provides a reliable, ordered byte stream — but it offers no message boundaries. A single `send()` of a 250 KB JPEG frame may arrive at the receiver as multiple fragments across several `recv()` calls, or conversely, data from two consecutive frames may be coalesced into a single `recv()` return. This is fundamental to TCP and is controlled by factors including the MSS (Maximum Segment Size, typically 1460 bytes on Ethernet), kernel buffer state, and network conditions.

### 2.2 Length-Prefixed Framing Protocol

The custom protocol in `tcp_server/protocol.py` solves this with a 4-byte length-prefixed framing scheme:

```
┌─────────────────────┬───────────────────────────────┐
│ 4 bytes: Frame      │ N bytes: JPEG Payload         │
│ Length (big-endian   │ (variable, typically          │
│ uint32, network      │  100–400 KB)                  │
│ byte order)          │                               │
└─────────────────────┴───────────────────────────────┘
```

The header is encoded with `struct.pack('>I', len(data))`:
- `>` specifies big-endian (network) byte order
- `I` specifies an unsigned 32-bit integer
- Maximum addressable frame size: 4,294,967,295 bytes (~4 GB)

Transmission uses `sendall()` which loops internally until all bytes are written to the kernel buffer, guaranteeing atomic delivery at the application level.

### 2.3 Reassembly with `recv_exact()`

The receiving side implements `recv_exact(sock, n)`, which loops until exactly `n` bytes have been buffered:

```python
def recv_exact(sock, n):
    buffer = b''
    while len(buffer) < n:
        chunk = sock.recv(n - len(buffer))
        if not chunk:
            return None  # Connection closed
        buffer += chunk
    return buffer
```

The receiver first calls `recv_exact(sock, 4)` to obtain the frame length, unpacks it with `struct.unpack('>I', header)`, then calls `recv_exact(sock, frame_length)` to read the complete JPEG payload. This two-phase read guarantees correct frame reconstruction regardless of TCP segmentation.

### 2.4 Frame Generation Pipeline

The `capture/screen.py` module generates 1280×720 JPEG frames at 30 FPS using OpenCV. Each frame is encoded with `cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 50])` at quality level 50 — a deliberate trade-off between visual clarity and bandwidth. The encoded bytes are stored in a thread-safe buffer protected by `threading.Lock`, and the TCP server's broadcast thread reads the latest frame via `get_latest_frame()`.

### 2.5 Benchmark Methodology

The `experiments/benchmark_client.py` tool connects as an authenticated TCP client and measures:
- **Throughput:** Total bytes received × 8 / elapsed time (Mbps)
- **Frame rate:** Frames received / elapsed time (FPS)
- **Inter-frame latency:** Time delta between successive frame arrivals (ms)
- **Jitter:** Standard deviation of inter-frame latency (ms)

Tests run for a configurable duration (default 15 seconds) with TLS enabled, providing statistically significant data for the socket option experiments documented in `experiments/ANALYSIS.md`.

---

## Section 3 — WebSocket Bridge, Client Communication & Authentication

### 3.1 WebSocket Secure (WSS) Handshake

The WebSocket bridge (`websocket_bridge/server.py`) is a FastAPI application served by uvicorn with TLS enabled. When a browser client navigates to `https://localhost:8000/client/index.html`, the connection is already encrypted via HTTPS using a separate certificate pair (`wss_cert.pem`, `wss_key.pem`).

The WebSocket upgrade occurs when the client opens a connection to the `/ws` endpoint. The HTTP handshake follows RFC 6455:

1. **Client sends HTTP GET** with headers:
   - `Connection: Upgrade`
   - `Upgrade: websocket`
   - `Sec-WebSocket-Key: <base64-random>`
   - `Sec-WebSocket-Version: 13`
2. **Server responds HTTP 101 Switching Protocols** with:
   - `Upgrade: websocket`
   - `Connection: Upgrade`
   - `Sec-WebSocket-Accept: <SHA-1 hash of key + magic GUID>`
3. The TCP connection is now a full-duplex WebSocket channel.

Since this occurs over an existing TLS connection, the result is WSS — WebSocket Secure.

### 3.2 TCP-to-WebSocket Relay Architecture

The bridge maintains two concurrent communication channels:

1. **Upstream (TCP):** An asyncio TCP connection to the backend server at `127.0.0.1:9999` using `asyncio.open_connection()` with TLS. The bridge authenticates using `STREAM_USER`/`STREAM_PASSWORD` from the `.env` file via the `AUTH <user> <pass>\n` protocol.

2. **Downstream (WebSocket):** Multiple browser clients connected via WSS. A `clients` set tracks active WebSocket connections.

A background asyncio task continuously reads framed JPEG data from the TCP connection using `reader.readexactly(4)` (header) and `reader.readexactly(data_size)` (payload), then broadcasts each frame to all WebSocket clients using `asyncio.gather()` with `return_exceptions=True` to prevent one failing client from blocking others.

### 3.3 Browser Client

The client (`client/app.js`) constructs a WSS URL with credentials as query parameters:

```javascript
const wsUrl = `wss://${location.host}/ws?username=${user}&password=${pass}`;
```

The WebSocket is configured with `binaryType = "blob"` to receive binary JPEG frames. Each incoming message is converted to an image via `URL.createObjectURL(blob)` and drawn onto an HTML5 `<canvas>` element. A `requestAnimationFrame`-based FPS counter provides real-time performance feedback.

### 3.4 Authentication Flow

Authentication is enforced at two boundaries:

**TCP Layer (server ↔ bridge):**
1. Client sends `AUTH <username> <password>\n` as UTF-8 over TLS
2. Server queries `SELECT id, password_hash FROM users WHERE username = %s` (parameterized, preventing SQL injection)
3. Server verifies with `bcrypt.checkpw(password.encode(), stored_hash.encode())`
4. Server responds `AUTH_SUCCESS` or `AUTH_FAILED`
5. On failure: event logged to database, socket closed

**WebSocket Layer (bridge ↔ browser):**
1. Browser passes `username` and `password` as URL query parameters
2. Bridge calls `DatabaseAdapter().authenticate_user(username, password)`
3. On failure: WebSocket closed with code `1008` (Policy Violation)

Both layers use bcrypt for password verification against the MySQL `users` table. The database stores only bcrypt hashes — never plaintext passwords.

---

## Section 4 — Concurrency, Database Logging & Failure Handling

### 4.1 TCP Server Concurrency Model (Threading)

The TCP server uses a thread-per-client model:

- **Main thread:** Runs the `accept()` loop. Each new connection spawns a daemon `threading.Thread` running `_handle_client()`.
- **Broadcast thread:** A dedicated daemon thread runs `_broadcast_loop()`, reading the latest frame from the capture module and sending it to all clients every 33.33 ms (1/30 second).
- **Shared state:** The `self.clients` list is protected by `threading.Lock`. All mutations (add on auth success, remove on disconnect) acquire the lock.

Python's Global Interpreter Lock (GIL) does not impair this model because the critical operations — `socket.sendall()`, `socket.recv()`, `ssl.write()` — release the GIL during I/O, allowing true concurrency on socket operations.

### 4.2 WebSocket Bridge Concurrency Model (Asyncio)

The bridge uses Python's `asyncio` event loop via FastAPI/uvicorn:

- A single thread handles all WebSocket connections cooperatively using non-blocking I/O.
- `asyncio.create_task()` launches the TCP relay as a background coroutine.
- `asyncio.gather(*send_coroutines, return_exceptions=True)` broadcasts frames to all WebSocket clients concurrently without blocking on any individual slow client.

This model avoids the overhead of thread creation per client while providing efficient I/O multiplexing — appropriate for the WebSocket layer where connections are long-lived and I/O-bound.

### 4.3 Database Logging Architecture

All significant network events are recorded in the MySQL `logs` table:

| Event Type | Trigger | Data Captured |
|------------|---------|---------------|
| `CONNECT_SUCCESS` | Client authenticated | username, IP address |
| `AUTH_FAILED` | Wrong credentials | username, IP address |
| `DISCONNECT` | Clean disconnection | username, IP address |
| `DISCONNECT_UNAUTHORIZED` | Failed auth attempt | username, IP address |
| `ERROR` | Unexpected exception | username, IP, error message |

**Critical design decision:** Each `log_event()` call opens a fresh MySQL connection, executes a single `INSERT`, commits, and closes the connection. This isolation ensures:
1. A slow or failed database write never blocks the video broadcast loop.
2. Connection pooling issues (stale connections, lock contention) are avoided entirely.
3. Each log entry is an independent, atomic transaction.

The `logs` table schema includes an auto-incrementing primary key, `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` for automatic audit trails, and `VARCHAR(45)` for IP addresses to accommodate both IPv4 and IPv6.

### 4.4 Congestion Handling

Each client socket has a 0.5-second send timeout configured via `settimeout(0.5)`. When the kernel send buffer is full (indicating a slow client that cannot consume frames fast enough), `sendall()` raises `socket.timeout`. The server catches this exception and silently drops the frame **for that client only** — all other clients continue receiving frames at full rate.

Benchmark data confirms this mechanism:
- **Without timeout:** A single slow client blocks the entire broadcast thread
- **With 0.5s timeout:** Slow client receives ~12 FPS; fast clients maintain 30 FPS

This is a graceful degradation strategy — clients with insufficient bandwidth receive a lower-fidelity stream rather than causing system-wide stalls.

### 4.5 Disconnection & Resource Cleanup

The `_handle_client` method uses a `try/finally` pattern that guarantees cleanup regardless of exit path:

```python
try:
    # Authentication and streaming logic
except (BrokenPipeError, ConnectionResetError):
    # Client disconnected unexpectedly
except Exception as e:
    # Log unexpected errors
finally:
    with self.lock:
        if client_sock in self.clients:
            self.clients.remove(client_sock)
    client_sock.close()
    self.db.log_event("DISCONNECT", username, addr[0])
```

`BrokenPipeError` (write to closed socket) and `ConnectionResetError` (RST received) are caught explicitly to handle abrupt client disconnections. The `finally` block unconditionally:
1. Acquires the lock and removes the client from the broadcast list
2. Calls `socket.close()`, triggering the TCP FIN sequence
3. Logs the disconnection event to the database

This prevents file descriptor leaks and ensures the TCP stack transitions cleanly through `FIN_WAIT → TIME_WAIT → CLOSED`.

### 4.6 Unauthorized Access Handling

When authentication fails, the server:
1. Sends `AUTH_FAILED` to the client
2. Logs `DISCONNECT_UNAUTHORIZED` with the client's IP address to the database
3. Immediately closes the socket

The client is never added to the broadcast list, so no frame data is ever transmitted to unauthenticated connections. Database logging of failed attempts provides an audit trail for security monitoring.

---

## Summary of Network Endpoints

| Component | Protocol | Port | Encryption | Concurrency |
|-----------|----------|------|------------|-------------|
| TCP Server | TCP + Custom Framing | 9999 | TLS (ssl module) | threading (per-client) |
| WebSocket Bridge | WSS (WebSocket Secure) | 8000 | TLS (uvicorn) | asyncio (event loop) |
| Log Viewer | HTTP | 8080 | None (localhost only) | uvicorn |
| MySQL Database | MySQL Protocol | 3306 | None (localhost) | Per-query connections |

---

## Dependencies

| Package | Role in Network Stack |
|---------|----------------------|
| `fastapi` + `uvicorn` | WebSocket server, ASGI framework, TLS termination |
| `websockets` | WebSocket protocol implementation |
| `mysql-connector-python` | Database connectivity for auth and logging |
| `bcrypt` | Password hashing for authentication |
| `opencv-python-headless` | JPEG frame encoding |
| `cryptography` | TLS certificate generation (RSA-2048, SHA-256) |
| `python-dotenv` | Environment variable management for credentials |
