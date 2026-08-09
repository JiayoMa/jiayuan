"""Core detection logic for PV panel monitoring."""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

from .config import DEFAULT_THRESHOLD

logger = logging.getLogger(__name__)


@dataclass
class PanelReading:
    string: int
    module: int
    voltage: float
    current: float

    @property
    def key(self) -> str:
        return f"#{self.string}-PV{self.module}"


@dataclass
class DetectionResult:
    readings: List[PanelReading]
    anomalies: List[PanelReading]
    threshold: float
    source: str

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "source": self.source,
            "anomalies": [r.__dict__ for r in self.anomalies],
            "readings": [r.__dict__ for r in self.readings],
        }


class Detector:
    """Offline detector that flags modules whose current is below a threshold."""

    def __init__(self, threshold: float = DEFAULT_THRESHOLD):
        self.threshold = threshold

    def detect(self, readings: Iterable[PanelReading], source: str = "") -> DetectionResult:
        readings_list = list(readings)
        anomalies = [r for r in readings_list if r.current < self.threshold]
        logger.info("Detection run completed: %s anomalies below %.2fA", len(anomalies), self.threshold)
        return DetectionResult(readings_list, anomalies, self.threshold, source)

    def load_from_csv(self, path: Path) -> List[PanelReading]:
        path = Path(path)
        logger.info("Loading readings from CSV: %s", path)
        readings: List[PanelReading] = []
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    reading = PanelReading(
                        string=int(row["string"]),
                        module=int(row["module"]),
                        voltage=float(row["voltage"]),
                        current=float(row["current"]),
                    )
                    readings.append(reading)
                except (ValueError, KeyError) as exc:
                    logger.error("Invalid row %s: %s", row, exc)
                    raise
        return readings

    @staticmethod
    def to_json(result: DetectionResult) -> str:
        return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
