"""Configuration loading and validation.

Defaults live in the dataclasses below. A TOML file (see config.example.toml)
overrides any subset of them. Validation errors stop the app at boot with a
clear message rather than misbehaving at the coin slot.
"""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

try:  # Python 3.11+ (Raspberry Pi OS Bookworm ships 3.11)
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - fallback for 3.9/3.10
    import tomli as _toml  # type: ignore


class ConfigError(ValueError):
    pass


@dataclass
class MachineCfg:
    name: str = "Footmop ni Kuya J"
    currency: str = "₱"            # ₱
    price_per_item: int = 5              # pesos; must be a multiple of coin.value
    max_per_transaction: int = 0         # 0 = no cap: the limit is the stock available


@dataclass
class TimingCfg:
    inactivity_timeout_s: float = 60.0   # idle time in Quantity/Payment before warning
    warning_countdown_s: float = 15.0    # "Still there?" countdown before cancelling
    success_screen_s: float = 6.0
    admin_sequence: str = "GBGBG"        # short presses (G=GREEN, B=BLUE) that open admin
    admin_sequence_window_s: float = 5.0 # ...all within this many seconds
    admin_pin_idle_s: float = 30.0       # PIN screen closes itself after this long idle
    admin_idle_timeout_s: float = 120.0
    admin_pin_lockout_s: float = 60.0
    admin_pin_max_attempts: int = 5


@dataclass
class PinsCfg:
    chip: Any = "auto"                   # "auto" or gpiochip number
    button_green: int = 5                # physical pin 29
    button_blue: int = 6                 # physical pin 31
    button_white: int = 13               # physical pin 33
    coin: int = 19                       # physical pin 35
    drop_sensor: int = 26                # physical pin 37
    motor_relay: int = 20                # physical pin 38
    coin_enable: int = -1                # physical pin 40 (GPIO21) if used; -1 = not wired


@dataclass
class ButtonsCfg:
    active_low: bool = True              # button between GPIO and GND, internal pull-up
    debounce_ms: float = 60.0
    poll_interval_ms: float = 5.0


@dataclass
class CoinCfg:
    value: int = 5                       # pesos credited per accepted coin
    pulses_per_coin: int = 1             # single-coin acceptor normally sends 1 pulse
    active_low: bool = True              # pulse pulls the line LOW (open collector / opto)
    pulse_min_ms: float = 15.0           # shorter = electrical noise
    pulse_max_ms: float = 150.0          # longer = stuck/garbage
    min_gap_ms: float = 40.0             # pulses closer than this = bounce
    burst_settle_ms: float = 250.0       # only used when pulses_per_coin > 1
    glitch_filter_us: int = 3000         # kernel-level edge glitch filter
    stuck_active_s: float = 2.0          # line held active this long = wiring fault
    enable_active_high: bool = True      # coin_enable relay polarity (if wired)


@dataclass
class DispenseCfg:
    relay_active_high: bool = True       # use an active-HIGH relay/MOSFET module (boot-safe)
    motor_on_ms: float = 2000.0          # relay ON time per item
    stop_on_drop: bool = False           # cut motor as soon as the sensor sees the item
    drop_wait_after_ms: float = 1500.0   # keep watching the sensor after motor stops
    cooldown_ms: float = 1000.0          # pause between items
    hard_cutoff_margin_ms: float = 500.0 # independent watchdog forces relay off
    sensor_enabled: bool = True          # TCRT5000 drop sensor present
    sensor_active_low: bool = True       # TCRT5000 module DO goes LOW when it sees the item
    sensor_glitch_us: int = 1000


@dataclass
class AdminCfg:
    pin: str = "1234"


@dataclass
class StorageCfg:
    db_path: str = "/var/lib/footmop/footmop.db"
    log_dir: str = "/var/log/footmop"


@dataclass
class DisplayCfg:
    fullscreen: bool = True
    hide_cursor: bool = True
    touch_enabled: bool = False          # buttons-only kiosk: ignore any touch/mouse input
    window_width: int = 480              # used when not fullscreen
    window_height: int = 320


