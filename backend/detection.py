import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np

# Model Loading
try:
    from ultralytics import YOLO
    _YOLO_AVAILABLE = True
except ImportError:
    _YOLO_AVAILABLE = False
    print("[Detection] WARNING: ultralytics not installed. Running in DEMO mode.")

MODELS_DIR = Path(__file__).parent.parent / "models"
MODEL_NAME  = "yolov8n.pt"   # Change to yolov8s.pt / yolov8m.pt etc. for better accuracy
MODEL_PATH  = MODELS_DIR / MODEL_NAME

# Tunable constants
LOITER_SECONDS    = 8      # Seconds stationary before loitering alert
ERRATIC_THRESHOLD = 4      # Direction changes in last 10 frames to flag erratic movement
CROUCH_RATIO      = 0.55   # bbox h/w below this = possible crouching/concealing
HOVER_ZONE_FRAMES = 25     # Frames near shelf edge before alert
CONFIDENCE_THRESH = 0.45   # Min YOLO confidence
HISTORY_LEN       = 60     # Frames of trajectory history per track
COOLDOWN_SECONDS  = 8      # Min seconds between same alert type for same person

# BGR colour palette
COLOR_NORMAL  = (0, 220, 130)
COLOR_SUSPECT = (0, 165, 255)
COLOR_ALERT   = (0, 60, 255)
COLOR_TRAIL   = (180, 100, 255)

FONT       = cv2.FONT_HERSHEY_DUPLEX
FONT_SMALL = cv2.FONT_HERSHEY_SIMPLEX


class TrackState:
    """Per-person tracking state."""

    def __init__(self, track_id: int):
        self.track_id          = track_id
        self.positions         = deque(maxlen=HISTORY_LEN)
        self.timestamps        = deque(maxlen=HISTORY_LEN)
        self.bboxes            = deque(maxlen=HISTORY_LEN)
        self.suspicion         = 0.0
        self.label             = "Tracking"
        self.color             = COLOR_NORMAL
        self.hover_counter     = 0
        self.last_alert_time: Dict[str, float] = {}

    def add(self, cx: int, cy: int, bbox: Tuple, ts: float):
        self.positions.append((cx, cy))
        self.timestamps.append(ts)
        self.bboxes.append(bbox)

    def can_alert(self, alert_type: str) -> bool:
        return (time.time() - self.last_alert_time.get(alert_type, 0)) > COOLDOWN_SECONDS

    def record_alert(self, alert_type: str):
        self.last_alert_time[alert_type] = time.time()


