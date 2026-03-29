import asyncio
import struct
import socket
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import sys
import ssl
from dotenv import load_dotenv

# Add parent dir to resolve potential absolute paths
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.auth import DatabaseAdapter

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(dotenv_path=env_path)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(connect_to_tcp_and_broadcast())
    yield

app = FastAPI(lifespan=lifespan)

client_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "client")
app.mount("/client", StaticFiles(directory=client_dir), name="client")
client_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "client")
app.mount("/client", StaticFiles(directory=client_dir), name="client")

clients = set()

TCP_HOST = '127.0.0.1'
TCP_PORT = 9999
USE_TLS = True

def recv_exact(sock, size):
    buf = b""
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf

async def connect_to_tcp_and_broadcast():
    # Connects to the TCP server using asyncio streams with SSL, receives frames, and broadcasts to WebSocket clients.
    ssl_ctx = None
    if USE_TLS:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        reader, writer = await asyncio.open_connection(
            TCP_HOST, TCP_PORT, ssl=ssl_ctx
        )

        # Authenticate with the TCP server securely via .env credentials
        auth_msg = f"AUTH {os.environ.get('STREAM_USER', 'admin')} {os.environ.get('STREAM_PASSWORD', 'admin123')}\n"
        writer.write(auth_msg.encode('utf-8'))
        await writer.drain()

        auth_resp = await reader.read(32)
        print(f"[DEBUG] Auth response from TCP server: {auth_resp}")
        if b"AUTH_SUCCESS" not in auth_resp:
            print(f"Bridge failed to auth with TCP server. Server responded with: {auth_resp} using user: {os.environ.get('STREAM_USER')}")
            writer.close()
            await writer.wait_closed()
            return

        print("Bridge connected to TCP Backend. Ready to broadcast to WS clients.")

        while True:
            # 1. Read the 4-byte frame header
            header = await reader.readexactly(4)
            print(f"[DEBUG] Frame header bytes: {header}")
            if not header:
                break
            (data_size,) = struct.unpack('>I', header)
            print(f"[DEBUG] Frame size: {data_size}")

            # 2. Read the entire frame payload based on the parsed size
            payload = await reader.readexactly(data_size)
            if not payload:
                break

            # Broadcast to web clients
            if clients:
                coros = [client.send_bytes(payload) for client in clients]
                await asyncio.gather(*coros, return_exceptions=True)

    except Exception as e:
        print(f"Bridge error: {e}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass



@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket, 
    username: str = Query(None), 
    password: str = Query(None)
):
    """
    WebSocket Handshake (HTTP Upgrade):
    The client sends an HTTP GET request with 'Connection: Upgrade' and 'Upgrade: websocket'.
    FastAPI (via Starlette/uvicorn) parses this and responds with HTTP '101 Switching Protocols'.
    The connection is now a persistent, full-duplex TCP stream (WebSocket).
    """
    # 1. Authenticate before accepting using the real Database
    db = DatabaseAdapter()
    if not db.authenticate_user(username, password):
        await websocket.close(code=1008) # Policy Violation
        return

    # 2. Accept the WebSocket connection (101 Switching Protocols sent here)
    await websocket.accept()
    
    # 3. Add to broadcast pool
    clients.add(websocket)
    try:
        while True:
            # Wait for any client message (ping, disconnect)
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        clients.remove(websocket)
        
if __name__ == "__main__":
    cert_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wss_cert.pem")
    key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wss_key.pem")
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        ssl_certfile=cert_path,
        ssl_keyfile=key_path
    )
