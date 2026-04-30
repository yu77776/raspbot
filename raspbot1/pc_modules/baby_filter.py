"""Temporal baby target filter.

Responsibilities:
- Keep only YOLO classes used as baby/child targets.
- Require several consecutive candidate frames before lock.
- Keep the last locked box briefly during short detection gaps.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional, Tuple


class TrackState(Enum):
    NONE = auto()
    CANDIDATE = auto()
    LOCKED = auto()


@dataclass
class TrackResult:
    state: TrackState
    box: Optional[List[float]] = None
    conf: float = 0.0
    confirm_cnt: int = 0
    confirm_max: int = 0

    @property
    def is_locked(self) -> bool:
        return self.state == TrackState.LOCKED


@dataclass
class FilterConfig:
    conf_threshold: float = 0.50
    confirm_frames: int = 3
    lost_frames: int = 5


BABY_CLASSES = {0, 2}


class BabyFilter:
    def __init__(self, config: FilterConfig = None):
        self.cfg = config or FilterConfig()
        self._conf_match_weight = 0.15
        self._reset()

    def _reset(self):
        self._locked_box: Optional[List[float]] = None
        self._candidate: Optional[List[float]] = None
        self._confirm_cnt: int = 0
        self._lost_cnt: int = 0

    @property
    def state(self) -> TrackState:
        if self._locked_box is not None:
            return TrackState.LOCKED
        if self._candidate is not None:
            return TrackState.CANDIDATE
        return TrackState.NONE

    @property
    def locked_box(self) -> Optional[List[float]]:
        return self._locked_box

    @property
    def candidate(self) -> Optional[List[float]]:
        return self._candidate

    @property
    def confirm_cnt(self) -> int:
        return self._confirm_cnt

    def pick_baby(
        self,
        boxes: List[List[float]],
        confs: List[float],
        classes: List[int],
    ) -> TrackResult:
        valid: List[Tuple[List[float], float]] = [
            (box, float(conf))
            for box, conf, cls in zip(boxes, confs, classes)
            if int(cls) in BABY_CLASSES and float(conf) >= self.cfg.conf_threshold
        ]
        valid.sort(key=lambda x: x[1], reverse=True)

        if self._locked_box is None:
            return self._try_lock(valid)
        return self._update_locked(valid)

    def reset(self):
        self._reset()

    def _try_lock(self, valid):
        if not valid:
            self._candidate = None
            self._confirm_cnt = 0
            return TrackResult(state=TrackState.NONE)

        if self._candidate is None:
            top_box, top_conf = valid[0]
        else:
            def score(item):
                box, conf = item
                return _iou(self._candidate, box) + self._conf_match_weight * conf

            top_box, top_conf = max(valid, key=score)

        iou_with_prev = _iou(self._candidate, top_box) if self._candidate is not None else 0.0
        if self._candidate is None or iou_with_prev <= 0.3:
            self._candidate = top_box
            self._confirm_cnt = 1
        else:
            self._candidate = top_box
            self._confirm_cnt += 1

        if self._confirm_cnt >= self.cfg.confirm_frames:
            self._locked_box = self._candidate
            self._candidate = None
            self._confirm_cnt = 0
            self._lost_cnt = 0
            return TrackResult(state=TrackState.LOCKED, box=self._locked_box, conf=top_conf)

        return TrackResult(
            state=TrackState.CANDIDATE,
            box=self._candidate,
            conf=top_conf,
            confirm_cnt=self._confirm_cnt,
            confirm_max=self.cfg.confirm_frames,
        )

    def _update_locked(self, valid):
        if not valid:
            self._lost_cnt += 1
            if self._lost_cnt > self.cfg.lost_frames:
                self._locked_box = None
                self._lost_cnt = 0
                return TrackResult(state=TrackState.NONE)
            return TrackResult(state=TrackState.LOCKED, box=self._locked_box, conf=0.0)

        def score(item):
            box, conf = item
            return _iou(self._locked_box, box) + self._conf_match_weight * conf

        best_box, best_conf = max(valid, key=score)
        best_iou = _iou(self._locked_box, best_box)

        if best_iou > 0.2 or (best_iou > 0.12 and best_conf >= 0.8):
            self._locked_box = best_box
            self._lost_cnt = 0
            return TrackResult(state=TrackState.LOCKED, box=best_box, conf=best_conf)

        self._lost_cnt += 1
        if self._lost_cnt > self.cfg.lost_frames:
            self._locked_box = None
            self._lost_cnt = 0
            return TrackResult(state=TrackState.NONE)
        return TrackResult(state=TrackState.LOCKED, box=self._locked_box, conf=0.0)


def _iou(a, b) -> float:
    x_a, y_a = max(a[0], b[0]), max(a[1], b[1])
    x_b, y_b = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x_b - x_a) * max(0.0, y_b - y_a)
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)
