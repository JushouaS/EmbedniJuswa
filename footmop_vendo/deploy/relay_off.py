#!/usr/bin/env python3
"""Drive the motor relay pin to its OFF level. Run by systemd after the
kiosk stops or crashes, so a dead process can never leave the motor on."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import lgpio
    from footmop.config import load_config
    from footmop.hal.lgpio_hal import _find_chip

    cfg = load_config(os.environ.get("FOOTMOP_CONFIG", "/etc/footmop/config.toml"))
    chip = _find_chip() if str(cfg.pins.chip).lower() == "auto" else int(cfg.pins.chip)
    off = 0 if cfg.dispense.relay_active_high else 1
    h = lgpio.gpiochip_open(chip)
    lgpio.gpio_claim_output(h, cfg.pins.motor_relay, off)
    lgpio.gpio_write(h, cfg.pins.motor_relay, off)
    # Note: lgpio may release the line on close; the boot-time config.txt
    # "gpio=" line and the relay module's own pull keep it off afterwards.
    lgpio.gpiochip_close(h)
    print(f"relay_off: GPIO{cfg.pins.motor_relay} set to {off}")
except Exception as exc:  # never fail the unit stop
    print(f"relay_off: {exc}", file=sys.stderr)
