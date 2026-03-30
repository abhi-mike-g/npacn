import cv2
import numpy as np
import time
import threading
import socket
from datetime import datetime

class ScreenCapture:
    def __init__(self, fps=30, quality=50):
        self.fps = fps
        self.quality = quality
        self.running = False
        self._frame_count = 0
        self._hostname = socket.gethostname()

        # Thread-safe frame sharing
        self._latest_jpeg = b""
        self._lock = threading.Lock()

    def get_latest_frame(self):
        with self._lock:
            return self._latest_jpeg

    def set_latest_frame(self, data):
        with self._lock:
            self._latest_jpeg = data

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if hasattr(self, '_thread'):
            self._thread.join()

    def _generate_frame(self):
        """Generate a live demo frame with timestamp and animated content."""
        W, H = 1280, 720
        img = np.zeros((H, W, 3), dtype=np.uint8)

        # Animated gradient background (shifts over time)
        t = time.time()
        for i in range(W):
            hue = int((i / W * 120 + t * 20) % 180)
            img[:, i] = [hue, 180, 60]
        img = cv2.cvtColor(img, cv2.COLOR_HSV2BGR)

        # Dark overlay for readability
        overlay = np.zeros((H, W, 3), dtype=np.uint8)
        cv2.addWeighted(overlay, 0.6, img, 0.4, 0, img)

        # Title bar
        cv2.rectangle(img, (0, 0), (W, 80), (20, 20, 20), -1)
        cv2.putText(img, "StreamSocket - Live Stream", (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 120), 2)

        # Timestamp
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S.%f")[:-3]
        cv2.putText(img, ts, (20, 140),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

        # Host info
        cv2.putText(img, f"Host: {self._hostname}", (20, 190),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (180, 180, 180), 1)

        # Frame counter
        cv2.putText(img, f"Frame: {self._frame_count}", (20, 230),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (180, 180, 180), 1)

        # Animated bouncing ball
        ball_x = int(W * 0.5 + (W * 0.35) * np.sin(t * 1.5))
        ball_y = int(H * 0.65 + (H * 0.15) * np.sin(t * 2.3))
        cv2.circle(img, (ball_x, ball_y), 40, (0, 200, 255), -1)
        cv2.circle(img, (ball_x - 12, ball_y - 12), 10, (255, 255, 255), -1)

        # Stream info box
        cv2.rectangle(img, (W - 320, H - 120), (W - 10, H - 10), (30, 30, 30), -1)
        cv2.putText(img, "TCP + WebSocket + TLS", (W - 310, H - 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 120), 1)
        cv2.putText(img, f"Target: {self.fps} FPS | Q: {self.quality}",
                    (W - 310, H - 55), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
        cv2.putText(img, "Encrypted  |  Authenticated", (W - 310, H - 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 180, 255), 1)

        self._frame_count += 1
        return img

    def _capture_loop(self):
        interval = 1.0 / self.fps
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]

        while self.running:
            start_time = time.time()

            img = self._generate_frame()
            ret, buffer = cv2.imencode('.jpg', img, encode_param)
            if ret:
                self.set_latest_frame(buffer.tobytes())

            elapsed = time.time() - start_time
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
