"""Stereo depth estimation helpers for simulation and robot cameras.

This module provides a small OpenCV-based stereo pipeline that can turn a
left/right image pair into a depth map or point cloud. It is intentionally
independent from Isaac Sim, ROS, or Unity so it can be reused in simulation
first and later swapped over to a real robot feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    import cv2
except Exception as exc:  # pragma: no cover - import guard for optional dependency
    cv2 = None  # type: ignore[assignment]
    _CV2_IMPORT_ERROR = exc
else:
    _CV2_IMPORT_ERROR = None


@dataclass(frozen=True)
class StereoCameraModel:
    """Minimal stereo calibration parameters.

    Attributes:
        fx: focal length in pixels on the x axis.
        fy: focal length in pixels on the y axis.
        cx: principal point x coordinate.
        cy: principal point y coordinate.
        baseline_m: distance between the two stereo cameras in meters.
    """

    fx: float
    fy: float
    cx: float
    cy: float
    baseline_m: float


class StereoDepthEstimator:
    """Estimate depth from a rectified stereo image pair."""

    def __init__(
        self,
        camera: StereoCameraModel,
        num_disparities: int = 128,
        block_size: int = 7,
        min_disparity: int = 0,
    ) -> None:
        if cv2 is None:
            raise ImportError(
                "OpenCV is required for stereo depth estimation. "
                "Install opencv-python to use teleop.utils.stereo_depth."
            ) from _CV2_IMPORT_ERROR

        if num_disparities <= 0 or num_disparities % 16 != 0:
            raise ValueError("num_disparities must be a positive multiple of 16")
        if block_size < 3 or block_size % 2 == 0:
            raise ValueError("block_size must be an odd integer >= 3")

        self.camera = camera
        self._matcher = cv2.StereoSGBM_create(
            minDisparity=min_disparity,
            numDisparities=num_disparities,
            blockSize=block_size,
            P1=8 * 3 * block_size * block_size,
            P2=32 * 3 * block_size * block_size,
            disp12MaxDiff=1,
            uniquenessRatio=10,
            speckleWindowSize=50,
            speckleRange=2,
            mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
        )

    def compute_disparity(self, left_bgr: np.ndarray, right_bgr: np.ndarray) -> np.ndarray:
        """Return a float32 disparity map in pixels."""

        self._validate_pair(left_bgr, right_bgr)

        if left_bgr.ndim == 3:
            left_gray = cv2.cvtColor(left_bgr, cv2.COLOR_BGR2GRAY)
        else:
            left_gray = left_bgr

        if right_bgr.ndim == 3:
            right_gray = cv2.cvtColor(right_bgr, cv2.COLOR_BGR2GRAY)
        else:
            right_gray = right_bgr

        disparity = self._matcher.compute(left_gray, right_gray).astype(np.float32) / 16.0
        return disparity

    def compute_depth(self, left_bgr: np.ndarray, right_bgr: np.ndarray) -> np.ndarray:
        """Return a float32 depth map in meters."""

        disparity = self.compute_disparity(left_bgr, right_bgr)

        depth = np.zeros_like(disparity, dtype=np.float32)
        valid = disparity > 0.1
        depth[valid] = (self.camera.fx * self.camera.baseline_m) / disparity[valid]
        depth[~np.isfinite(depth)] = 0.0
        return depth

    def depth_to_point_cloud(self, depth_m: np.ndarray, color_bgr: Optional[np.ndarray] = None) -> tuple[np.ndarray, Optional[np.ndarray]]:
        """Project a depth image into a point cloud.

        Returns:
            points: (N, 3) array in camera coordinates.
            colors: optional (N, 3) uint8 array in BGR order.
        """

        if depth_m.ndim != 2:
            raise ValueError("depth_m must be a 2D array")

        height, width = depth_m.shape
        u_coords, v_coords = np.meshgrid(np.arange(width), np.arange(height))
        valid = depth_m > 0.0

        z = depth_m[valid]
        x = (u_coords[valid] - self.camera.cx) * z / self.camera.fx
        y = (v_coords[valid] - self.camera.cy) * z / self.camera.fy
        points = np.stack([x, y, z], axis=1).astype(np.float32)

        colors = None
        if color_bgr is not None:
            self._validate_color_image(color_bgr, (height, width))
            colors = color_bgr[valid].reshape(-1, 3).astype(np.uint8)

        return points, colors

    def colorize_depth(self, depth_m: np.ndarray, max_depth_m: float = 5.0) -> np.ndarray:
        """Convert depth to a visually useful color map for debugging."""

        if cv2 is None:
            raise ImportError("OpenCV is required for depth visualization.") from _CV2_IMPORT_ERROR

        if depth_m.ndim != 2:
            raise ValueError("depth_m must be a 2D array")

        clipped = np.clip(depth_m, 0.0, max_depth_m)
        scaled = np.zeros_like(clipped, dtype=np.uint8)
        if max_depth_m > 0:
            scaled = (255.0 * (clipped / max_depth_m)).astype(np.uint8)
        return cv2.applyColorMap(255 - scaled, cv2.COLORMAP_TURBO)

    @staticmethod
    def _validate_pair(left_bgr: np.ndarray, right_bgr: np.ndarray) -> None:
        if left_bgr is None or right_bgr is None:
            raise ValueError("left_bgr and right_bgr are required")
        if left_bgr.shape != right_bgr.shape:
            raise ValueError(f"Stereo images must have the same shape, got {left_bgr.shape} and {right_bgr.shape}")
        if left_bgr.ndim not in (2, 3):
            raise ValueError("Stereo images must be grayscale or BGR arrays")

    @staticmethod
    def _validate_color_image(color_bgr: np.ndarray, expected_shape: tuple[int, int]) -> None:
        if color_bgr.ndim != 3 or color_bgr.shape[2] != 3:
            raise ValueError("color_bgr must be a BGR image with shape (H, W, 3)")
        if color_bgr.shape[0] != expected_shape[0] or color_bgr.shape[1] != expected_shape[1]:
            raise ValueError(
                f"color_bgr shape {color_bgr.shape[:2]} does not match depth shape {expected_shape}"
            )
