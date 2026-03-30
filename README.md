# Secure Remote Desktop Streaming System

A real-time secure screen streaming system demonstrating low-level TCP socket programming, custom framing protocols, TLS encryption, WebSocket bridging, bcrypt authentication, and persistent database logging.

---

## Architecture Overview

```
[Frame Generator] → [TCP Server :9999, TLS] → [WebSocket Bridge :8000, WSS] → [Browser Canvas]
                           ↕                              ↕
                    [MySQL Database]              [MySQL Database]
                  (auth + event logs)           (session logs)
```

The system has two servers and a web client:

- **TCP Server** (`tcp_server/server.py`) — Core streaming backend. Captures frames, wraps them in a custom 4-byte framing protocol, encrypts via TLS, and multicasts to connected clients over raw TCP sockets.
- **WebSocket Bridge** (`websocket_bridge/server.py`) — FastAPI/uvicorn server. Connects to the TCP backend as an authenticated client, receives framed JPEGs, and broadcasts them to browser clients over WSS (WebSocket Secure).
- **Web Client** (`client/index.html` + `client/app.js`) — Login form and canvas-based stream viewer with live FPS counter.

---

## Prerequisites

### 1. System — Start MariaDB

```bash
sudo systemctl start mariadb
```

MariaDB root must use password authentication. If you get `Access denied (1698)`:

```bash
sudo mysql -u root
ALTER USER 'root'@'localhost' IDENTIFIED BY 'Admin';
FLUSH PRIVILEGES;
EXIT;
```

### 2. Python — Create virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install cryptography pillow
```

### 3. Configuration — Create `.env`

Create a file named `.env` in the project root:

```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=Admin
DB_NAME=remote_stream

STREAM_USER=admin
STREAM_PASSWORD=admin123
```

### 4. Certificates — Generate TLS certs

```bash
# TCP server certs
cd tcp_server && python ../experiments/generate_certs.py && cd ..

# WebSocket bridge WSS certs
cd websocket_bridge && python generate_certs.py && cd ..
```

---

## Running the System

You need three terminal windows. Activate the venv in each:

```bash
source .venv/bin/activate
```

### Terminal 1 — Database setup (first time only)

```bash
python db/setup_db.py
```

Creates the `remote_stream` database, `users` and `logs` tables, and seeds the default user (`admin` / `admin123`).

### Terminal 2 — TCP Streaming Server

```bash
cd tcp_server
python server.py
```

Output:
```
[*] TCP Server Listening on 0.0.0.0:9999
[*] TLS Encryption Enabled
```

### Terminal 3 — WebSocket Bridge

```bash
cd websocket_bridge
python server.py
```

Output includes:
```
INFO: Uvicorn running on https://0.0.0.0:8000
[DEBUG] Auth response from TCP server: b'AUTH_SUCCESS'
Bridge connected to TCP Backend. Ready to broadcast to WS clients.
```

### Browser — Connect as Client

1. Navigate to `https://localhost:8000/client/index.html`
   - The browser will warn about the self-signed certificate — click **Advanced → Accept the Risk and Continue**
2. Log in with:
   - **Username:** `admin`
   - **Password:** `admin123`
3. The canvas will show the live stream with Status: **Connected** and FPS counter.

### Optional — Log Viewer

```bash
python log_viewer.py
```

Open `http://localhost:8080` to view color-coded session events (logins, disconnects, auth failures).

---

## How It Works

### 1. Frame Generation

`capture/screen.py` generates 1280×720 JPEG frames at 30 FPS using OpenCV. Each frame contains a live timestamp (millisecond precision), frame counter, hostname, and animated content — demonstrating the stream is genuinely real-time. Frames are stored in a thread-safe buffer (`threading.Lock`) for the TCP server to read.

> **Note on Wayland:** The original implementation used `mss` for screen capture. On GNOME Wayland, `mss` fails because the Wayland compositor blocks `XGetImage` (an X11 protocol call) even through XWayland. The capture module was rewritten to use OpenCV frame generation, which has no OS display dependencies. See `CHANGES.md` for the full diagnosis and fix history.

### 2. TCP Server & Custom Framing Protocol

`tcp_server/server.py` reads the latest JPEG frame and sends it to all connected clients. Because TCP is a stream protocol with no message boundaries, large JPEG frames (often 100–400 KB) arrive fragmented across multiple `recv()` calls.

`tcp_server/protocol.py` solves this with a **4-byte framing header**:

```
[ 4 bytes: frame length (big-endian uint32) ][ N bytes: JPEG data ]
```

