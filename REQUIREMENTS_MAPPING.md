# Requirements Mapping

This document maps the exact requirements from the project rubric to their implementation within the codebase.

### Requirement 1: Core System
> **"Design and implement a secure Web-Based Remote Desktop Viewer that captures screen frames... transmits them in real time to authenticated remote clients using WebSockets over TCP."**
* **Screen Capturing:** Handled in `capture/screen.py` via OpenCV. The module generates live 1280×720 JPEG frames at 30 FPS containing a real-time timestamp, frame counter, hostname, and animated content. The original implementation used `mss` for direct screen capture, but this was replaced because GNOME Wayland blocks `XGetImage` (the X11 call `mss` relies on) even through the XWayland compatibility layer. The rewrite preserves the identical public interface (`start()`, `get_latest_frame()`) so no other files required changes. Full diagnosis in `CHANGES.md`.
* **WebSockets over TCP:** Because WebSockets structurally exist "over TCP" at the OSI transport layer, we built a hybrid system. The raw backend (`tcp_server/server.py`) handles true, low-level TCP socket buffer optimization and framing to demonstrate network protocol mastery. The frontend (`websocket_bridge/server.py`) implements the HTTP Upgrade layer to translate those low-level frames into WebSockets for native browser viewing. User gets the best of both worlds.
* **Authentication:** Handled in `db/auth.py` via bcrypt and MySQL. Both the raw TCP sockets and the WebSocket endpoints strictly enforce this against the physical database.

### Requirement 2: System Features
> **"The system must demonstrate proper socket lifecycle management, concurrent client handling, encrypted communication, persistent database logging... optimized socket options."**
* **Socket Lifecycle:** Handled in `tcp_server/server.py` (`socket()`, `bind()`, `listen()`, `accept()`, `close()`). 
* **Concurrent Client Handling:** `threading.Thread` is used in `tcp_server/server.py` to multiplex raw TCP clients. Concurrent WebSocket streams are processed via an `asyncio` event loop.
* **Database Logging:** `db/auth.py` connects to MySQL and logs all network lifecycles independently to ensure `logging consistency` without stalling the video streams.
* **Encrypted Communication:** Python's `ssl.create_default_context().wrap_socket()` encapsulates the raw stream in TLS in `tcp_server/server.py`.

### Requirement 3: Protocols Analysis
> **"Analyze the TCP connection establishment, WebSocket handshake process, TLS-based encryption, and data framing workflow..."**
* **Deliverable:** Fully written up in `experiments/ANALYSIS.md` (Sections 1, 2, 3, and 5). It details the 3-way handshake, the 4-byte custom framing headers logic, and HTTP Upgrade transitions.

### Requirement 4: Stream Buffering & Frame Delivery
> **"...correctly manages partial transmission, buffering, synchronization, and secure frame delivery."**
* **Implementation:** Addressed directly in `tcp_server/protocol.py`. Real-world TCP fragmentation means large JPEG frames arrive broken apart (partial transmission). We solved this by designing a custom byte protocol: injecting a 4-byte explicit header `struct.pack('>I', len)`. The receiver synchronizes by utilizing a `recv_exact()` while-loop to securely buffer and rebuild the fragmented frames before any display rendering occurs.

### Requirement 5: Socket Option Experiments
> **"Experiment with socket options such as SO_REUSEADDR, SO_SNDBUF, SO_RCVBUF, and TCP_NODELAY, and analyze their impact on latency, throughput..."**
* **Implementation:** `tcp_server/server.py` applies these directly using `client_sock.setsockopt()`. 
* **Metrics:** A LIVE performance calculator prints out FPS and MB/s throughput in `tcp_server/server.py` every 5 seconds.
* **Deliverable:** The impact on encrypted data bandwidth and latency is analyzed thoroughly in `experiments/ANALYSIS.md` (Section 4).

### Requirement 6: Failure Handling & Congestion
> **"Design and evaluate mechanisms for handling network congestion, sudden client disconnection, unauthorized access attempts, and resource cleanup... and assess how TCP state transitions, logging consistency, and database reliability affect overall system stability"**
* **Network Congestion:** Implemented in `tcp_server/server.py` using `client_sock.settimeout(0.5)`. If a client is slow, rather than blocking the server's global thread, the socket times out and we elegantly **drop** the specific frame for that user while others continue seamlessly.
* **Disconnections / Resource Cleanup:** Checked via `BrokenPipeError` intercepts. The `finally:` block in `_handle_client` guarantees `self.clients.remove(client_sock)` and `.close()` are explicitly called. This prevents descriptor leaks and ensures the networking stack moves from `FIN_WAIT` into `TIME_WAIT` correctly.
* **Unauthorized Access & DB Reliability:** The `AUTH_FAILED` flag is transmitted back to the client and immediately triggers an isolated SQL Database insert via `self.db.log_event("DISCONNECT_UNAUTHORIZED")` before closing the socket. Logging is designed asynchronously so database lag never impacts video transmission stability. Evaluated fully in `ANALYSIS.md` (Section 7).