@dataclass
class Config:
    machine: MachineCfg = field(default_factory=MachineCfg)
    timing: TimingCfg = field(default_factory=TimingCfg)
    pins: PinsCfg = field(default_factory=PinsCfg)
    buttons: ButtonsCfg = field(default_factory=ButtonsCfg)
    coin: CoinCfg = field(default_factory=CoinCfg)
    dispense: DispenseCfg = field(default_factory=DispenseCfg)
    admin: AdminCfg = field(default_factory=AdminCfg)
    storage: StorageCfg = field(default_factory=StorageCfg)
    display: DisplayCfg = field(default_factory=DisplayCfg)

    def validate(self) -> None:
        m, c, d, t = self.machine, self.coin, self.dispense, self.timing
        errs = []
        if c.value <= 0:
            errs.append("coin.value must be > 0")
        if m.price_per_item <= 0:
            errs.append("machine.price_per_item must be > 0")
        elif m.price_per_item % c.value != 0:
            errs.append(
                f"machine.price_per_item ({m.price_per_item}) must be a multiple of "
                f"coin.value ({c.value}) or customers can never pay exactly")
        if m.max_per_transaction < 0:
            errs.append("machine.max_per_transaction must be >= 0 (0 = limited by stock only)")
        if c.pulses_per_coin < 1:
            errs.append("coin.pulses_per_coin must be >= 1")
        if not (0 < c.pulse_min_ms < c.pulse_max_ms):
            errs.append("coin.pulse_min_ms must be > 0 and < coin.pulse_max_ms")
        if c.glitch_filter_us / 1000.0 >= c.pulse_min_ms:
            errs.append("coin.glitch_filter_us must be shorter than coin.pulse_min_ms")
        if d.motor_on_ms <= 0:
            errs.append("dispense.motor_on_ms must be > 0")
        if t.inactivity_timeout_s <= 0 or t.warning_countdown_s < 0:
            errs.append("timing values must be positive")
        if not str(self.admin.pin).isdigit() or len(str(self.admin.pin)) < 4:
            errs.append("admin.pin must be at least 4 digits")
        if self.admin.pin == "1234":
            # Not fatal, but loud.
            import logging
            logging.getLogger("footmop.config").warning(
                "admin.pin is still the default 1234 - change it in config.toml")
        used = {}
        for name in ("button_green", "button_blue", "button_white", "coin",
                     "drop_sensor", "motor_relay", "coin_enable"):
            pin = getattr(self.pins, name)
            if pin is None or pin < 0:
                continue
            if pin in used:
                errs.append(f"pins.{name} and pins.{used[pin]} both use GPIO{pin}")
            used[pin] = name
            # GPIO used by typical 3.5" SPI hats (SPI0 + DC/RST/touch IRQ)
            if pin in (7, 8, 9, 10, 11, 17, 24, 25):
                errs.append(f"pins.{name}=GPIO{pin} is used by the 3.5\" SPI display hat")
        if errs:
            raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errs))


def _merge(dc_obj: Any, data: Dict[str, Any], path: str) -> None:
    names = {f.name: f for f in dataclasses.fields(dc_obj)}
    for key, value in data.items():
        if key not in names:
            raise ConfigError(f"Unknown config key: {path}{key}")
        current = getattr(dc_obj, key)
        if dataclasses.is_dataclass(current):
            if not isinstance(value, dict):
                raise ConfigError(f"{path}{key} must be a table")
            _merge(current, value, f"{path}{key}.")
        else:
            if isinstance(current, bool) and not isinstance(value, bool):
                raise ConfigError(f"{path}{key} must be true/false")
            if isinstance(current, float) and isinstance(value, int) and not isinstance(value, bool):
                value = float(value)
            setattr(dc_obj, key, value)


def load_config(path: Optional[str]) -> Config:
    cfg = Config()
    if path:
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"Config file not found: {p}")
        with p.open("rb") as fh:
            _merge(cfg, _toml.load(fh), "")
    env_db = os.environ.get("FOOTMOP_DB")
    if env_db:
        cfg.storage.db_path = env_db
    cfg.validate()
    return cfg
