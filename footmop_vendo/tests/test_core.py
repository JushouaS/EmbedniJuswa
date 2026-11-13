import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from footmop.config import Config, ConfigError, CoinCfg, DispenseCfg  # noqa: E402
from footmop.core import store as st  # noqa: E402
from footmop.core.coin import CoinDecoder  # noqa: E402
from footmop.core.debounce import Debouncer  # noqa: E402
from footmop.core.dispenser import Dispenser  # noqa: E402
from footmop.core.state import Btn, Kiosk, State  # noqa: E402
from footmop.core.store import Store  # noqa: E402

MS = 1_000_000  # ns per ms


# ----------------------------------------------------------------- debounce
def test_debounce_ignores_bounce_and_reports_once():
    d = Debouncer(0.05, initial_level=1, active_low=True)
    events = []
    t = 0.0
    # bouncy press: 1,0,1,0,0,0...
    for lvl in [0, 1, 0, 1, 0]:
        t += 0.002
        r = d.update(lvl, t)
        if r is not None:
            events.append(r)
    for _ in range(40):
        t += 0.005
        r = d.update(0, t)
        if r is not None:
            events.append(r)
    assert events == [True]
    for _ in range(40):
        t += 0.005
        r = d.update(1, t)
        if r is not None:
            events.append(r)
    assert events == [True, False]


def test_debounce_rejects_short_spike():
    d = Debouncer(0.05, 1)
    out = [d.update(0, 0.0), d.update(0, 0.02), d.update(1, 0.03), d.update(1, 0.2)]
    assert all(o is None for o in out)


# --------------------------------------------------------------------- coin
def _decoder(**kw):
    cfg = CoinCfg(**kw)
    coins, rejects = [], []
    dec = CoinDecoder(cfg, lambda v, p: coins.append((v, p)), rejects.append)
    return dec, coins, rejects


def _pulse(dec, start_ms, width_ms):
    dec.edge(0, int(start_ms * MS), start_ms / 1000)
    dec.edge(1, int((start_ms + width_ms) * MS), (start_ms + width_ms) / 1000)


def test_coin_valid_pulse_credits_five():
    dec, coins, rejects = _decoder()
    _pulse(dec, 1000, 40)
    assert coins == [(5, 1)] and rejects == []


def test_coin_noise_too_short_rejected():
    dec, coins, rejects = _decoder()
    for i in range(5):
        _pulse(dec, 1000 + i * 10, 3)
    assert coins == [] and len(rejects) == 5


def test_coin_too_long_rejected():
    dec, coins, rejects = _decoder()
    _pulse(dec, 1000, 400)
    assert coins == [] and "too long" in rejects[0]


def test_coin_bounce_gap_rejected_then_next_real_coin_ok():
    dec, coins, rejects = _decoder()
    _pulse(dec, 1000, 40)        # real coin, ends at 1040
    _pulse(dec, 1050, 20)        # 10 ms later -> bounce
    _pulse(dec, 1600, 40)        # next real coin
    assert coins == [(5, 1), (5, 1)]
    assert any("gap" in r for r in rejects)


def test_coin_multi_pulse_bursts():
    dec, coins, rejects = _decoder(pulses_per_coin=2, burst_settle_ms=200)
    _pulse(dec, 1000, 30)
    _pulse(dec, 1100, 30)
    dec.poll(1.2)                # not settled yet
    assert coins == []
    dec.poll(1.4)
    assert coins == [(5, 2)]
    _pulse(dec, 3000, 30)        # lone pulse = incomplete
    dec.poll(3.5)
    assert coins == [(5, 2)] and any("incomplete" in r for r in rejects)


def test_coin_stuck_line_reported():
    dec, coins, rejects = _decoder()
    dec.edge(0, 1000 * MS, 1.0)
    dec.poll(3.5)
    assert any("stuck" in r for r in rejects)
    dec.edge(1, 5000 * MS, 5.0)  # release after stuck -> not a coin
    assert coins == []


