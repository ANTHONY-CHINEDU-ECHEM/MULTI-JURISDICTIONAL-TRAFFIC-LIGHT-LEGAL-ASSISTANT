"""Structured side of the hybrid RAG: CSV tables loaded into SQLite.

The structured retriever answers the factual questions a regulatory manual
cannot: which interval each phase was displaying at a given millisecond, what
the controller was programmed to show, whether detectors or the MMU had
reported faults, and what the crash telemetry recorded.
"""

import re
import sqlite3

import pandas as pd

from . import config
from .utils import get_logger

LOG = get_logger("store")

TABLES = ["hcs_streets_export", "intersections", "lane_group_geometry", "signal_timing_plans",
          "signal_event_log", "detector_faults", "mmu_events", "crash_events", "jurisdiction_policy"]
INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_event_window ON signal_event_log(window_id, nema_phase, interval_type)",
    "CREATE INDEX IF NOT EXISTS ix_event_time ON signal_event_log(intersection_id, start_epoch_ms, end_epoch_ms)",
    "CREATE INDEX IF NOT EXISTS ix_fault ON detector_faults(intersection_id, nema_phase, fault_start_epoch_ms)",
    "CREATE INDEX IF NOT EXISTS ix_mmu ON mmu_events(intersection_id, event_epoch_ms)",
    "CREATE INDEX IF NOT EXISTS ix_crash ON crash_events(crash_id)",
    "CREATE INDEX IF NOT EXISTS ix_hcs ON hcs_streets_export(intersection_id, scenario_year, timing_plan_id, nema_phase)",
]
READ_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|attach|pragma|create|replace|vacuum)\b", re.IGNORECASE)


def build_database(path=None):
    path = path or config.DB_PATH
    if path.exists():
        path.unlink()
    with sqlite3.connect(path) as conn:
        for name in TABLES:
            csv = config.RAW_DIR / (name + ".csv")
            if not csv.exists():
                raise FileNotFoundError("Missing " + str(csv) + "; run the generate command first")
            frame = pd.read_csv(csv)
            frame.to_sql(name, conn, index=False)
            LOG.info("Loaded %s (%d rows)", name, len(frame))
        for statement in INDEXES:
            conn.execute(statement)
    return path


class StructuredRetriever:
    def __init__(self, path=None):
        path = path or config.DB_PATH
        if not path.exists():
            build_database(path)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def _all(self, sql, params=()):
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def _one(self, sql, params=()):
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def crash(self, crash_id):
        return self._one("SELECT * FROM crash_events WHERE crash_id = ?", (crash_id,))

    def crashes(self, limit=50, intersection_id=None):
        if intersection_id:
            return self._all("SELECT * FROM crash_events WHERE intersection_id = ? ORDER BY crash_epoch_ms LIMIT ?",
                             (intersection_id, limit))
        return self._all("SELECT * FROM crash_events ORDER BY crash_id LIMIT ?", (limit,))

    def intersection(self, intersection_id):
        return self._one("SELECT * FROM intersections WHERE intersection_id = ?", (intersection_id,))

    def lane_group(self, intersection_id, phase):
        return self._one("SELECT * FROM lane_group_geometry WHERE intersection_id = ? AND nema_phase = ?",
                         (intersection_id, int(phase)))

    def policy(self, jurisdiction_code):
        return self._one("SELECT * FROM jurisdiction_policy WHERE jurisdiction_code = ?", (jurisdiction_code,))

    def timing_plan(self, intersection_id, plan_id, phase):
        return self._one("SELECT * FROM signal_timing_plans WHERE intersection_id = ? AND timing_plan_id = ? "
                         "AND nema_phase = ?", (intersection_id, int(plan_id), int(phase)))

    def state_at(self, intersection_id, epoch_ms, window_id=None):
        """Every phase interval active at the given millisecond (the signal state snapshot)."""
        sql = ("SELECT * FROM signal_event_log WHERE intersection_id = ? AND start_epoch_ms <= ? "
               "AND end_epoch_ms > ?")
        params = [intersection_id, int(epoch_ms), int(epoch_ms)]
        if window_id:
            sql += " AND window_id = ?"
            params.append(window_id)
        return self._all(sql + " ORDER BY ring, nema_phase", tuple(params))

    def phase_intervals(self, window_id, phase, interval_type=None):
        sql = "SELECT * FROM signal_event_log WHERE window_id = ? AND nema_phase = ?"
        params = [window_id, int(phase)]
        if interval_type:
            sql += " AND interval_type = ?"
            params.append(interval_type)
        return self._all(sql + " ORDER BY start_epoch_ms", tuple(params))

    def interval_containing(self, window_id, phase, epoch_ms):
        return self._one("SELECT * FROM signal_event_log WHERE window_id = ? AND nema_phase = ? AND start_epoch_ms <= ? "
                         "AND end_epoch_ms > ? ORDER BY start_epoch_ms LIMIT 1",
                         (window_id, int(phase), int(epoch_ms), int(epoch_ms)))

    def last_interval_before(self, window_id, phase, interval_type, epoch_ms):
        return self._one("SELECT * FROM signal_event_log WHERE window_id = ? AND nema_phase = ? AND interval_type = ? "
                         "AND start_epoch_ms <= ? ORDER BY start_epoch_ms DESC LIMIT 1",
                         (window_id, int(phase), interval_type, int(epoch_ms)))

    def active_faults(self, intersection_id, phase, epoch_ms):
        return self._all("SELECT * FROM detector_faults WHERE intersection_id = ? AND nema_phase = ? "
                         "AND fault_start_epoch_ms <= ? AND fault_cleared_epoch_ms > ?",
                         (intersection_id, int(phase), int(epoch_ms), int(epoch_ms)))

    def mmu_events(self, intersection_id, start_ms, end_ms):
        return self._all("SELECT * FROM mmu_events WHERE intersection_id = ? AND event_epoch_ms BETWEEN ? AND ? "
                         "ORDER BY event_epoch_ms", (intersection_id, int(start_ms), int(end_ms)))

    def hcs_rows(self, intersection_id, year=None):
        if year:
            return self._all("SELECT * FROM hcs_streets_export WHERE intersection_id = ? AND scenario_year = ? "
                             "ORDER BY timing_plan_id, nema_phase", (intersection_id, int(year)))
        return self._all("SELECT * FROM hcs_streets_export WHERE intersection_id = ? "
                         "ORDER BY scenario_year, timing_plan_id, nema_phase", (intersection_id,))

    def query(self, sql, params=(), limit=500):
        """Run an analyst supplied read only query with a row cap."""
        if not READ_ONLY.match(sql) or FORBIDDEN.search(sql) or ";" in sql.strip().rstrip(";"):
            raise ValueError("Only single SELECT statements are permitted")
        rows = self.conn.execute(sql.strip().rstrip(";"), params).fetchmany(limit)
        return [dict(r) for r in rows]