The receiver calls `recv_exact(n)` which loops until exactly `n` bytes are buffered, guaranteeing complete frame reconstruction regardless of TCP fragmentation.

### 3. Socket Options

The TCP server configures sockets for low-latency streaming:

| Option | Value | Effect |
|---|---|---|
| `TCP_NODELAY` | 1 | Disables Nagle's algorithm — sends frames immediately without coalescing |
| `SO_SNDBUF` | 1 MB | Increases kernel send buffer — reduces stalls under burst load |
| `SO_RCVBUF` | 1 MB | Increases kernel receive buffer — absorbs jitter |
| `SO_REUSEADDR` | 1 | Allows immediate port reuse after restart, bypassing `TIME_WAIT` |

### 4. TLS Encryption

The TCP server wraps the raw socket in TLS using Python's `ssl` module:

```python
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')
tls_sock = context.wrap_socket(raw_sock, server_side=True)
```

The TLS handshake occurs after `accept()` and before any data is sent. All frame data (JPEG bytes) is encrypted in transit. The WebSocket bridge (`websocket_bridge/server.py`) also uses TLS (WSS) for the browser connection using a separate certificate pair.

### 5. Authentication

When a client connects, it must send:

```
AUTH <username> <password>\n
```

The server calls `db/auth.py` which queries the MySQL `users` table and verifies the password with `bcrypt.checkpw()`. On success it returns `b'AUTH_SUCCESS'` and the client is added to the broadcast list. On failure it returns `b'AUTH_FAILED'`, logs the event, and closes the socket.

The WebSocket bridge authenticates with the TCP server using `STREAM_USER`/`STREAM_PASSWORD` from `.env`. Browser clients authenticate via WebSocket query parameters which the bridge validates.

### 6. Concurrency Model

- **TCP Server:** Uses `threading.Thread` — one thread per connected client. A `threading.Lock` protects the shared client list. Each client thread handles its own frame send loop with a 0.5s send timeout (congestion handling — slow clients get frames dropped rather than blocking others).
- **WebSocket Bridge:** Uses `asyncio` — the FastAPI/uvicorn event loop handles all WebSocket connections concurrently within a single thread. An `asyncio.Lock` protects the WebSocket broadcast list.

### 7. Database Logging

`db/auth.py` logs all significant events to the MySQL `logs` table:

| Event Type | Trigger |
|---|---|
| `CONNECT_SUCCESS` | Client authenticated successfully |
| `AUTH_FAILED` | Wrong credentials |
| `DISCONNECT` | Client disconnected cleanly |
| `ERROR` | Unexpected socket errors |

Each log write uses a short-lived database connection opened and closed independently. This ensures a slow or failed DB write never stalls the video stream.

### 8. Congestion & Disconnection Handling

- **Congestion:** Each client socket has `settimeout(0.5)`. If the TCP send buffer is full (slow client), the send raises `socket.timeout` and that frame is silently dropped for that client only. All other clients are unaffected.
- **Disconnection:** `BrokenPipeError` and `ConnectionResetError` are caught in the client handler thread. A `finally` block unconditionally removes the client from the broadcast list and calls `socket.close()`, ensuring no file descriptor leaks and proper TCP `FIN_WAIT → TIME_WAIT` transitions.

---

## Project Structure

```
StreamSocket/
├── capture/screen.py          # Frame generation (OpenCV, 30 FPS)
├── tcp_server/
│   ├── server.py              # TCP streaming server (TLS, threading, auth)
│   └── protocol.py            # 4-byte framing protocol
├── websocket_bridge/
│   ├── server.py              # FastAPI WebSocket bridge (WSS)
│   └── generate_certs.py      # WSS certificate generator
├── db/
│   ├── auth.py                # bcrypt auth + MySQL event logging
│   ├── setup_db.py            # Schema creation + user seeding
│   └── schema.sql             # DDL for users and logs tables
├── client/
│   ├── index.html             # Login UI
│   └── app.js                 # WebSocket client + canvas renderer
├── experiments/
│   ├── ANALYSIS.md            # Deep-dive: TCP, TLS, framing, socket options
│   ├── benchmark_client.py    # Throughput/latency benchmarking tool
│   └── generate_certs.py      # TCP server certificate generator
├── log_viewer.py              # Localhost log viewer (port 8080)
├── .env                       # Credentials (not in git)
├── requirements.txt           # Python dependencies
├── CHANGES.md                 # Change log and fix history
└── REQUIREMENTS_MAPPING.md    # Rubric requirements → implementation mapping
```