# -------------------------------------------------------------------- store
def test_store_persists_stock_and_recovers(tmp_path):
    path = str(tmp_path / "f.db")
    s = Store(path, 25)
    s.set_stock(10)
    sid = s.open_session(25)
    s.add_coin(sid, 5, 1, "payment")
    s.add_coin(sid, 5, 1, "payment")
    s.begin_dispense(sid, 2, 25, 50)
    s.record_item_dispensed(sid)
    s.close()                                  # "power cut"
    s2 = Store(path, 25)
    assert s2.get_stock() == 9
    findings = s2.recover_on_boot()
    assert findings and "1 item(s) owed" in findings[0]
    f = s2.active_fault()
    assert f["code"] == "power_interrupted" and f["owed_items"] == 1
    assert s2.get_session(sid)["status"] == st.INTERRUPTED


def test_store_recovery_open_session_with_credit(tmp_path):
    s = Store(str(tmp_path / "f.db"), 25)
    sid = s.open_session(25)
    s.add_coin(sid, 5, 1, "payment")
    s.recover_on_boot()
    assert s.get_session(sid)["status"] == st.ABANDONED
    assert s.active_fault() is None


def test_stock_never_negative(tmp_path):
    s = Store(str(tmp_path / "f.db"), 25)
    s.set_stock(0)
    s.record_item_dispensed(None)
    assert s.get_stock() == 0


# ----------------------------------------------------------- state machine
class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeFx:
    def __init__(self):
        self.dispenses = []
        self.coin_enabled = None
        self.motor_off_calls = 0

    def start_dispense(self, qty, token):
        self.dispenses.append((qty, token))

    def set_coin_acceptor(self, enabled):
        self.coin_enabled = enabled

    def force_motor_off(self):
        self.motor_off_calls += 1


@pytest.fixture
def k(tmp_path):
    cfg = Config()
    cfg.machine.price_per_item = 25
    cfg.machine.max_per_transaction = 5
    store = Store(str(tmp_path / "k.db"), 25)
    store.set_stock(3)
    clock = FakeClock()
    kiosk = Kiosk(cfg, store, FakeFx(), clock)
    kiosk.boot()
    return kiosk


