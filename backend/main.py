import asyncio
import base64
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

import cv2
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# Global references — set inside lifespan, not at import time
alert_manager = None
detector      = None
camera_stream = None
connected_clients: List[WebSocket] = []
START_TIME = time.time()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global alert_manager, detector, camera_stream

    # Import here so module-level instantiation doesn't happen on uvicorn import
    from alerts import AlertManager
    from camera import CameraStream
    from detection import ShopDetector

    print("[ShieldEye] Initialising components...")
    alert_manager = AlertManager()
    camera_stream = CameraStream()
    detector      = ShopDetector()

    print("[ShieldEye] Starting server...")
    task = asyncio.create_task(video_processing_loop())
    yield

    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    camera_stream.stop()
    print("[ShieldEye] Server shut down.")

app = FastAPI(title="ShieldEye API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def broadcast(message: dict):
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in connected_clients:
            connected_clients.remove(ws)


# Static file routes
@app.get("/")
async def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

@app.get("/style.css")
async def serve_css():
    return FileResponse(str(FRONTEND_DIR / "style.css"), media_type="text/css")

@app.get("/app.js")
async def serve_js():
    return FileResponse(str(FRONTEND_DIR / "app.js"), media_type="application/javascript")


# API routes
@app.get("/api/alerts")
async def get_alerts():
    return {"alerts": alert_manager.get_all() if alert_manager else []}

@app.get("/api/status")
async def get_status():
    return {
        "status":        "running",
        "camera_active": camera_stream.is_running if camera_stream else False,
        "total_alerts":  alert_manager.count() if alert_manager else 0,
        "uptime":        time.strftime("%H:%M:%S", time.gmtime(time.time() - START_TIME)),
    }

@app.post("/api/alerts/clear")
async def clear_alerts():
    if alert_manager:
        alert_manager.clear()
    await broadcast({"type": "alerts_cleared"})
    return {"success": True}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    print(f"[WS] Client connected. Total: {len(connected_clients)}")
    try:
        # Send alert history on connect
        if alert_manager:
            await websocket.send_json({
                "type":   "alert_history",
                "alerts": alert_manager.get_all(),
            })
        while True:
            # Use receive() not receive_text() — handles ping/binary without crashing
            try:
                await asyncio.wait_for(websocket.receive(), timeout=30)
            except asyncio.TimeoutError:
                pass  # Normal keep-alive timeout, continue
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as e:
        print(f"[WS] Unexpected error: {e}")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        print(f"[WS] Client disconnected. Total: {len(connected_clients)}")

async def video_processing_loop():
    print("[Engine] Starting video processing loop...")
    try:
        camera_stream.start()
    except RuntimeError as e:
        print(f"[Engine] {e}")
        print("[Engine] Add test.mp4 to project root or set VIDEO_SOURCE in .env, then restart.")
        return

    frame_count = 0
    fps_timer   = time.time()
    fps         = 0.0

    while True:
        frame = camera_stream.read_frame()
        if frame is None:
            await asyncio.sleep(0.05)
            continue

        annotated, detections, new_alerts = detector.process_frame(frame)

        for alert in new_alerts:
            alert_manager.add(alert)
            await broadcast({"type": "alert", "alert": alert})

        frame_count += 1
        elapsed = time.time() - fps_timer
        if elapsed >= 1.0:
            fps         = frame_count / elapsed
            frame_count = 0
            fps_timer   = time.time()

        _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
        b64    = base64.b64encode(buf).decode("utf-8")

        if connected_clients:
            payload: dict = {
                "type":       "frame",
                "data":       b64,
                "detections": detections,
                "timestamp":  time.time(),
            }
            # Only include fps once it's been calculated (avoid sending 0)
            if fps > 0:
                payload["fps"] = round(fps, 1)
            await broadcast(payload)

        await asyncio.sleep(0.04)  # ~25 FPS target

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")