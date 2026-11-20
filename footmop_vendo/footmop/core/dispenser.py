"""Dispense sequence, run on a worker thread one item at a time.

Per item:
  1. Wait until the IR sensor is clear: before the first item (a hand or an
     old item in the chute -> "please clear the chute", fault after
     blocked_timeout_s) and, for multi-item orders, after every drop until the
     customer has TAKEN that footmop out (no time limit), then pickup_settle_ms.
  2. Arm the drop latch, relay ON, start an independent hard-cutoff timer.
  3. Run the motor for motor_on_ms (or until the drop if stop_on_drop).
  4. Relay OFF, then keep watching the sensor for drop_wait_after_ms.
  5. No drop seen -> fault (jam). Drop seen -> report item, cool down.

The relay is switched off in a ``finally`` block AND by the hard-cutoff
timer, so neither an exception nor a stuck thread can leave the motor on.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from ..config import DispenseCfg

log = logging.getLogger("footmop.dispenser")


class Dispenser:
    def __init__(self, hal, cfg: DispenseCfg,
                 on_item: Callable[[int, int], None],
                 on_done: Callable[[int], None],
                 on_fault: Callable[[int, str, str], None],
                 on_status: Optional[Callable[[int, str, int], None]] = None):
        self.hal = hal
        self.on_status = on_status or (lambda token, phase, index: None)
        self.cfg = cfg
        self.on_item = on_item
        self.on_done = on_done
        self.on_fault = on_fault
        self._lock = threading.Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def start(self, qty: int, token: int) -> bool:
        with self._lock:
            if self._busy:
                log.error("dispense requested while busy - refused")
                self.on_fault(token, "dispenser_busy", "Dispenser was already running.")
                return False
            self._busy = True
        threading.Thread(target=self._run, args=(qty, token), name="dispenser",
                         daemon=True).start()
        return True

    # ------------------------------------------------------------------
    def _run(self, qty: int, token: int) -> None:
        try:
            c = self.cfg
            if c.sensor_enabled:
                # Hand or an old item in the exit before the order starts: wait (then fault).
                code, msg = self._wait_clear(token, "blocked", 1, c.blocked_timeout_s)
                if code:
                    self.on_fault(token, code, msg)
                    return
            for i in range(1, qty + 1):
                self.on_status(token, "spinning", i)
                code, msg = self._one_item(i, qty)
                if code:
                    self.on_fault(token, code, msg)
                    return
                self.on_item(token, i)
                if i < qty:
                    if c.sensor_enabled and c.wait_for_pickup:
                        # One at a time: the customer takes footmop i out before the next drops.
                        code, msg = self._wait_clear(token, "pickup", i, None)
                        if code:
                            self.on_fault(token, code, msg)
                            return
                    time.sleep(c.cooldown_ms / 1000)
            self.on_done(token)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("dispenser crashed")
            self.hal.force_motor_off()
            self.on_fault(token, "dispenser_exception", f"Dispenser error: {exc}")
        finally:
            self.hal.force_motor_off()
            with self._lock:
                self._busy = False

    def _wait_clear(self, token: int, phase: str, index: int, timeout_s):
        """Wait until the IR sensor has been clear for pickup_settle_ms.
        phase "blocked": before an order (hand/old item in the chute), times out.
        phase "pickup":  waiting for the customer to take footmop `index` out."""
        c = self.cfg
        settle = c.pickup_settle_ms / 1000
        start = time.monotonic()
        clear_since = None
        announced = False
        while True:
            now = time.monotonic()
            if self.hal.drop_sensor_active():
                clear_since = None
                if not announced:
                    announced = True
                    log.info("waiting for chute to clear (%s, item %d)", phase, index)
                    self.on_status(token, phase, index)
                if timeout_s is not None and now - start > timeout_s:
                    return ("chute_blocked",
                            f"IR sensor stayed blocked for {timeout_s:.0f} s before dispensing "
                            "(hand or item in the chute, or sensor fault).")
            else:
                if clear_since is None:
                    clear_since = now
                # Item fell past the sensor / was never there: no need to wait the settle time.
                if not announced or now - clear_since >= settle:
                    return (None, None)
            time.sleep(0.05)

    def _one_item(self, i: int, qty: int):
        c = self.cfg

        self.hal.arm_drop()
        cutoff = threading.Timer((c.motor_on_ms + c.hard_cutoff_margin_ms) / 1000,
                                 self._hard_cutoff)
        cutoff.daemon = True
        log.info("item %d/%d: motor ON", i, qty)
        t0 = time.monotonic()
        self.hal.set_motor(True)
        cutoff.start()
        try:
            run_s = c.motor_on_ms / 1000
            if c.sensor_enabled and c.stop_on_drop:
                self.hal.wait_drop(run_s)
            else:
                time.sleep(run_s)
        finally:
            self.hal.set_motor(False)
            cutoff.cancel()
        log.info("item %d/%d: motor OFF after %.2fs", i, qty, time.monotonic() - t0)

        if not c.sensor_enabled:
            return (None, None)
        if not self.hal.wait_drop(c.drop_wait_after_ms / 1000):
            return ("dispense_failure",
                    f"No item detected by the drop sensor for item {i} of {qty} (possible jam or empty slot).")
        n = self.hal.drop_count()
        if n > 1:
            log.warning("item %d: sensor saw %d activations (possible double drop or sensor chatter)", i, n)
        return (None, None)

    def _hard_cutoff(self) -> None:
        log.error("HARD CUTOFF: motor relay forced OFF by watchdog timer")
        self.hal.force_motor_off()
