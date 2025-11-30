import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "pv_monitor.db")
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_PATH = os.path.join(LOG_DIR, "pv_monitor.log")
DEFAULT_THRESHOLD = 0.5
SAMPLE_DATA_PATH = os.path.join(os.path.dirname(__file__), "sample_data", "sample_snapshot.csv")
