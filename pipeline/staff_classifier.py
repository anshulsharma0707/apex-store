import numpy as np
import cv2
from typing import Tuple


# ─── Staff Color Profiles ─────────────────────────────────────
# Staff typically wear uniforms — defined by HSV color ranges
STAFF_UNIFORM_COLORS = [
    # Blue uniform (HSV)
    {"lower": np.array([100, 50, 50]), "upper": np.array([130, 255, 255])},
    # White uniform (HSV)
    {"lower": np.array([0, 0, 200]),   "upper": np.array([180, 30, 255])},
    # Dark navy uniform (HSV)
    {"lower": np.array([100, 50, 20]), "upper": np.array([130, 255, 80])},
]

STAFF_COLOR_THRESHOLD = 0.35  # 35% of body must match uniform color


# ─── Extract Body Region ──────────────────────────────────────
def extract_body_region(frame: np.ndarray, bbox: Tuple) -> np.ndarray:
    """Extract torso region from bounding box (middle 50%)"""
    x1, y1, x2, y2 = map(int, bbox)
    h = y2 - y1
    # Take middle 50% vertically (torso area)
    torso_y1 = y1 + int(h * 0.25)
    torso_y2 = y1 + int(h * 0.75)
    torso = frame[torso_y1:torso_y2, x1:x2]
    return torso


# ─── Check Uniform Color ──────────────────────────────────────
def check_uniform_color(
    body_region: np.ndarray,
    threshold: float = STAFF_COLOR_THRESHOLD
) -> Tuple[bool, float]:
    """
    Check if body region matches staff uniform colors.
    Returns (is_staff, confidence)
    """
    if body_region.size == 0:
        return False, 0.0

    # Convert to HSV
    hsv = cv2.cvtColor(body_region, cv2.COLOR_BGR2HSV)
    total_pixels = hsv.shape[0] * hsv.shape[1]

    if total_pixels == 0:
        return False, 0.0

    max_match_ratio = 0.0

    for color_profile in STAFF_UNIFORM_COLORS:
        mask = cv2.inRange(hsv, color_profile["lower"], color_profile["upper"])
        match_pixels = cv2.countNonZero(mask)
        match_ratio = match_pixels / total_pixels
        max_match_ratio = max(max_match_ratio, match_ratio)

    is_staff = max_match_ratio >= threshold
    return is_staff, round(max_match_ratio, 4)


# ─── Main Classifier ──────────────────────────────────────────
class StaffClassifier:
    def __init__(self, threshold: float = STAFF_COLOR_THRESHOLD):
        self.threshold = threshold
        # Track staff visitor IDs once classified
        self._staff_cache: dict[str, bool] = {}

    def classify(
        self,
        frame: np.ndarray,
        bbox: Tuple,
        visitor_id: str,
    ) -> Tuple[bool, float]:
        """
        Classify if a detected person is staff or customer.
        Uses cache to maintain consistency across frames.
        """
        # Return cached result if already classified
        if visitor_id in self._staff_cache:
            return self._staff_cache[visitor_id], 1.0

        body = extract_body_region(frame, bbox)
        is_staff, confidence = check_uniform_color(body, self.threshold)

        # Cache result
        self._staff_cache[visitor_id] = is_staff

        return is_staff, confidence

    def reset(self):
        """Reset cache for new video clip"""
        self._staff_cache.clear()

    def mark_as_staff(self, visitor_id: str):
        """Manually mark a visitor as staff"""
        self._staff_cache[visitor_id] = True

    def is_known_staff(self, visitor_id: str) -> bool:
        return self._staff_cache.get(visitor_id, False)