"""
camera.py
---------------------------------------------------------------------
Camera backend for the AI X-Ray Cancer Detection Prototype.

This module owns all direct interaction with the USB camera via
OpenCV (cv2) and exposes a small, Flask-friendly API:

    - generate_frames()   : MJPEG generator for a <img> streaming route
    - get_camera_status() : current camera state, for the system
                             information / diagnostics panel
    - capture_frame()     : save the most recent frame to disk
    - release_camera()    : cleanly release the capture device

Design goals
------------
- Never raise an unhandled exception into Flask. Every public
  function fails softly and reports its state through
  ``get_camera_status()`` instead.
- If the camera is missing, busy, or disconnects mid-stream, the
  module falls back to a clearly labeled placeholder frame
  ("Camera Not Available") rather than crashing the video feed.
- No AI/model logic lives here. This file is strictly the camera
  I/O layer that a future analysis pipeline can build on top of.

Educational prototype notice
-----------------------------
This module only handles camera capture. It performs no medical
image analysis of any kind.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, asdict
from typing import Generator, Optional

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Index of the USB camera to open. 0 is usually a built-in webcam;
# external USB cameras often show up at 1, 2, etc. Adjust as needed
# for the exhibition hardware.
CAMERA_INDEX: int = 0

# Desired capture resolution and frame rate. The camera driver may
# not honor these exactly - actual values are read back after the
# device opens and exposed via get_camera_status().
FRAME_WIDTH: int = 1280
FRAME_HEIGHT: int = 720
TARGET_FPS: int = 30

# JPEG encoding quality used for both the MJPEG stream and captured
# still frames (0-100, higher is better quality / larger file size).
JPEG_QUALITY: int = 90

# Where captured stills are written. Path is relative to this file's
# directory so it works regardless of the process's working directory.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURE_DIR: str = os.path.join(_BASE_DIR, "static", "captured")
CAPTURE_FILENAME: str = "latest_capture.jpg"

# How long generate_frames() waits between frames if the camera is
# unavailable, to avoid a tight busy-loop hammering the CPU while
# still streaming placeholder frames at a watchable rate.
_UNAVAILABLE_FRAME_INTERVAL_SECONDS: float = 0.5

# Number of consecutive failed reads tolerated before the module
# considers the camera disconnected and attempts to release/reopen it.
_MAX_CONSECUTIVE_READ_FAILURES: int = 10

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

@dataclass
class _CameraState:
    """Mutable, thread-guarded state describing the camera connection."""

    connected: bool = False
    initializing: bool = False
    last_error: Optional[str] = None
    actual_width: Optional[int] = None
    actual_height: Optional[int] = None
    actual_fps: Optional[float] = None
    consecutive_failures: int = 0
    last_frame_time: Optional[float] = None


_state = _CameraState()
_state_lock = threading.Lock()

# The underlying OpenCV capture device. None when not open.
_capture: Optional[cv2.VideoCapture] = None
_capture_lock = threading.Lock()

# The most recently successfully read frame (BGR numpy array), kept so
# capture_frame() can save a still without depending on the caller
# also being the frame reader.
_latest_frame: Optional[np.ndarray] = None
_latest_frame_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Camera initialization
# ---------------------------------------------------------------------------

def _open_camera() -> bool:
    """
    Attempt to open and configure the USB camera at CAMERA_INDEX.

    Safe to call multiple times; if a capture is already open and
    working, this is a no-op that returns True.

    Returns:
        True if the camera is open and ready, False otherwise.
    """
    global _capture

    with _capture_lock:
        if _capture is not None and _capture.isOpened():
            return True

        with _state_lock:
            _state.initializing = True
            _state.last_error = None

        try:
            # cv2.CAP_ANY lets OpenCV pick the best available backend
            # for the platform (e.g. V4L2 on Linux, DSHOW on Windows).
            capture = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_ANY)

            if not capture.isOpened():
                capture.release()
                raise RuntimeError(
                    f"Unable to open camera at index {CAMERA_INDEX}."
                )

            # Request resolution and frame rate. These are best-effort;
            # not all cameras/drivers support every combination.
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
            capture.set(cv2.CAP_PROP_FPS, TARGET_FPS)

            # Give the camera a brief moment to apply settings and
            # warm up before we trust the first frame read.
            time.sleep(0.1)

            # Confirm the device actually produces frames.
            ok, frame = capture.read()
            if not ok or frame is None:
                capture.release()
                raise RuntimeError(
                    f"Camera at index {CAMERA_INDEX} opened but returned "
                    "no frame."
                )

            _capture = capture

            with _state_lock:
                _state.connected = True
                _state.initializing = False
                _state.last_error = None
                _state.consecutive_failures = 0
                _state.actual_width = int(
                    capture.get(cv2.CAP_PROP_FRAME_WIDTH)
                )
                _state.actual_height = int(
                    capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
                )
                _state.actual_fps = capture.get(cv2.CAP_PROP_FPS) or None
                _state.last_frame_time = time.time()

            _store_latest_frame(frame)

            logger.info(
                "Camera %s opened successfully (%sx%s @ %sfps requested).",
                CAMERA_INDEX,
                _state.actual_width,
                _state.actual_height,
                TARGET_FPS,
            )
            return True

        except Exception as exc:  # noqa: BLE001 - intentionally broad, must not crash Flask
            logger.warning("Camera initialization failed: %s", exc)
            with _state_lock:
                _state.connected = False
                _state.initializing = False
                _state.last_error = str(exc)
            _capture = None
            return False


def _store_latest_frame(frame: np.ndarray) -> None:
    """Thread-safely cache the most recent successfully read frame."""
    global _latest_frame
    with _latest_frame_lock:
        _latest_frame = frame


# ---------------------------------------------------------------------------
# Placeholder frame (camera unavailable)
# ---------------------------------------------------------------------------

def _build_placeholder_frame(message: str = "Camera Not Available") -> np.ndarray:
    """
    Build a neutral placeholder image used whenever a live camera
    frame cannot be produced (device missing, failed to open, or
    disconnected mid-stream).

    Args:
        message: Primary line of text to display on the placeholder.

    Returns:
        A BGR numpy array sized to match the configured frame
        dimensions, suitable for JPEG encoding or on-screen display.
    """
    height, width = FRAME_HEIGHT, FRAME_WIDTH
    frame = np.full((height, width, 3), (30, 32, 35), dtype=np.uint8)

    # Simple viewfinder-style corner brackets so the placeholder still
    # reads as an imaging viewport rather than a blank error screen.
    bracket_color = (90, 110, 120)
    bracket_len = 40
    thickness = 2
    margin = 24
    corners = [
        (margin, margin, 1, 1),
        (width - margin, margin, -1, 1),
        (margin, height - margin, 1, -1),
        (width - margin, height - margin, -1, -1),
    ]
    for x, y, dx, dy in corners:
        cv2.line(frame, (x, y), (x + dx * bracket_len, y), bracket_color, thickness)
        cv2.line(frame, (x, y), (x, y + dy * bracket_len), bracket_color, thickness)

    # Centered primary message.
    font = cv2.FONT_HERSHEY_SIMPLEX
    text_scale = 1.1
    text_thickness = 2
    text_color = (200, 210, 215)
    (text_w, text_h), _ = cv2.getTextSize(message, font, text_scale, text_thickness)
    text_x = (width - text_w) // 2
    text_y = (height + text_h) // 2
    cv2.putText(
        frame, message, (text_x, text_y), font, text_scale, text_color,
        text_thickness, cv2.LINE_AA,
    )

    # Secondary hint line underneath.
    hint = "Check USB connection and CAMERA_INDEX in camera.py"
    hint_scale = 0.55
    hint_thickness = 1
    hint_color = (140, 150, 155)
    (hint_w, hint_h), _ = cv2.getTextSize(hint, font, hint_scale, hint_thickness)
    hint_x = (width - hint_w) // 2
    hint_y = text_y + text_h + 24
    cv2.putText(
        frame, hint, (hint_x, hint_y), font, hint_scale, hint_color,
        hint_thickness, cv2.LINE_AA,
    )

    return frame


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_camera_status() -> dict:
    """
    Report the current camera connection state.

    Intended for the system information / diagnostics panel in the
    UI, and for internal decisions about whether to attempt a
    reconnect.

    Returns:
        A dictionary with keys: connected, initializing, last_error,
        actual_width, actual_height, actual_fps, camera_index.
    """
    with _state_lock:
        status = asdict(_state)
    status["camera_index"] = CAMERA_INDEX
    return status


def generate_frames() -> Generator[bytes, None, None]:
    """
    Continuously yield JPEG-encoded frames as a multipart HTTP stream.

    Intended to back a Flask route such as::

        @app.route("/video_feed")
        def video_feed():
            return Response(
                generate_frames(),
                mimetype="multipart/x-mixed-replace; boundary=frame",
            )

    Behavior:
        - Attempts to open the camera if it is not already open.
        - On each iteration, reads a frame and encodes it as JPEG.
        - If the camera is unavailable or a read fails repeatedly,
          yields a labeled placeholder frame instead of raising.
        - Never lets an exception propagate to the Flask response;
          all errors are logged and converted into placeholder output.

    Yields:
        Raw bytes of a single multipart section containing one JPEG
        frame, ready to be streamed to the browser.
    """
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]

    while True:
        frame: Optional[np.ndarray] = None

        try:
            if not _open_camera():
                # Camera not available at all - serve a placeholder
                # and back off slightly so we don't spin the CPU.
                frame = _build_placeholder_frame("Camera Not Available")
                time.sleep(_UNAVAILABLE_FRAME_INTERVAL_SECONDS)
            else:
                with _capture_lock:
                    ok, raw_frame = (
                        _capture.read() if _capture is not None else (False, None)
                    )

                if ok and raw_frame is not None:
                    frame = raw_frame
                    _store_latest_frame(frame)
                    with _state_lock:
                        _state.consecutive_failures = 0
                        _state.last_frame_time = time.time()
                else:
                    # A single failed read does not necessarily mean
                    # the camera is gone - USB cameras can drop the
                    # occasional frame. Track consecutive failures
                    # and only treat it as a disconnect past the
                    # configured threshold.
                    with _state_lock:
                        _state.consecutive_failures += 1
                        failures = _state.consecutive_failures

                    if failures >= _MAX_CONSECUTIVE_READ_FAILURES:
                        logger.warning(
                            "Camera read failed %s times in a row; "
                            "treating device as disconnected.",
                            failures,
                        )
                        release_camera()
                        frame = _build_placeholder_frame("Camera Not Available")
                    else:
                        frame = _build_placeholder_frame("Camera Signal Lost")
                        time.sleep(0.05)

        except Exception as exc:  # noqa: BLE001 - never let the stream crash Flask
            logger.error("Unexpected error while reading camera frame: %s", exc)
            frame = _build_placeholder_frame("Camera Not Available")

        # Encode whatever frame we ended up with (real or placeholder).
        try:
            success, buffer = cv2.imencode(".jpg", frame, encode_params)
            if not success:
                logger.error("JPEG encoding failed for current frame.")
                continue
        except Exception as exc:  # noqa: BLE001
            logger.error("Exception during JPEG encoding: %s", exc)
            continue

        payload = (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
        )
        yield payload


def capture_frame() -> str:
    """
    Save the most recently captured frame as a still JPEG image.

    If no live frame is available (camera disconnected or never
    initialized), a labeled placeholder image is saved instead so
    the calling route can still respond successfully.

    The destination directory (static/captured) is created
    automatically if it does not already exist.

    Returns:
        The absolute filesystem path of the saved image.
    """
    os.makedirs(CAPTURE_DIR, exist_ok=True)
    output_path = os.path.join(CAPTURE_DIR, CAPTURE_FILENAME)

    with _latest_frame_lock:
        frame = _latest_frame.copy() if _latest_frame is not None else None

    if frame is None:
        frame = _build_placeholder_frame("Camera Not Available")

    try:
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
        success = cv2.imwrite(output_path, frame, encode_params)
        if not success:
            raise IOError(f"cv2.imwrite reported failure for {output_path}")
        logger.info("Captured frame saved to %s", output_path)
    except Exception as exc:  # noqa: BLE001 - saving must never crash the caller
        logger.error("Failed to save captured frame: %s", exc)
        with _state_lock:
            _state.last_error = f"Capture save failed: {exc}"

    return output_path


def release_camera() -> None:
    """
    Release the camera device and reset connection state.

    Safe to call even if the camera was never opened or has already
    been released. Should be called on application shutdown, and is
    also called internally when a persistent disconnect is detected.
    """
    global _capture

    with _capture_lock:
        if _capture is not None:
            try:
                _capture.release()
                logger.info("Camera %s released.", CAMERA_INDEX)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error releasing camera: %s", exc)
            finally:
                _capture = None

    with _state_lock:
        _state.connected = False
        _state.initializing = False