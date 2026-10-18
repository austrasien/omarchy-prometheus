"""What the world looked like during a session: power source, weather.

Both are read locally. The weather comes from the file the Omarchy weather
plugin writes on each reading; Prometheus never fetches it itself.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

POWER_SUPPLY = Path("/sys/class/power_supply")
WEATHER_FILE = Path(os.path.expanduser("~/.local/state/omarchy/weather-current.json"))
WEATHER_MAX_AGE_MS = 3 * 3600 * 1000


def on_battery(root: Path = POWER_SUPPLY) -> bool:
    """True when the machine has mains supplies and none is plugged in."""
    mains = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return False
    for d in entries:
        try:
            if (d / "type").read_text().strip() == "Mains":
                mains.append((d / "online").read_text().strip() == "1")
        except OSError:
            continue
    return bool(mains) and not any(mains)


# WMO weather codes (Open-Meteo) and wttr.in codes, folded into a few kinds.
_WMO = {
    "storm": {95, 96, 99},
    "snow": {71, 73, 75, 77, 85, 86},
    "rain": {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82},
    "clear": {0, 1},
}
_WTTR = {
    "storm": {200, 386, 389, 392, 395},
    "snow": {179, 182, 185, 227, 230, 281, 284, 311, 314, 317, 320, 323, 326, 329, 332, 335, 338, 350, 362, 365, 368, 371, 374, 377},
    "rain": {176, 263, 266, 293, 296, 299, 302, 305, 308, 353, 356, 359},
    "clear": {113},
}


def classify(reading: dict) -> tuple[str | None, float | None]:
    """(kind, temperature °C) from a weather-current.json reading."""
    temp = reading.get("tempC")
    temp = float(temp) if isinstance(temp, (int, float)) else None
    kind = None
    for codes, key in ((_WMO, "wmoCode"), (_WTTR, "wttrCode")):
        code = reading.get(key)
        if isinstance(code, (int, float)):
            for name, values in codes.items():
                if int(code) in values:
                    kind = name
                    break
            break
    if kind == "clear" and reading.get("isDay") is False:
        kind = None  # a clear night is not sunshine
    return kind, temp


def weather_now(at: int, path: Path = WEATHER_FILE) -> tuple[str | None, float | None]:
    try:
        reading = json.loads(path.read_text())
    except (OSError, ValueError):
        return None, None
    if not isinstance(reading, dict) or abs(at - int(reading.get("at", 0))) > WEATHER_MAX_AGE_MS:
        return None, None  # stale: the weather plugin has not run lately
    return classify(reading)