def pay(k, pesos):
    for _ in range(pesos // 5):
        k.on_coin(5, 1)


def test_happy_path(k):
    assert k.state == State.LANDING
    k.press(Btn.WHITE)
    assert k.state == State.QUANTITY and k.qty == 1
    k.press(Btn.BLUE)
    k.press(Btn.BLUE)
    k.press(Btn.BLUE)               # capped by stock 3
    assert k.qty == 3 and k.max_qty == 3
    k.press(Btn.GREEN)
    assert k.qty == 2
    k.press(Btn.WHITE)
    assert k.state == State.PAYMENT and k.amount_due == 50
    pay(k, 45)
    assert k.state == State.PAYMENT and k.remaining == 5
    k.on_coin(5, 1)
    assert k.state == State.DISPENSING
    qty, tok = k.fx.dispenses[-1]
    assert qty == 2
    k.on_item_dropped(tok, 1)
    k.on_item_dropped(tok, 2)
    k.on_dispense_done(tok)
    assert k.state == State.SUCCESS
    assert k.stock == 1
    assert k.store.get_session(k.session_id or 1)["status"] in (st.COMPLETED,)
    k.clock.t += 10
    k.tick()
    assert k.state == State.LANDING


def test_qty_min_is_one(k):
    k.action("start")
    k.action("dec")
    k.action("dec")
    assert k.qty == 1


def test_max_per_transaction_cap(k):
    k.store.set_stock(50)
    k.action("start")
    for _ in range(10):
        k.action("inc")
    assert k.qty == 5


def test_sold_out_blocks_purchase(k):
    k.store.set_stock(0)
    k.exit_admin()
    k._go_home()
    assert k.state == State.SOLD_OUT
    k.press(Btn.WHITE)
    assert k.state == State.SOLD_OUT
    k.on_coin(5, 1)                 # logged as unclaimed
    assert k.store.sales_summary()["unclaimed_coins"] == 5


def test_coin_on_landing_starts_session_with_credit(k):
    k.on_coin(5, 1)
    assert k.state == State.QUANTITY and k.credit == 5


def test_inactivity_warning_then_cancel_forfeits_credit(k):
    k.action("start")
    k.action("confirm")
    pay(k, 10)
    sid = k.session_id
    k.clock.t += 61
    k.tick()
    assert k.warning and k.state == State.PAYMENT
    k.clock.t += 16
    k.tick()
    assert k.state == State.LANDING and k.credit == 0
    s = k.store.get_session(sid)
    assert s["status"] == st.ABANDONED and s["credit"] == 10
    # not carried over to the next customer
    k.action("start")
    assert k.credit == 0


def test_warning_dismissed_by_press_without_side_effect(k):
    k.action("start")
    k.action("inc")
    k.clock.t += 61
    k.tick()
    assert k.warning
    k.press(Btn.BLUE)               # dismiss only, must not change qty
    assert not k.warning and k.qty == 2


def test_coin_during_warning_is_credited_and_dismisses(k):
    k.action("start")
    k.action("confirm")
    k.clock.t += 61
    k.tick()
    k.on_coin(5, 1)
    assert not k.warning and k.credit == 5


def test_overpayment_recorded(k):
    k.on_coin(5, 1)
    for _ in range(5):
        k.on_coin(5, 1)             # P30 credit while choosing qty
    k.action("confirm")             # qty 1, P25 due -> dispense immediately
    assert k.state == State.DISPENSING and k.overpaid == 5


def test_dispense_fault_partial_locks_machine(k):
    k.action("start")
    k.action("inc")
    k.action("confirm")
    pay(k, 50)
    _, tok = k.fx.dispenses[-1]
    k.on_item_dropped(tok, 1)
    k.on_dispense_fault(tok, "dispense_failure", "No item detected.")
    assert k.state == State.FAULT
    assert k.stock == 2              # only the confirmed item was deducted
    f = k.store.active_fault()
    assert f["owed_items"] == 1
    # locked: buttons and coins do nothing useful
    k.press(Btn.WHITE)
    assert k.state == State.FAULT
    # late messages from the dead run are ignored
    k.on_dispense_done(tok)
    assert k.state == State.FAULT


def test_dispense_watchdog(k):
    k.action("start")
    k.action("confirm")
    pay(k, 25)
    k.clock.t += 120
    k.tick()
    assert k.state == State.FAULT
    assert k.store.active_fault()["code"] == "dispense_timeout"


def test_admin_combo_pin_and_clear_fault(k):
    k.store.add_fault("x", "test")
    k._go_home()
    assert k.state == State.FAULT
    k.press(Btn.GREEN)
    k.press(Btn.BLUE)
    k.clock.t += 3.1
    k.tick()
    assert k.state == State.ADMIN_PIN
    assert not k.submit_pin("0000")
    assert k.submit_pin("1234")
    k.admin_clear_faults()
    k.admin_set_stock(20)
    k.admin_set_price(23)            # not a multiple of 5 -> refused
    assert k.price == 25
    k.admin_set_price(30)
    k.exit_admin()
    assert k.state == State.LANDING and k.stock == 20 and k.price == 30


def test_admin_combo_not_available_mid_transaction(k):
    k.action("start")
    k.press(Btn.BLUE)
    k.press(Btn.GREEN)
    k.clock.t += 5
    k.tick()
    assert k.state == State.QUANTITY


def test_pin_lockout(k):
    k.open_admin()
    for _ in range(5):
        k.submit_pin("9999")
    assert k.pin_locked_seconds > 0
    assert not k.submit_pin("1234")
    k.clock.t += 61
    assert k.submit_pin("1234")


def test_coin_during_dispensing_goes_to_next_order(k):
    k.action("start")
    k.action("confirm")
    pay(k, 25)
    _, tok = k.fx.dispenses[-1]
    k.on_coin(5, 1)
    k.on_item_dropped(tok, 1)
    k.on_dispense_done(tok)
    k.action("done")
    assert k.state == State.QUANTITY and k.credit == 5


def test_cancel_only_without_credit(k):
    k.action("start")
    k.on_coin(5, 1)
    k.action("cancel")
    assert k.state == State.QUANTITY


def test_coin_acceptor_inhibited_when_not_selling(k):
    assert k.fx.coin_enabled is True
    k.action("start")
    k.action("confirm")
    pay(k, 25)
    assert k.fx.coin_enabled is False   # DISPENSING


# -------------------------------------------------------------- dispenser
class SimHAL:
    def __init__(self, drop=True, blocked=False, drop_delay=0.05):
        self.drop, self.blocked, self.delay = drop, blocked, drop_delay
        self.motor = False
        self.ev = threading.Event()
        self.n = 0
        self.history = []

    def drop_sensor_active(self):
        return self.blocked

    def arm_drop(self):
        self.ev.clear()
        self.n = 0

    def wait_drop(self, t):
        return self.ev.wait(t)

    def drop_count(self):
        return self.n

    def set_motor(self, on):
        self.motor = on
        self.history.append(on)
        if on and self.drop:
            def fire():
                self.n += 1
                self.ev.set()
            threading.Timer(self.delay, fire).start()

    def force_motor_off(self):
        self.motor = False


def _run_dispenser(hal, qty, **cfg_kw):
    cfg = DispenseCfg(motor_on_ms=100, drop_wait_after_ms=100, cooldown_ms=10, **cfg_kw)
    res = {"items": [], "done": False, "fault": None}
    finished = threading.Event()

    def done(tok):
        res["done"] = True
        finished.set()

    def fault(tok, code, msg):
        res["fault"] = code
        finished.set()

    d = Dispenser(hal, cfg, lambda tok, i: res["items"].append(i), done, fault)
    d.start(qty, 1)
    assert finished.wait(5)
    time.sleep(0.05)
    assert hal.motor is False
    return res


def test_dispenser_ok():
    r = _run_dispenser(SimHAL(), 3)
    assert r["items"] == [1, 2, 3] and r["done"]


def test_dispenser_jam():
    r = _run_dispenser(SimHAL(drop=False), 2)
    assert r["items"] == [] and r["fault"] == "dispense_failure"


def test_dispenser_chute_blocked():
    r = _run_dispenser(SimHAL(blocked=True), 1)
    assert r["fault"] == "chute_blocked"


def test_dispenser_without_sensor_assumes_success():
    r = _run_dispenser(SimHAL(drop=False), 2, sensor_enabled=False)
    assert r["items"] == [1, 2] and r["done"]


# ------------------------------------------------------------------ config
def test_config_rejects_bad_price():
    c = Config()
    c.machine.price_per_item = 23
    with pytest.raises(ConfigError):
        c.validate()


def test_config_rejects_display_pins():
    c = Config()
    c.pins.coin = 24
    with pytest.raises(ConfigError):
        c.validate()


# ------------------------------------------------- buttons-only behaviour
def test_green_at_qty_one_cancels_when_unpaid(k):
    k.press(Btn.WHITE)
    k.press(Btn.GREEN)
    assert k.state == State.LANDING
    # still holding GREEN, then BLUE: must NOT open admin (held across screen change)
    k.press(Btn.BLUE)
    k.clock.t += 5
    k.tick()
    assert k.state == State.LANDING


def test_cannot_go_below_paid_items_and_coins_drive_qty(tmp_path):
    cfg = Config()                      # default price P5
    store = Store(str(tmp_path / "p.db"), cfg.machine.price_per_item)
    store.set_stock(10)
    kk = Kiosk(cfg, store, FakeFx(), FakeClock())
    kk.boot()
    assert kk.price == 5
    for _ in range(3):
        kk.on_coin(5, 1)                # coins first, from the landing screen
    assert kk.state == State.QUANTITY and kk.qty == 3 and kk.min_qty == 3
    kk.press(Btn.GREEN)
    assert kk.qty == 3 and kk.state == State.QUANTITY
    kk.press(Btn.BLUE)
    kk.press(Btn.WHITE)
    assert kk.state == State.PAYMENT and kk.coins_needed == 1
    kk.on_coin(5, 1)
    assert kk.state == State.DISPENSING and kk.overpaid == 0


def test_white_hold_exits_admin_without_selecting(k):
    navs = []
    k.admin_nav = lambda b, p: navs.append((b, p))
    k.open_admin()
    k.submit_pin("1234")
    k.press(Btn.WHITE)
    k.clock.t += 2.1
    k.tick()
    assert k.state == State.LANDING
    k.release(Btn.WHITE)
    assert navs == [(Btn.WHITE, True)]   # no release->select after exiting
