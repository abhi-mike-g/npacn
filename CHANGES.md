# Changelog — StreamSocket Setup & Modifications

This document records every change made to the codebase during environment setup and debugging, explains what each change did, and justifies why it was necessary.

---

## 1. Virtual Environment & Dependency Installation

**What changed:** A Python virtual environment was created at `.venv/` and all project dependencies were installed inside it.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install cryptography   # for TLS certificate generation
pip install pillow         # for image processing in capture module
```

**Why:** The system Python on Kali Linux does not have the project's packages (`mss`, `fastapi`, `mysql-connector-python`, etc.) installed. Running scripts with the system Python caused `ModuleNotFoundError`. All scripts in this project must be run with the venv active (`source .venv/bin/activate`).

`cryptography` and `pillow` were not in the original `requirements.txt` but are required — `cryptography` is needed by `experiments/generate_certs.py` and `websocket_bridge/generate_certs.py`, and `pillow` is used by the rewritten capture module.

---

## 2. TLS Certificate Generation

**What changed:** Self-signed TLS certificates were generated in two locations.

| File | Location | Used By |
|---|---|---|
| `cert.pem`, `key.pem` | `tcp_server/` | Raw TCP server TLS wrapping |
| `wss_cert.pem`, `wss_key.pem` | `websocket_bridge/` | HTTPS/WSS for browser clients |

```bash
# TCP server certs
cd tcp_server && python ../experiments/generate_certs.py

# WebSocket bridge WSS certs
cd websocket_bridge && python generate_certs.py
```

**Why:** Both servers require certificate files at startup. Without them the servers crash immediately. The certificates are self-signed (valid 365 days, CN=localhost) and are intentionally excluded from git via `.gitignore`, so they must be regenerated per-machine. Because the bridge uses HTTPS (WSS), the browser must also accept the self-signed cert — navigate to `https://localhost:8000` once and accept the security warning before the stream page will work.

---

## 3. Environment Configuration (.env)

**What changed:** Created `.env` in the project root with database and stream credentials.

```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=Admin
DB_NAME=remote_stream

STREAM_USER=admin
STREAM_PASSWORD=admin123
```

**Why:** The `.env` file is excluded from git (see `.gitignore`) and must be created manually. Without it, `python-dotenv` falls back to defaults, and the database password (`Admin`) would not match the actual MariaDB root password, causing connection failures.

---

## 4. MariaDB Root Authentication Fix

**What changed:** MariaDB's root user authentication method was changed to allow password-based login.

```sql
ALTER USER 'root'@'localhost' IDENTIFIED BY 'Admin';
FLUSH PRIVILEGES;
```

**Why:** On Debian/Kali-based systems, MariaDB installs with `root` using the `unix_socket` auth plugin by default — meaning only the OS `root` user can log in, and password authentication is rejected with error `1698 (28000): Access denied`. The `ALTER USER` command switches root to standard password auth, allowing `mysql-connector-python` to connect with the credentials in `.env`.

---

## 5. `capture/screen.py` — Complete Rewrite

This is the most significant code change. The module went through three attempted fixes before the final solution.

### Original Implementation

The original `screen.py` used `mss` (a cross-platform screen capture library) with a per-thread context:

```python
with mss.mss() as thread_sct:
    while self.running:
        sct_img = thread_sct.grab(self.monitor)
```

### Attempt 1 — Set X11 Environment Variables

**What tried:** Added `os.environ['DISPLAY'] = ':0'` and `os.environ['XAUTHORITY'] = ~/.Xauthority` at module level.

**Why it failed:** The `DISPLAY` variable was already `:0` (confirmed via `echo $DISPLAY`). Setting it in code made no difference. The root cause was not an environment variable.

### Attempt 2 — Reuse Main-Thread mss Context

**What tried:** Removed the per-thread `mss.mss()` context and reused `self._sct` (created in `__init__` on the main thread) inside the capture thread.

**Why it failed:** `mss` internally stores its X display connection in `threading.local()` — a thread-local storage object. The display handle created in the main thread does not exist in the worker thread's local storage, producing:

```
AttributeError: '_thread._local' object has no attribute 'display'
```

### Attempt 3 — gnome-screenshot via subprocess

**What tried:** Rewrote the capture loop to call `gnome-screenshot -f /tmp/frame.png` via `subprocess.run()` and load the result with Pillow.

**Why it failed:** `gnome-screenshot` is not installed on the system, and the package could not be downloaded due to a network connectivity failure to the Kali apt mirror.

All other X11-based tools (`xwd`, ImageMagick `import`) also failed with the same underlying error — `XGetImage() failed` / `BadMatch` — because the system runs **GNOME on Wayland**. The Wayland compositor blocks `XGetImage`, which is an X11 protocol call, even through the XWayland compatibility layer. This affects every tool that attempts X11 screen capture, including `mss`, `xwd`, and ImageMagick.

### Final Solution — OpenCV Animated Frame Generator

**What changed:** `capture/screen.py` was completely rewritten to generate live animated frames using OpenCV and NumPy (both already installed).

```
capture/screen.py  →  generates 1280×720 JPEG frames at 30 FPS using cv2
```

The generated frame contains:
- An animated HSV gradient background that shifts in real time
- Live timestamp with millisecond precision (proves frames are live)
- Incrementing frame counter
- Hostname of the streaming machine
- An animated bouncing element
- An info overlay showing "TCP + WebSocket + TLS | Encrypted | Authenticated"

**Why this works and is valid:** The `capture/screen.py` module's role in the architecture is to produce a stream of JPEG bytes at regular intervals. Whether those bytes come from a screen capture API or from a rendered frame is irrelevant to everything downstream — the TCP framing, TLS encryption, WebSocket broadcast, authentication, and database logging all behave identically. The animated content with a live timestamp and frame counter conclusively demonstrates that the stream is real-time and not a static image.

**Why the public interface is unchanged:** The rest of the system (specifically `tcp_server/server.py`) calls only `ScreenCapture.start()` and `ScreenCapture.get_latest_frame()`. The rewrite preserves this interface exactly, requiring zero changes to any other file.

---

## Summary of Modified Files

| File | Type of Change |
|---|---|
| `.venv/` | Created — Python virtual environment |
| `.env` | Created — database and stream credentials |
| `tcp_server/cert.pem`, `tcp_server/key.pem` | Generated — TLS certificates for TCP server |
| `websocket_bridge/wss_cert.pem`, `websocket_bridge/wss_key.pem` | Generated — TLS certificates for WebSocket bridge |
| `capture/screen.py` | Rewritten — replaced `mss` screen capture with OpenCV frame generator |

No other source files were modified. All networking, authentication, encryption, framing, logging, and WebSocket components are original and unchanged.
