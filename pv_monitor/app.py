"""Tkinter UI for PV string anomaly detection."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

if __package__ in (None, ""):
    # Allow running as `python pv_monitor/app.py` by adding repo root to sys.path
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from .config import DEFAULT_THRESHOLD, LOG_DIR, LOG_PATH, SAMPLE_DATA_PATH
from .data_access import fetch_recent_runs, load_run_detail, save_detection
from .detection import DetectionResult, Detector, PanelReading

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


class TableView(tk.Frame):
    """Grid view that mimics the control center layout."""

    def __init__(self, master: tk.Misc):
        super().__init__(master)
        self.canvas = tk.Canvas(self, borderwidth=0)
        self.scroll_y = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scroll_x = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.scroll_y.set, xscrollcommand=self.scroll_x.set)

        self.inner = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll_y.grid(row=0, column=1, sticky="ns")
        self.scroll_x.grid(row=1, column=0, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.inner.bind("<Configure>", self._on_frame_configure)
        self.labels: Dict[str, tk.Label] = {}

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def clear(self):
        for widget in self.inner.winfo_children():
            widget.destroy()
        self.labels.clear()

    def render(self, readings: List[PanelReading], anomalies: List[PanelReading]):
        self.clear()
        if not readings:
            tk.Label(self.inner, text="未加载数据", fg="gray").grid(row=0, column=0)
            return
        max_string = max(r.string for r in readings)
        max_module = max(r.module for r in readings)
        header_style = {"bg": "#1f1f1f", "fg": "white", "font": ("Arial", 10, "bold"), "width": 12, "padx": 4, "pady": 4}
        cell_font = ("Consolas", 10)

        # Corner cell
        tk.Label(self.inner, text="串/板", **header_style).grid(row=0, column=0, sticky="nsew")
        for m in range(1, max_module + 1):
            tk.Label(self.inner, text=f"PV{m}", **header_style).grid(row=0, column=m, sticky="nsew")

        reading_map = {(r.string, r.module): r for r in readings}
        anomaly_keys = {(r.string, r.module) for r in anomalies}

        for s in range(1, max_string + 1):
            tk.Label(self.inner, text=f"#{s}", **header_style).grid(row=s, column=0, sticky="nsew")
            for m in range(1, max_module + 1):
                reading = reading_map.get((s, m))
                if not reading:
                    continue
                text = f"{reading.voltage:.1f}V\n{reading.current:.2f}A"
                bg = "#222"
                fg = "lime" if (s, m) not in anomaly_keys else "white"
                if (s, m) in anomaly_keys:
                    bg = "red"
                label = tk.Label(
                    self.inner,
                    text=text,
                    width=12,
                    height=2,
                    bg=bg,
                    fg=fg,
                    font=cell_font,
                    relief="ridge",
                    borderwidth=1,
                    justify="center",
                )
                label.grid(row=s, column=m, sticky="nsew", padx=1, pady=1)
                self.labels[f"{s}-{m}"] = label


class PVMonitorApp(tk.Tk):
    def __init__(self, detector: Optional[Detector] = None):
        super().__init__()
        self.title("光伏组串离线监测")
        self.geometry("1280x720")
        self.detector = detector or Detector()
        self.current_readings: List[PanelReading] = []
        self.current_result: Optional[DetectionResult] = None

        self._build_ui()
        self._load_sample_data()

    def _build_ui(self):
        control = ttk.Frame(self)
        control.pack(side=tk.TOP, fill=tk.X, padx=10, pady=6)

        ttk.Button(control, text="载入CSV", command=self._choose_csv).pack(side=tk.LEFT, padx=4)
        ttk.Button(control, text="载入示例", command=self._load_sample_data).pack(side=tk.LEFT, padx=4)
        ttk.Button(control, text="检测异常", command=self._run_detection).pack(side=tk.LEFT, padx=4)

        ttk.Label(control, text="阈值(A) <").pack(side=tk.LEFT, padx=4)
        self.threshold_var = tk.DoubleVar(value=self.detector.threshold)
        threshold_entry = ttk.Entry(control, width=6, textvariable=self.threshold_var)
        threshold_entry.pack(side=tk.LEFT)
        ttk.Button(control, text="更新阈值", command=self._update_threshold).pack(side=tk.LEFT, padx=4)

        ttk.Button(control, text="查看最近记录", command=self._show_history).pack(side=tk.LEFT, padx=4)

        self.status_var = tk.StringVar(value="准备就绪")
        ttk.Label(control, textvariable=self.status_var, foreground="blue").pack(side=tk.RIGHT)

        self.table = TableView(self)
        self.table.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def _update_threshold(self):
        try:
            value = float(self.threshold_var.get())
        except ValueError:
            messagebox.showerror("错误", "阈值必须是数字")
            return
        self.detector.threshold = value
        self.status_var.set(f"已更新阈值: < {value}A")
        logger.info("Threshold updated to %.2f", value)
        if self.current_readings:
            self._run_detection(save=False)

    def _choose_csv(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if not file_path:
            return
        self._load_csv(file_path)

    def _load_csv(self, path: str):
        try:
            readings = self.detector.load_from_csv(Path(path))
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Failed to load CSV")
            messagebox.showerror("加载失败", str(exc))
            return
        self.current_readings = readings
        self.status_var.set(f"载入 {len(readings)} 条记录: {path}")
        logger.info("Loaded %s readings from %s", len(readings), path)
        self._run_detection(source=path)

    def _load_sample_data(self):
        if not Path(SAMPLE_DATA_PATH).exists():
            messagebox.showerror("缺少示例数据", f"未找到 {SAMPLE_DATA_PATH}")
            return
        self._load_csv(SAMPLE_DATA_PATH)

    def _run_detection(self, source: str = "示例数据", save: bool = True):
        if not self.current_readings:
            messagebox.showwarning("无数据", "请先载入数据文件")
            return
        result = self.detector.detect(self.current_readings, source=source)
        self.current_result = result
        self.table.render(result.readings, result.anomalies)
        if save:
            run_id = save_detection(result)
            self.status_var.set(f"检测完成，记录ID {run_id}，异常 {len(result.anomalies)} 处")
        else:
            self.status_var.set(f"检测完成，异常 {len(result.anomalies)} 处 (未写入数据库)")
        if result.anomalies:
            details = "\n".join(f"串{s.string} - PV{s.module}: {s.current:.2f}A" for s in result.anomalies)
            messagebox.showwarning("发现异常", f"以下组件电流低于阈值 {result.threshold}A:\n{details}")
        logger.info("Detection finished with %s anomalies", len(result.anomalies))

    def _show_history(self):
        runs = fetch_recent_runs(limit=20)
        if not runs:
            messagebox.showinfo("历史记录", "没有检测记录")
            return
        win = tk.Toplevel(self)
        win.title("最近检测记录")
        tree = ttk.Treeview(win, columns=("id", "time", "source", "threshold", "anomalies"), show="headings")
        for col, text in zip(tree["columns"], ["ID", "时间(UTC)", "来源", "阈值", "异常数"]):
            tree.heading(col, text=text)
        for r in runs:
            tree.insert("", "end", values=(r["id"], r["run_at"], r["source"], r["threshold"], r["anomalies"]))
        tree.pack(fill=tk.BOTH, expand=True)

        def on_detail(event):  # noqa: ANN001
            item = tree.selection()
            if not item:
                return
            run_id = int(tree.item(item[0], "values")[0])
            detail = load_run_detail(run_id)
            if not detail:
                messagebox.showerror("错误", "无法读取详情")
                return
            msg = f"来源: {detail['source']}\n阈值: {detail['threshold']}A\n异常数: {len(detail['anomalies'])}"
            if detail["anomalies"]:
                lines = [
                    f"串{a['string']} - PV{a['module']}: {a['current']}A ({a['voltage']}V)"
                    for a in detail["anomalies"]
                ]
                msg += "\n\n异常列表:\n" + "\n".join(lines)
            messagebox.showinfo("详情", msg)

        tree.bind("<Double-1>", on_detail)


def run_headless(detector: Detector, csv_path: Optional[str]):
    path = csv_path or SAMPLE_DATA_PATH
    readings = detector.load_from_csv(Path(path))
    result = detector.detect(readings, source=path)
    save_detection(result)
    print("完成检测，异常数量:", len(result.anomalies))
    for a in result.anomalies:
        print(f"串{a.string} PV{a.module}: {a.current}A")


def main():
    parser = argparse.ArgumentParser(description="光伏组串离线异常检测")
    parser.add_argument("--headless", action="store_true", help="在命令行模式下运行检测")
    parser.add_argument("--csv", help="待检测的CSV文件路径", default=None)
    parser.add_argument("--threshold", type=float, help="自定义电流阈值")
    args = parser.parse_args()

    detector = Detector(threshold=args.threshold or DEFAULT_THRESHOLD)

    if args.headless:
        run_headless(detector, args.csv)
    else:
        app = PVMonitorApp(detector=detector)
        app.mainloop()


if __name__ == "__main__":
    main()
