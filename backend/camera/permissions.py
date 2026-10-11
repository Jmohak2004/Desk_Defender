"""macOS camera permission and AVFoundation device discovery.

OpenCV's AVFoundation backend can only *request* camera permission from the
process main thread; FastAPI handlers run on worker threads. We therefore
request permission ourselves on the main thread during startup, and tell
OpenCV to skip its own request (OPENCV_AVFOUNDATION_SKIP_AUTH=1).

macOS attributes the permission to the app that launched Python (Terminal,
iTerm, VS Code...), so that app must be allowed in
System Settings -> Privacy & Security -> Camera.
"""

import logging
import os
import platform
import threading
import time
from typing import Dict, List

logger = logging.getLogger("desk_defender.camera.permissions")

os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")

IS_MACOS = platform.system() == "Darwin"

_STATUS_NAMES = {0: "not_determined", 1: "restricted", 2: "denied", 3: "authorized"}

try:  # PyObjC is optional; without it we fall back to OpenCV index probing.
    if IS_MACOS:
        import AVFoundation  # type: ignore
        from Foundation import NSDate, NSRunLoop  # type: ignore
        HAS_AVFOUNDATION = True
    else:
        HAS_AVFOUNDATION = False
except Exception:  # pragma: no cover - depends on the host
    HAS_AVFOUNDATION = False


_status_cache = {"value": None, "at": 0.0}
_STATUS_TTL_S = 5.0


def authorization_status(fresh: bool = False) -> str:
    """Camera permission state. Cached briefly: the AVFoundation query costs ~30 ms and is polled often."""
    if not IS_MACOS:
        return "not_applicable"
    if not HAS_AVFOUNDATION:
        return "unknown"
    now = time.time()
    if fresh or _status_cache["value"] is None or now - _status_cache["at"] > _STATUS_TTL_S:
        code = int(AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(AVFoundation.AVMediaTypeVideo))
        _status_cache["value"] = _STATUS_NAMES.get(code, "unknown")
        _status_cache["at"] = now
    return _status_cache["value"]


def request_authorization(timeout_s: float = 45.0) -> str:
    """Requests camera access. Must be called on the main thread to show the system prompt."""
    status = authorization_status(fresh=True)
    if status != "not_determined":
        return status
    if threading.current_thread() is not threading.main_thread():
        logger.warning("Camera permission can only be requested from the main thread")
        return status

    result: Dict[str, bool] = {}

    def _done(granted: bool) -> None:
        result["granted"] = bool(granted)

    logger.info("Requesting macOS camera permission - approve the system dialog if it appears")
    AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVFoundation.AVMediaTypeVideo, _done)
    deadline = time.time() + timeout_s
    while "granted" not in result and time.time() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
    return authorization_status(fresh=True)


def discover_avfoundation_devices() -> List[Dict]:
    """Lists video devices in the order OpenCV's AVFoundation backend indexes them.

    OpenCV enumerates with an AVCaptureDeviceDiscoverySession over built-in,
    external and Continuity camera types. We use the same session so the list
    index matches cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION). Because that
    ordering is an OpenCV implementation detail, the UI also shows a live
    thumbnail for each index so the player can confirm visually.
    """
    if not HAS_AVFOUNDATION:
        return []
    AV = AVFoundation
    device_types = [AV.AVCaptureDeviceTypeBuiltInWideAngleCamera]
    # Desk View is deliberately excluded: OpenCV cannot open it, and listing it would
    # shift indices for any device enumerated after it.
    for name in ("AVCaptureDeviceTypeExternal", "AVCaptureDeviceTypeExternalUnknown",
                 "AVCaptureDeviceTypeContinuityCamera"):
        value = getattr(AV, name, None)
        if value is not None and value not in device_types:
            device_types.append(value)
    session = AV.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_(
        device_types, AV.AVMediaTypeVideo, 0)
    devices = []
    for idx, dev in enumerate(session.devices()):
        name = str(dev.localizedName())
        model = str(dev.modelID() or "")
        dtype = str(dev.deviceType())
        is_continuity = ("Continuity" in dtype or "iphone" in name.lower() or model.lower().startswith("iphone"))
        is_desk_view = "DeskView" in dtype or "desk view" in name.lower()
        devices.append({
            "index": idx,
            "name": name,
            "unique_id": str(dev.uniqueID()),
            "model_id": model,
            "device_type": dtype.replace("AVCaptureDeviceType", ""),
            "is_continuity": bool(is_continuity),
            "is_desk_view": bool(is_desk_view),
            "connected": bool(dev.isConnected()),
            "suspended": bool(dev.isSuspended()) if hasattr(dev, "isSuspended") else False,
        })
    return devices