class ShopDetector:
    """Runs YOLO person detection and behaviour analysis."""

    def __init__(self):
        self.model  = None
        self.tracks: Dict[int, TrackState] = {}
        self._load_model()

    def _load_model(self):
        if not _YOLO_AVAILABLE:
            print("[Detection] ultralytics not installed — demo mode.")
            return

        MODELS_DIR.mkdir(parents=True, exist_ok=True)

        if not MODEL_PATH.exists():
            print(f"[Detection] {MODEL_NAME} not found at {MODEL_PATH}")
            print(f"[Detection] Auto-downloading to {MODELS_DIR} ...")

        try:
            import torch
            from ultralytics.nn.tasks import DetectionModel
            from ultralytics.nn.modules import Conv, C2f, SPPF, Detect, DFL
            for cls in [DetectionModel, Conv, C2f, SPPF, Detect, DFL]:
                try:
                    torch.serialization.add_safe_globals([cls])
                except Exception:
                    pass
        except Exception:
            pass

        try:
            # Pass full path — YOLO will download to that location if missing
            self.model = YOLO(str(MODEL_PATH))
            print(f"[Detection] Model loaded: {MODEL_PATH}")
        except Exception as e:
            print(f"[Detection] Failed to load model: {e}")
            self.model = None

    def process_frame(self, frame: np.ndarray) -> Tuple[np.ndarray, List[dict], List[dict]]:
        annotated        = frame.copy()
        triggered_alerts: List[dict] = []
        detections:       List[dict] = []
        now = time.time()

        if self.model is None:
            self._draw_demo_overlay(annotated)
            return annotated, detections, triggered_alerts

        results = self.model.track(
            annotated,
            persist=True,
            classes=[0],
            conf=CONFIDENCE_THRESH,
            verbose=False,
        )

        active_ids: set = set()

        if results and results[0].boxes is not None:
            for i, box in enumerate(results[0].boxes):
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                conf     = float(box.conf[0])
                track_id = int(box.id[0]) if box.id is not None else i

                active_ids.add(track_id)
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2

                if track_id not in self.tracks:
                    self.tracks[track_id] = TrackState(track_id)
                state = self.tracks[track_id]
                state.add(cx, cy, (x1, y1, x2, y2), now)

                alerts = self._analyse(state, (x1, y1, x2, y2), frame.shape)
                triggered_alerts.extend(alerts)

                self._draw_person(annotated, state, x1, y1, x2, y2, conf)

                detections.append({
                    "id":         track_id,
                    "bbox":       [x1, y1, x2, y2],
                    "confidence": round(conf, 2),
                    "suspicion":  round(state.suspicion, 2),
                    "label":      state.label,
                })

        # Prune tracks that disappeared this frame
        for tid in [t for t in self.tracks if t not in active_ids]:
            del self.tracks[tid]

        self._draw_hud(annotated, len(active_ids))
        return annotated, detections, triggered_alerts

    def _analyse(self, state: TrackState, bbox: Tuple, frame_shape: Tuple) -> List[dict]:
        alerts    = []
        positions = list(state.positions)
        timestamps = list(state.timestamps)

        if len(positions) < 5:
            return alerts

        x1, y1, x2, y2 = bbox
        h, w = frame_shape[:2]
        bh = y2 - y1
        bw = x2 - x1

        # 1. Loitering
        if len(positions) >= 20:
            recent   = positions[-30:] if len(positions) >= 30 else positions
            xs       = [p[0] for p in recent]
            ys       = [p[1] for p in recent]
            spread   = max(max(xs) - min(xs), max(ys) - min(ys))
            n        = len(timestamps)
            duration = timestamps[-1] - timestamps[max(0, n - 30)]

            if spread < 80 and duration >= LOITER_SECONDS:
                state.suspicion = min(state.suspicion + 0.02, 1.0)
                state.label     = "Loitering"
                state.color     = COLOR_SUSPECT
                if state.can_alert("loiter"):
                    state.record_alert("loiter")
                    alerts.append(self._make_alert(
                        "LOITERING DETECTED",
                        f"Person #{state.track_id} stationary for {duration:.0f}s.",
                        state, "medium",
                    ))

        # 2. Crouching / Concealing
        if bh > 0 and bw > 0 and (bh / bw) < CROUCH_RATIO and bh > 40:
            state.suspicion = min(state.suspicion + 0.03, 1.0)
            state.label     = "Crouching"
            state.color     = COLOR_SUSPECT
            if state.can_alert("crouch"):
                state.record_alert("crouch")
                alerts.append(self._make_alert(
                    "CONCEALMENT POSTURE",
                    f"Person #{state.track_id} appears to be crouching or bending low.",
                    state, "high",
                ))

        # 3. Erratic / Evasive movement
        if len(positions) >= 10:
            recent_pos = positions[-10:]
            dirs = []
            for i in range(1, len(recent_pos)):
                dx = recent_pos[i][0] - recent_pos[i-1][0]
                dy = recent_pos[i][1] - recent_pos[i-1][1]
                if abs(dx) + abs(dy) > 5:
                    dirs.append((dx > 0, dy > 0))
            if len(dirs) > 1:
                changes = sum(1 for i in range(1, len(dirs)) if dirs[i] != dirs[i-1])
                if changes >= ERRATIC_THRESHOLD:
                    state.suspicion = min(state.suspicion + 0.025, 1.0)
                    state.label     = "Erratic Movement"
                    state.color     = COLOR_SUSPECT
                    if state.can_alert("erratic"):
                        state.record_alert("erratic")
                        alerts.append(self._make_alert(
                            "ERRATIC MOVEMENT",
                            f"Person #{state.track_id} moving erratically — possible evasion.",
                            state, "medium",
                        ))

        # 4. Shelf edge proximity
        near_edge = x1 < w * 0.08 or x2 > w * 0.92
        state.hover_counter = (state.hover_counter + 1) if near_edge else max(0, state.hover_counter - 1)

        if state.hover_counter >= HOVER_ZONE_FRAMES:
            state.suspicion = min(state.suspicion + 0.015, 1.0)
            if state.label == "Tracking":
                state.label = "Near Shelves"
                state.color = COLOR_SUSPECT
            # use cooldown instead of exact frame count so alert can re-fire
            if state.can_alert("hover"):
                state.record_alert("hover")
                alerts.append(self._make_alert(
                    "SHELF PROXIMITY ALERT",
                    f"Person #{state.track_id} lingering near shelf edges.",
                    state, "low",
                ))

        # 5. High suspicion composite
        if state.suspicion >= 0.75:
            state.color = COLOR_ALERT
            state.label = "HIGH RISK"
            if state.can_alert("high_risk"):
                state.record_alert("high_risk")
                alerts.append(self._make_alert(
                    "HIGH-RISK BEHAVIOUR",
                    f"Person #{state.track_id} triggered multiple suspicious behaviour flags.",
                    state, "critical",
                ))

        # Decay suspicion when no flags triggered this frame
        if not alerts:
            state.suspicion = max(0.0, state.suspicion - 0.002)
            # Only reset label if suspicion is genuinely low
            if state.suspicion < 0.2:
                state.label = "Tracking"
                state.color = COLOR_NORMAL

        return alerts

    def _draw_person(self, frame, state: TrackState, x1, y1, x2, y2, conf):
        color = state.color

        # Trajectory trail
        positions = list(state.positions)
        for i in range(1, len(positions)):
            alpha = i / len(positions)
            trail_color = tuple(int(c * alpha) for c in COLOR_TRAIL)
            cv2.circle(frame, positions[i], 2, trail_color, -1)

        # Corner brackets
        corner_len = 20
        for (sx, sy, ex, ey) in [
            (x1, y1, x1+corner_len, y1), (x1, y1, x1, y1+corner_len),
            (x2, y1, x2-corner_len, y1), (x2, y1, x2, y1+corner_len),
            (x1, y2, x1+corner_len, y2), (x1, y2, x1, y2-corner_len),
            (x2, y2, x2-corner_len, y2), (x2, y2, x2, y2-corner_len),
        ]:
            cv2.line(frame, (sx, sy), (ex, ey), color, 3)

        # Thin full rect
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)

        # Suspicion bar below bbox
        bar_w = x2 - x1
        bar_y = y2 + 4
        cv2.rectangle(frame, (x1, bar_y), (x2, bar_y + 5), (40, 40, 40), -1)
        fill_w    = int(bar_w * state.suspicion)
        bar_color = COLOR_ALERT if state.suspicion > 0.6 else (COLOR_SUSPECT if state.suspicion > 0.3 else COLOR_NORMAL)
        if fill_w > 0:
            cv2.rectangle(frame, (x1, bar_y), (x1 + fill_w, bar_y + 5), bar_color, -1)

        # Label chip above bbox
        label_text = f"#{state.track_id}  {state.label}  {conf:.0%}"
        (tw, th), _ = cv2.getTextSize(label_text, FONT_SMALL, 0.7, 2)
        chip_y = max(y1 - th - 8, 0)
        cv2.rectangle(frame, (x1, chip_y - 4), (x1 + tw + 12, chip_y + th + 6), color, -1)
        cv2.putText(frame, label_text, (x1 + 6, chip_y + th), FONT_SMALL, 0.7, (10, 10, 10), 2, cv2.LINE_AA)

    def _draw_hud(self, frame, person_count: int):
        """Draw corner brackets only — no text overlay on video."""
        h, w = frame.shape[:2]
        blen  = 20
        color = (0, 200, 100)
        for (bx, by, dx, dy) in [
            (0, 0, 1, 1), (w-1, 0, -1, 1), (0, h-1, 1, -1), (w-1, h-1, -1, -1)
        ]:
            cv2.line(frame, (bx, by), (bx + dx*blen, by), color, 2)
            cv2.line(frame, (bx, by), (bx, by + dy*blen), color, 2)

    def _draw_demo_overlay(self, frame):
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, 0), (w, h), (20, 20, 20), -1)
        msg = "DEMO MODE — ultralytics not installed"
        (tw, _), _ = cv2.getTextSize(msg, FONT_SMALL, 0.7, 1)
        cv2.putText(frame, msg, ((w - tw) // 2, h // 2), FONT_SMALL, 0.7, COLOR_SUSPECT, 1, cv2.LINE_AA)

    @staticmethod
    def _make_alert(title: str, detail: str, state: TrackState, severity: str) -> dict:
        severity_levels = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        return {
            "id":              f"{state.track_id}_{title.replace(' ', '_')}_{int(time.time())}",
            "title":           title,
            "detail":          detail,
            "track_id":        state.track_id,
            "severity":        severity,
            "severity_level":  severity_levels.get(severity, 1),
            "suspicion_score": round(state.suspicion, 2),
            "timestamp":       time.time(),
            "time_str":        time.strftime("%H:%M:%S"),
        }