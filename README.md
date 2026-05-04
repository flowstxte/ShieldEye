# ShieldEye — Retail Security Intelligence System

AI-powered CCTV analysis that detects suspicious behaviour in real time and alerts shopkeepers via a live dashboard.

## Screenshots

<p align="center">
  <img src="https://raw.githubusercontent.com/flowstxte/ShieldEye/refs/heads/main/ss.png" width="60%" />
</p>

---

## Features

- **Real-Time Behaviour Analysis:** Automatically detects loitering, crouching, erratic movement, and shelf proximity.
- **Live Alert Dashboard:** Web-based UI with a modern dark theme to monitor alerts and video feeds instantly.
- **Multi-Source Video Support:** Works seamlessly with local video files, USB webcams, and IP camera RTSP streams.
- **Scalable AI Models:** Choose from different YOLOv8 model sizes (Nano to Large) based on your hardware capabilities.
- **GPU Acceleration:** Built-in support for CUDA-enabled GPUs for high-performance, real-time processing.
- **Customizable Sensitivity:** Easily tune detection thresholds and cooldowns to match your store's specific environment.

---

## How It Works

1. **Video Ingestion:** The backend captures continuous video frames from the configured source (local file, webcam, or RTSP stream) using OpenCV.
2. **AI Detection & Tracking:** Frames are processed by a YOLOv8 object detection model to identify and track individuals moving through the camera's view.
3. **Behavioural Analysis:** The system analyzes the movement history, bounding box dimensions, and positioning of each tracked person to flag suspicious patterns (e.g., staying stationary for >8 seconds, sudden drops in posture).
4. **Real-Time Broadcasting:** When a high-risk behaviour is triggered, the backend instantly pushes an alert payload via WebSockets.
5. **Dashboard Display:** The frontend receives the WebSocket data and updates the live dashboard, giving shopkeepers immediate, categorized security alerts.

---

## Tech Stack

- **Backend:** Python 3.11, FastAPI, Uvicorn, OpenCV
- **AI & Computer Vision:** Ultralytics YOLOv8, PyTorch
- **Frontend:** HTML5, CSS3, Vanilla JavaScript (WebSocket Client)

---

## Project Structure

```
ShieldEye/
├── backend/
│   ├── main.py        # FastAPI server, WebSocket, video loop
│   ├── camera.py      # Video source manager (file / webcam / RTSP)
│   ├── detection.py   # YOLOv8 detection + behaviour analysis
│   └── alerts.py      # In-memory alert store
├── frontend/
│   ├── index.html     # Dashboard UI
│   ├── style.css      # Modern dark theme
│   └── app.js         # WebSocket client + rendering
├── models/
│   └── yolov8n.pt     # Auto-downloaded on first run
├── .env               # Video source configuration
├── requirements.txt   # Python dependencies
└── README.md
```

---

## Setup

```cmd
# Clone repo
git clone https://github.com/flowstxte/ShieldEye.git
cd ShieldEye
```

### Requirements

- **Python 3.11** (not 3.12+ — PyTorch wheels are only available for 3.11 on Windows)
- A test video file (`test.mp4`) placed in the project root for local testing

### Step 1 — Create venv with Python 3.11

```cmd
cd path\to\ShieldEye
py -3.11 -m venv venv
venv\Scripts\activate
```

### Step 2 — Install dependencies

```cmd
pip install --upgrade pip
pip install -r requirements.txt
```

> First install takes a few minutes.

### Step 3 — Add a test video

Place any MP4 file in the project root named `test.mp4`:

```
ShieldEye/
└── test.mp4
```

### Step 4 — Run

```cmd
cd backend
python main.py
```

### Step 5 — Open dashboard

```
http://localhost:8000
```

---

## Configuration (.env)

```env
# Local test video (relative to project root)
VIDEO_SOURCE=test.mp4

# USB / built-in webcam
# VIDEO_SOURCE=0

# IP camera RTSP stream
# VIDEO_SOURCE=rtsp://admin:password@192.168.1.100:554/stream
```

---

## Upgrading the AI Model

Edit `MODEL_NAME` at the top of `backend/detection.py`:

| Model        | Size  | Accuracy   | CPU Speed      |
| ------------ | ----- | ---------- | -------------- |
| `yolov8n.pt` | 6 MB  | ⭐⭐       | Fast (default) |
| `yolov8s.pt` | 22 MB | ⭐⭐⭐     | Good           |
| `yolov8m.pt` | 52 MB | ⭐⭐⭐⭐   | Moderate       |
| `yolov8l.pt` | 87 MB | ⭐⭐⭐⭐⭐ | Slow on CPU    |

Models auto-download to the `models/` folder on first use.

**Check for GPU (run in venv):**

```cmd
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No GPU')"
```

If you have a GPU, add `self.model.to("cuda")` in `detection.py` after the YOLO() line and use `yolov8l.pt` for best accuracy.

---

## Detection Behaviours

| Behaviour              | Trigger                     | Severity |
| ---------------------- | --------------------------- | -------- |
| Loitering              | Stationary >8s in same area | Medium   |
| Crouching / Concealing | Low body posture            | High     |
| Erratic Movement       | Rapid direction changes     | Medium   |
| Shelf Proximity        | Lingering at shelf edges    | Low      |
| High Risk (Composite)  | Multiple flags triggered    | Critical |

### Tuning sensitivity (`backend/detection.py`)

```python
LOITER_SECONDS    = 8      # Seconds before loitering alert (lower = more sensitive)
ERRATIC_THRESHOLD = 4      # Direction changes to flag erratic movement
CROUCH_RATIO      = 0.55   # bbox h/w ratio for crouching detection
COOLDOWN_SECONDS  = 8      # Seconds between same alerts for same person
CONFIDENCE_THRESH = 0.45   # Min YOLO confidence (raise to reduce false positives)
```

---

## Stopping

Press `Ctrl+C` in the terminal. Then:

```cmd
deactivate
```

#### Contributions are always welcome! :-)
