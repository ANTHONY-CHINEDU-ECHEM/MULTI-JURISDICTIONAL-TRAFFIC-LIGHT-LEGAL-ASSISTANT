"""Shared helpers.

Style note: this repository never contains the ASCII hyphen or any dash
character. Arithmetic subtraction is therefore written with operator.sub for
scalars and numpy.subtract for arrays, and negation with operator.neg or
numpy.negative. The helpers below keep that convention readable.
"""

import json
import logging
import operator
import string
from datetime import datetime, timezone

import numpy as np

sub = operator.sub
neg = operator.neg
vsub = np.subtract
vneg = np.negative

STAMP_FORMAT = "%Y/%m/%d %H:%M:%S"
UPPER_CLASS = "[" + string.ascii_uppercase + "]"
"""Regex class for one uppercase ASCII letter, spelled out so no range hyphen is needed."""


def get_logger(name):
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def gap(a, b):
    """Absolute difference between two scalars."""
    return abs(sub(a, b))


def shortfall(required, provided):
    """How far provided falls short of required, never below zero."""
    return max(0.0, sub(required, provided))


def surplus(required, provided):
    """How far provided exceeds required, never below zero."""
    return max(0.0, sub(provided, required))


def ms_to_stamp(epoch_ms):
    """Format epoch milliseconds (UTC) as YYYY/MM/DD HH:MM:SS.mmm."""
    epoch_ms = int(epoch_ms)
    seconds, millis = divmod(epoch_ms, 1000)
    moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return moment.strftime(STAMP_FORMAT) + "." + str(millis).zfill(3)


def stamp_to_ms(stamp):
    """Parse YYYY/MM/DD HH:MM:SS(.mmm) in UTC into epoch milliseconds."""
    text = stamp.strip()
    millis = 0
    if "." in text:
        text, fraction = text.split(".", 1)
        millis = int((fraction + "000")[:3])
    moment = datetime.strptime(text, STAMP_FORMAT).replace(tzinfo=timezone.utc)
    return int(moment.timestamp()) * 1000 + millis


def ms_between(later_ms, earlier_ms):
    return sub(int(later_ms), int(earlier_ms))


def round_up_to(value, step):
    """Round a positive value up to the next multiple of step (controller resolution)."""
    units = np.ceil(np.round(value / step, 6))
    return float(np.round(units * step, 3))


def write_json(path, payload):
    with open(path, "w", encoding="utf8") as handle:
        json.dump(payload, handle, indent=2, default=_json_default)


def read_json(path):
    with open(path, "r", encoding="utf8") as handle:
        return json.load(handle)


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return str(value)


def contains_dash(text):
    """True when text holds a hyphen, en dash, em dash or similar dash glyph."""
    return any(ch in text for ch in DASH_CHARACTERS)


DASH_CHARACTERS = tuple(chr(code) for code in (45, 8208, 8209, 8210, 8211, 8212, 8213, 8722, 65112, 65123, 65293))


def strip_dashes(text):
    """Replace dash glyphs with a space for display surfaces that must stay dash free."""
    for ch in DASH_CHARACTERS:
        text = text.replace(ch, " ")
    return " ".join(text.split(" ")).replace("  ", " ")
