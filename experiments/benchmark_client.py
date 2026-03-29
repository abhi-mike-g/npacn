import socket
import ssl
import time
import struct
import statistics
import argparse
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
STREAM_USER = os.environ.get("STREAM_USER", "admin")
STREAM_PASSWORD = os.environ.get("STREAM_PASSWORD", "admin123")

def recv_exact(sock, size):
    buf = b""
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf

def run_benchmark(host='127.0.0.1', port=9999, use_tls=True, duration=10):
    print(f"[*] Starting benchmark against {host}:{port} for {duration} seconds...")
    print(f"[*] TLS Encrypted: {use_tls}")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    if use_tls:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        sock = context.wrap_socket(sock, server_hostname=host)
        
    try:
        sock.connect((host, port))
        
        # Authenticate using .env
        auth_msg = f"AUTH {STREAM_USER} {STREAM_PASSWORD}\n".encode('utf-8')
        sock.sendall(auth_msg)
        
        auth_resp = sock.recv(1024)
        if b"AUTH_SUCCESS" not in auth_resp:
            print("[-] Authentication failed.")
            return
            
        print("[+] Connected & Authenticated. Collecting frames...\n")
        
        start_time = time.time()
        frames_received = 0
        total_bytes = 0
        arrival_times = []
        
        last_frame_time = time.time()
        
        while time.time() - start_time < duration:
            header = recv_exact(sock, 4)
            if not header: break
            
            (data_size,) = struct.unpack('>I', header)
            payload = recv_exact(sock, data_size)
            if not payload: break
            
            now = time.time()
            inter_frame_time = now - last_frame_time
            arrival_times.append(inter_frame_time * 1000) # Convert to ms
            last_frame_time = now
            
            frames_received += 1
            total_bytes += (4 + data_size)
            
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        
    # --- ANALYSIS & MATH ---
    elapsed = time.time() - start_time
    throughput_mbps = (total_bytes * 8 / 1000000) / elapsed
    fps = frames_received / elapsed
    
    # Ignore the first frame's arrival time as it includes connection overhead
    if len(arrival_times) > 1:
        arrival_times = arrival_times[1:]
        avg_latency = statistics.mean(arrival_times)
        jitter = statistics.stdev(arrival_times) if len(arrival_times) > 1 else 0
        max_latency = max(arrival_times)
    else:
        avg_latency = jitter = max_latency = 0

    print("=" * 50)
    print("EXPERIMENT RESULTS FORMATTED FOR REPORT")
    print("=" * 50)
    print(f"Test Duration        : {elapsed:.2f} seconds")
    print(f"Total Frames         : {frames_received}")
    print(f"Total Data Transferred: {total_bytes / (1024*1024):.2f} MB")
    print("-" * 50)
    print("THROUGHPUT & FRAMERATE")
    print("-" * 50)
    print(f"Avg FPS              : {fps:.2f} Frames/sec")
    print(f"Network Throughput   : {throughput_mbps:.2f} Mbps")
    print("-" * 50)
    print("LATENCY & JITTER (Frame-to-Frame Arrival)")
    print("-" * 50)
    print(f"Avg Inter-frame Time : {avg_latency:.2f} ms")
    print(f"Max Spike (Lag)      : {max_latency:.2f} ms")
    print(f"Jitter (Variance)    : {jitter:.2f} ms")
    print("=" * 50)
    print("REPORT HINT:")
    print("- High Jitter means frames are clumped together (bad for real-time video).")
    print("- Disabling TCP_NODELAY usually increases Jitter significantly because of Nagle's Algorithm.")
    print("- Enabling TLS usually drops Throughput and slightly increases Avg Inter-frame Time due to encryption overhead.\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=15, help="Test duration in seconds")
    args = parser.parse_args()
    # Hardcoded host/port and TLS enabled by default
    run_benchmark(host="127.0.0.1", port=9999, use_tls=True, duration=args.duration)
