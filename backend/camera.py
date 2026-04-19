import os
import threading
import time
from pathlib import Path

import cv2
from dotenv import load_dotenv

# Load .env from project root (ShieldEye/.env)
_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

class CameraStream:

    def __init__(self):
        self._cap      = None
        self._frame    = None
        self._lock     = threading.Lock()
        self._thread   = None
        self._running  = False
        self._fps      = 25.0  
        self._source   = self._resolve_source()

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self):
        if self._running:
            return

        self._cap = cv2.VideoCapture(self._source)

        if not self._cap.isOpened():
            print(f"[Camera] Could not open '{self._source}'. Trying webcam 0...")
            self._cap = cv2.VideoCapture(0)

        if not self._cap.isOpened():
            raise RuntimeError("[Camera] FATAL: No video source available.")

        w          = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h          = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._fps  = self._cap.get(cv2.CAP_PROP_FPS) or 25.0
        print(f"[Camera] Opened: {self._source}  {w}x{h} @ {self._fps:.1f} FPS")

        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        if self._cap:
            self._cap.release()
        print("[Camera] Stopped.")

    def read_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def _resolve_source(self):
        env_val = os.getenv("VIDEO_SOURCE", "").strip()

        if env_val:
            # Numeric string = webcam index
            if env_val.isdigit():
                print(f"[Camera] Source: webcam index {env_val}")
                return int(env_val)

            # Resolve relative paths from project root, not from CWD
            p = Path(env_val)
            if not p.is_absolute():
                p = _PROJECT_ROOT / p

            if p.exists():
                print(f"[Camera] Source: {p}")
                return str(p)

            print(f"[Camera] WARNING: VIDEO_SOURCE not found: {p}")
            print(f"[Camera] Hint: place your video in {_PROJECT_ROOT}")

        # Auto-detect test.mp4 in project root
        test_video = _PROJECT_ROOT / "test.mp4"
        if test_video.exists():
            print(f"[Camera] Auto-detected: {test_video}")
            return str(test_video)

        print(f"[Camera] No video source found. Place test.mp4 in {_PROJECT_ROOT}")
        return 0  # falls through to webcam attempt in start()

    def _loop(self):
        interval = 1.0 / self._fps   # use cached fps — no syscall per frame
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                # End of file — loop back to start
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                time.sleep(0.05)
                continue
            with self._lock:
                self._frame = frame
            time.sleep(interval)
