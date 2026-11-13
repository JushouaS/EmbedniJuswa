"""All kiosk screens - designed for THREE PHYSICAL BUTTONS, no touch.

Every screen ends with a legend bar whose three keycaps sit in the same
left/centre/right order and colours as the real GREEN / WHITE / BLUE buttons,
so the customer always sees what each button does right now.

Screens only *read* the Kiosk; all input goes through Kiosk.press/release.
To keep a slow SPI panel smooth, widgets are only restyled when their
content actually changes.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from PyQt5.QtCore import QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..core.state import Btn, Kiosk
from . import theme as T

Legend = Optional[str]


class Ctx:
    def __init__(self, sc: T.Scale, kiosk: Kiosk, hal):
        self.sc = sc
        self.kiosk = kiosk
        self.cfg = kiosk.cfg
        self.hal = hal

    def money(self, n: int) -> str:
        return f"{self.cfg.machine.currency}{n:,}"


def _set(lbl: QLabel, text: str) -> None:
    if lbl.text() != text:
        lbl.setText(text)


# ============================================================ building blocks
class Header(QWidget):
    def __init__(self, ctx: Ctx):
        super().__init__()
        sc = ctx.sc
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.title = T.label(sc, ctx.cfg.machine.name, 14, T.ACCENT, True,
                             align=Qt.AlignLeft | Qt.AlignVCenter)
        self.status = T.label(sc, "", 12, T.MUTED, align=Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.title, 1)
        lay.addWidget(self.status)
        self.setFixedHeight(sc(24))


class LegendBar(QWidget):
    """Non-interactive keycaps mirroring the physical buttons."""

    SPEC = ((Btn.GREEN, T.GREEN, T.TEXT), (Btn.WHITE, T.WHITE, "#10202F"),
            (Btn.BLUE, T.BLUE, T.TEXT))

    def __init__(self, ctx: Ctx):
        super().__init__()
        self.sc = ctx.sc
        sc = self.sc
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(sc(8))
        self.caps = {}
        self._cur = {}
        for btn, bg, fg in self.SPEC:
            lb = QLabel()
            lb.setAlignment(Qt.AlignCenter)
            lb.setFont(T.font(sc, 16, True))
            lay.addWidget(lb, 1)
            self.caps[btn] = (lb, bg, fg)
            self._cur[btn] = object()
        self.setFixedHeight(sc(44))
        self.set()

    def set(self, green: Legend = None, white: Legend = None, blue: Legend = None) -> None:
        sc = self.sc
        for btn, text in ((Btn.GREEN, green), (Btn.WHITE, white), (Btn.BLUE, blue)):
            if self._cur[btn] == text:
                continue
            self._cur[btn] = text
            lb, bg, fg = self.caps[btn]
            r = sc(12)
            if text:
                lb.setText(text)
                # thick bottom edge makes it read as a physical key
                lb.setStyleSheet(f"background: {bg}; color: {fg}; border-radius: {r}px;"
                                 f" border-bottom: {sc(4)}px solid rgba(0,0,0,90);")
            else:
                lb.setText("")
                lb.setStyleSheet(f"background: transparent; border: {sc(2)}px dashed"
                                 f" rgba(255,255,255,25); border-radius: {r}px;")


class CoinRow(QWidget):
    """One circle per coin needed: filled = inserted, outline = still needed."""

    MAX_DOTS = 12

    def __init__(self, ctx: Ctx):
        super().__init__()
        self.ctx = ctx
        self.paid = 0
        self.total = 0
        self.setFixedHeight(ctx.sc(46))

    def set(self, paid: int, total: int) -> None:
        if (paid, total) != (self.paid, self.total):
            self.paid, self.total = paid, total
            self.update()

    def paintEvent(self, ev) -> None:
        if self.total <= 0:
            return
        sc = self.ctx.sc
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if self.total > self.MAX_DOTS:   # too many coins for dots: draw a bar
            bh = sc(16)
            y = (h - bh) / 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.PANEL))
            p.drawRoundedRect(QRectF(0, y, w, bh), bh / 2, bh / 2)
            p.setBrush(QColor(T.SUCCESS))
            p.drawRoundedRect(QRectF(0, y, w * min(1, self.paid / self.total), bh), bh / 2, bh / 2)
            return
        gap = sc(6)
        d = min(sc(40), (w - gap * (self.total - 1)) / self.total)
        x = (w - (self.total * d + (self.total - 1) * gap)) / 2
        y = (h - d) / 2
        f = T.font(sc, 1)
        f.setPixelSize(max(8, int(d * 0.32)))
        f.setBold(True)
        p.setFont(f)
        label = f"{self.ctx.cfg.machine.currency}{self.ctx.cfg.coin.value}"
        for i in range(self.total):
            r = QRectF(x + i * (d + gap), y, d, d)
            if i < self.paid:
                p.setPen(QPen(QColor("#C78F00"), sc(2)))
                p.setBrush(QColor(T.ACCENT))
                p.drawEllipse(r)
                p.setPen(QColor(T.ACCENT_TEXT))
            else:
                p.setPen(QPen(QColor(T.MUTED), sc(2), Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(r)
                p.setPen(QColor(T.MUTED))
            p.drawText(r, Qt.AlignCenter, label)


class Screen(QWidget):
    def __init__(self, ctx: Ctx):
        super().__init__()
        self.ctx = ctx
        sc = ctx.sc
        root = QVBoxLayout(self)
        root.setContentsMargins(sc(10), sc(4), sc(10), sc(8))
        root.setSpacing(sc(4))
        self.header = Header(ctx)
        root.addWidget(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(sc(2))
        root.addLayout(self.body, 1)
        self.legend = LegendBar(ctx)
        root.addWidget(self.legend)

    def refresh(self) -> None:  # pragma: no cover
        pass


def card(sc: T.Scale, color: str) -> Tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setStyleSheet(f"QFrame {{ background: {color}; border-radius: {sc(12)}px; }}")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(sc(10), sc(6), sc(10), sc(6))
    lay.setSpacing(sc(2))
    return f, lay


# ================================================================= customer
class LandingScreen(Screen):
    def __init__(self, ctx: Ctx):
        super().__init__(ctx)
        sc = ctx.sc
        self.body.addStretch(1)
        self.body.addWidget(T.label(sc, "Welcome to", 17, T.MUTED))
        self.body.addWidget(T.label(sc, "Footmop Vendo", 38, T.TEXT, True))
        self.price = T.label(sc, "", 26, T.ACCENT, True)
        self.body.addWidget(self.price)
        self.avail = T.label(sc, "", 14, T.MUTED)
        self.body.addWidget(self.avail)
        self.body.addStretch(1)
        self.body.addWidget(T.label(sc, "Press WHITE to buy  •  or just insert coins", 15, T.TEXT, True))
        self.body.addStretch(1)
        self.legend.set(white="BUY")

    def refresh(self) -> None:
        k = self.ctx.kiosk
        _set(self.header.status, f"Stock {k.stock}")
        _set(self.price, f"{self.ctx.money(k.price)} each")
        _set(self.avail, f"{k.stock} available  •  up to {k.max_qty} per purchase")


class SoldOutScreen(Screen):
    def __init__(self, ctx: Ctx):
        super().__init__(ctx)
        sc = ctx.sc
        self.body.addStretch(1)
        self.body.addWidget(T.label(sc, "SOLD OUT", 42, T.ACCENT, True))
        self.body.addWidget(T.label(sc, "Sorry, no footmops left.\nPlease come back later.", 17, T.TEXT))
        self.body.addWidget(T.label(sc, "Please don't insert coins.", 14, "#FF9C9C", True))
        self.body.addStretch(1)

    def refresh(self) -> None:
        _set(self.header.status, "Stock 0")


class QuantityScreen(Screen):
    def __init__(self, ctx: Ctx):
        super().__init__(ctx)
        sc = ctx.sc
        self.body.addWidget(T.label(sc, "How many footmops?", 19, T.TEXT, True))
        row = QHBoxLayout()
        self.left = T.label(sc, "◀", 40, T.GREEN, True)
        self.qty = T.label(sc, "1", 76, T.TEXT, True)
        self.right = T.label(sc, "▶", 40, T.BLUE, True)
        row.addWidget(self.left, 1)
        row.addWidget(self.qty, 2)
        row.addWidget(self.right, 1)
        self.body.addLayout(row, 1)
        self.total = T.label(sc, "", 21, T.ACCENT, True)
        self.body.addWidget(self.total)
        self.sub = T.label(sc, "", 13, T.MUTED)
        self.body.addWidget(self.sub)

    def refresh(self) -> None:
        k, m = self.ctx.kiosk, self.ctx.money
        coins = -(-k.amount_due // self.ctx.cfg.coin.value)
        _set(self.header.status, f"Stock {k.stock}")
        _set(self.qty, str(k.qty))
        can_less = k.qty > k.min_qty
        can_more = k.qty < k.max_qty
        # keep layout stable: hide arrows by colour, not by removing them
        arrows = (can_less, can_more)
        if getattr(self, "_arrows", None) != arrows:
            self._arrows = arrows
            self.left.setStyleSheet(f"color: {T.GREEN if can_less else 'transparent'}; background: transparent;")
            self.right.setStyleSheet(f"color: {T.BLUE if can_more else 'transparent'}; background: transparent;")
        _set(self.total, f"Total {m(k.amount_due)}  ({coins} coin{'s' if coins != 1 else ''})")
        if k.credit:
            sub = f"Inserted {m(k.credit)}  •  paid for {k.credit // k.price}"
        elif k.max_qty < self.ctx.cfg.machine.max_per_transaction:
            sub = f"Only {k.max_qty} left in stock"
        else:
            sub = f"Max {k.max_qty} per purchase"
        _set(self.sub, sub)
        if k.qty <= 1 and k.credit == 0:
            green = "Cancel"
        else:
            green = "− Less" if can_less else None
        self.legend.set(green=green, white="OK", blue="More +" if can_more else None)


class PaymentScreen(Screen):
    def __init__(self, ctx: Ctx):
        super().__init__(ctx)
        sc = ctx.sc
        self.title = T.label(sc, "", 20, T.TEXT, True)
        self.body.addWidget(self.title)
        self.coins = CoinRow(ctx)
        self.body.addWidget(self.coins)
        self.amount = T.label(sc, "", 34, T.ACCENT, True)
        self.body.addWidget(self.amount)
        self.detail = T.label(sc, "", 13, T.MUTED)
        self.body.addWidget(self.detail)
        self.body.addStretch(1)
        notice, nl = card(sc, "#3A2A00")
        nl.setContentsMargins(sc(8), sc(3), sc(8), sc(3))
        nl.addWidget(T.label(sc, "Exact amount only  •  No change given", 13, T.ACCENT, True))
        self.body.addWidget(notice)
        self.legend.set(green="← Back")

    def refresh(self) -> None:
        k, m = self.ctx.kiosk, self.ctx.money
        cv = self.ctx.cfg.coin.value
        need = k.coins_needed
        _set(self.header.status, f"{k.qty} item{'s' if k.qty > 1 else ''}")
        _set(self.title, f"Insert {need} more {m(cv)} coin{'s' if need != 1 else ''}")
        self.coins.set(k.coins_paid, k.coins_paid + need)
        _set(self.amount, f"{m(k.credit)} / {m(k.amount_due)}")
        _set(self.detail, f"{k.qty} × {m(k.price)}")


class DispensingScreen(Screen):
    def __init__(self, ctx: Ctx):
        super().__init__(ctx)
        sc = ctx.sc
        self.body.addStretch(1)
        self.body.addWidget(T.label(sc, "Dispensing your footmop…", 22, T.TEXT, True))
        self.progress = T.label(sc, "", 34, T.ACCENT, True)
        self.body.addWidget(self.progress)
        self.body.addWidget(T.label(sc, "Please wait - don't reach into the chute", 14, T.MUTED))
        self.body.addStretch(1)

    def refresh(self) -> None:
        k = self.ctx.kiosk
        _set(self.progress, f"{min(k.qty, k.items_done + 1)} of {k.qty}")
        _set(self.header.status, "")


class SuccessScreen(Screen):
    def __init__(self, ctx: Ctx):
        super().__init__(ctx)
        sc = ctx.sc
        self.body.addStretch(1)
        self.body.addWidget(T.label(sc, "Salamat po!", 40, T.ACCENT, True))
        self.msg = T.label(sc, "", 19, T.TEXT, wrap=True)
        self.body.addWidget(self.msg)
        self.over = T.label(sc, "", 13, T.MUTED, wrap=True)
        self.body.addWidget(self.over)
        self.body.addStretch(1)
        self.legend.set(white="Done")

    def refresh(self) -> None:
        k = self.ctx.kiosk
        n = k.qty
        _set(self.msg, f"Please take your {n} footmop{'s' if n > 1 else ''} below.")
        _set(self.over, (f"Overpaid {self.ctx.money(k.overpaid)} - no change given.  " if k.overpaid else "")
             + f"Back to start in {k.success_seconds_left}s")
        _set(self.header.status, "")


class FaultScreen(Screen):
    TITLES = {"dispense_failure": "Dispense Failure",
              "chute_blocked": "Chute Blocked",
              "dispense_timeout": "Dispenser Not Responding",
              "power_interrupted": "Power Interrupted",
              "dispenser_exception": "Dispenser Fault"}

    def __init__(self, ctx: Ctx):
        super().__init__(ctx)
        sc = ctx.sc
        self.setObjectName("fault")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#fault {{ background: {T.DANGER_DARK}; }}")
        box, bl = card(sc, T.DANGER)
        bl.setContentsMargins(sc(12), sc(10), sc(12), sc(10))
        bl.addWidget(T.label(sc, "OUT OF SERVICE", 30, T.TEXT, True))
        self.title = T.label(sc, "", 18, T.TEXT, True, wrap=True)
        bl.addWidget(self.title)
        bl.addWidget(T.label(sc, "Please contact the owner.  Do not insert coins.", 14, T.TEXT))
        self.body.addStretch(1)
        self.body.addWidget(box)
        self.detail = T.label(sc, "", 12, "#FFD5D5", wrap=True)
        self.body.addWidget(self.detail)
        self.body.addStretch(1)
        self.legend.hide()

    def refresh(self) -> None:
        f = self.ctx.kiosk.store.active_fault()
        _set(self.header.status, "LOCKED")
        if not f:
            _set(self.title, "Error")
            return
        _set(self.title, "Error: " + self.TITLES.get(f["code"], f["code"]))
        owed = f"  •  Items owed: {f['owed_items']}" if f["owed_items"] else ""
        _set(self.detail, f"Code {f['code']}  •  {f['ts'].replace('T', ' ')}{owed}")


# ==================================================================== admin
EXIT_HINT = "Hold WHITE 2 s to exit admin"


class AdminPinScreen(Screen):
    """PIN entry with three buttons: GREEN/BLUE change the digit, WHITE moves
    on (and submits after the last digit)."""

    def __init__(self, ctx: Ctx):
        super().__init__(ctx)
        sc = ctx.sc
        self.length = len(str(ctx.cfg.admin.pin))
        self.body.addWidget(T.label(sc, "Admin PIN", 20, T.TEXT, True))
        row = QHBoxLayout()
        row.setSpacing(sc(10))
        row.addStretch(1)
        self.boxes: List[QLabel] = []
        for _ in range(self.length):
            b = QLabel()
            b.setAlignment(Qt.AlignCenter)
            b.setFont(T.font(sc, 34, True))
            b.setFixedSize(sc(56), sc(70))
            row.addWidget(b)
            self.boxes.append(b)
        row.addStretch(1)
        self.body.addLayout(row, 1)
        self.msg = T.label(sc, "", 14, T.ACCENT, True)
        self.body.addWidget(self.msg)
        self.body.addWidget(T.label(sc, EXIT_HINT, 12, T.MUTED))
        self._style_cache: List[Optional[str]] = [None] * self.length
        self.on_show()

    def on_show(self) -> None:
        self.digits = [0] * self.length
        self.pos = 0
        _set(self.msg, "")

    def nav(self, btn: Btn, pressed: bool) -> None:
        k = self.ctx.kiosk
        if pressed and btn in (Btn.GREEN, Btn.BLUE):
            d = -1 if btn == Btn.GREEN else 1
            self.digits[self.pos] = (self.digits[self.pos] + d) % 10
            _set(self.msg, "")
        elif not pressed and btn == Btn.WHITE:
            if self.pos < self.length - 1:
                self.pos += 1
            else:
                ok = k.submit_pin("".join(map(str, self.digits)))
                if ok:
                    return
                self.on_show()
                _set(self.msg, f"Locked - wait {k.pin_locked_seconds}s"
                     if k.pin_locked_seconds else "Wrong PIN - try again")
        self.refresh()

    def refresh(self) -> None:
        sc = self.ctx.sc
        k = self.ctx.kiosk
        if k.pin_locked_seconds:
            _set(self.msg, f"Locked - wait {k.pin_locked_seconds}s")
        for i, b in enumerate(self.boxes):
            active = i == self.pos
            _set(b, str(self.digits[i]) if active else ("•" if i < self.pos else ""))
            style = (f"background: {T.PANEL_HI if active else T.PANEL}; color: {T.TEXT};"
                     f" border-radius: {sc(10)}px; border: {sc(3)}px solid "
                     f"{T.ACCENT if active else 'transparent'};")
            if self._style_cache[i] != style:
                self._style_cache[i] = style
                b.setStyleSheet(style)
        last = self.pos == self.length - 1
        self.legend.set(green="− 1", white="Enter" if last else "Next →", blue="+ 1")
        _set(self.header.status, "ADMIN")


class ListBox(QWidget):
    """Vertical option list; the highlighted row is what WHITE selects."""

    def __init__(self, ctx: Ctx, row_px: int = 30):
        super().__init__()
        self.ctx = ctx
        self.row_px = row_px
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(ctx.sc(3))
        self.rows: List[QLabel] = []
        self._styles: List[Optional[str]] = []
        self.index = 0
        self.count = 0

    def set_items(self, labels: List[str]) -> None:
        sc = self.ctx.sc
        while len(self.rows) < len(labels):
            lb = QLabel()
            lb.setFont(T.font(sc, 15, True))
            lb.setFixedHeight(sc(self.row_px))
            self.lay.addWidget(lb)
            self.rows.append(lb)
            self._styles.append(None)
        for i, lb in enumerate(self.rows):
            lb.setVisible(i < len(labels))
            if i < len(labels):
                _set(lb, labels[i])
        self.count = len(labels)
        self.index = min(self.index, max(0, self.count - 1))
        self.paint()

    def move(self, d: int) -> None:
        if self.count:
            self.index = (self.index + d) % self.count
            self.paint()

    def paint(self) -> None:
        sc = self.ctx.sc
        for i, lb in enumerate(self.rows):
            on = i == self.index
            style = (f"background: {T.ACCENT if on else T.PANEL}; color: {T.ACCENT_TEXT if on else T.TEXT};"
                     f" border-radius: {sc(8)}px; padding-left: {sc(12)}px;")
            if self._styles[i] != style:
                self._styles[i] = style
                lb.setStyleSheet(style)


class AdminScreen(Screen):
    """Admin pages, all operable with the three buttons:
      list pages   GREEN up / BLUE down / WHITE select
      value pages  GREEN - / BLUE + (hold to repeat; stock speeds up) / WHITE save
    """

    TITLES = {"menu": "Admin menu", "stock": "Set stock", "price": "Set price per footmop",
              "faults": "Faults", "hw": "Hardware test", "sales": "Sales report"}

    def __init__(self, ctx: Ctx):
        super().__init__(ctx)
        sc = ctx.sc
        self.title = T.label(sc, "", 15, T.TEXT, True, align=Qt.AlignLeft | Qt.AlignVCenter)
        self.body.addWidget(self.title)
        self.info = T.label(sc, "", 12, T.TEXT, align=Qt.AlignLeft | Qt.AlignTop, wrap=True)
        self.body.addWidget(self.info, 1)
        self.value = T.label(sc, "", 50, T.TEXT, True)
        self.body.addWidget(self.value, 2)
        self.list = ListBox(ctx)
        self.body.addWidget(self.list)
        self.msg = T.label(sc, "", 12, T.ACCENT, True)
        self.msg.setFixedHeight(sc(16))
        self.body.addWidget(self.msg)

        self.page = "menu"
        self.draft = 0
        self._repeat_dir = 0
        self._repeat_n = 0
        self.repeat = QTimer(self)
        self.repeat.timeout.connect(self._repeat_step)
        self.live = QTimer(self)
        self.live.setInterval(300)
        self.live.timeout.connect(self.refresh)

    # ------------------------------------------------------------ pages
    def page_items(self) -> List[Tuple[str, Callable[[], None]]]:
        k = self.ctx.kiosk
        back = ("← Back", lambda: self.go("menu"))
        if self.page == "menu":
            nf = len(k.store.active_faults())
            return [("Stock / Restock", lambda: self.go("stock")),
                    ("Price", lambda: self.go("price")),
                    (f"Faults ({nf})" if nf else "Faults (none)", lambda: self.go("faults")),
                    ("Test hardware", lambda: self.go("hw")),
                    ("Sales report", lambda: self.go("sales")),
                    ("Exit admin", k.exit_admin)]
        if self.page == "faults":
            return ([("Clear all faults", k.admin_clear_faults)] if k.store.active_faults() else []) + [back]
        if self.page == "hw":
            return [("Test dispense 1 item", k.admin_test_dispense), back]
        return [back]

    def go(self, page: str) -> None:
        k = self.ctx.kiosk
        k.admin_message = ""
        self.page = page
        if page == "stock":
            self.draft = k.stock
        elif page == "price":
            self.draft = k.price
        self.list.index = 0
        self.repeat.stop()
        (self.live.start if page == "hw" else self.live.stop)()
        self.refresh()

    def on_show(self) -> None:
        self.go("menu")

    # ------------------------------------------------------------ input
    def nav(self, btn: Btn, pressed: bool) -> None:
        k = self.ctx.kiosk
        if self.page in ("stock", "price"):
            if btn in (Btn.GREEN, Btn.BLUE):
                if pressed:
                    self._repeat_dir = -1 if btn == Btn.GREEN else 1
                    self._repeat_n = 0
                    self._adjust(self._repeat_dir)
                    self.repeat.start(450)          # first repeat after 0.45 s
                else:
                    self.repeat.stop()
            elif btn == Btn.WHITE and not pressed:
                if self.page == "stock":
                    k.admin_set_stock(self.draft)
                else:
                    k.admin_set_price(self.draft)
                msg = k.admin_message
                self.go("menu")
                k.admin_message = msg
                self.refresh()
            return
        if not pressed and btn == Btn.WHITE:
            items = self.page_items()
            if items:
                items[min(self.list.index, len(items) - 1)][1]()
                if k.state.value == "ADMIN":
                    self.refresh()
        elif pressed and btn == Btn.GREEN:
            self.list.move(-1)
        elif pressed and btn == Btn.BLUE:
            self.list.move(1)

    def _repeat_step(self) -> None:
        self._repeat_n += 1
        self.ctx.kiosk.note_activity()
        self.repeat.setInterval(90)
        fast = self._repeat_n > 15 and self.page == "stock"
        self._adjust(self._repeat_dir * (5 if fast else 1))

    def _adjust(self, d: int) -> None:
        if self.page == "stock":
            self.draft = max(0, min(9999, self.draft + d))
        else:
            cv = self.ctx.cfg.coin.value
            self.draft = max(cv, min(1000, self.draft + d * cv))
        self.refresh()

    # ----------------------------------------------------------- render
    def refresh(self) -> None:
        k, m = self.ctx.kiosk, self.ctx.money
        _set(self.header.status, f"ADMIN • Stock {k.stock} • {m(k.price)}")
        _set(self.msg, k.admin_message or EXIT_HINT)
        p = self.page
        value_page = p in ("stock", "price")
        self.value.setVisible(value_page)
        self.list.setVisible(not value_page)
        _set(self.title, self.TITLES[p])

        if value_page:
            cur = k.stock if p == "stock" else k.price
            self.info.setVisible(True)
            _set(self.value, str(self.draft) if p == "stock" else m(self.draft))
            _set(self.info, f"Current: {cur if p == 'stock' else m(cur)}"
                 + ("     (hold − / + to change fast)" if p == "stock" else ""))
            step = "1" if p == "stock" else m(self.ctx.cfg.coin.value)
            self.legend.set(green=f"− {step}", white="Save", blue=f"+ {step}")
            return

        text = ""
        if p == "faults":
            fs = k.store.active_faults()
            text = "No active faults." if not fs else "\n".join(
                f"[{f['ts'][5:16].replace('T', ' ')}] {f['code']}"
                + (f" (owed {f['owed_items']})" if f["owed_items"] else "")
                + f": {f['message'][:90]}" for f in fs[:2])
        elif p == "hw":
            try:
                lv = self.ctx.hal.read_inputs()
            except Exception as e:  # pragma: no cover
                lv = {"error": str(e)}
            sensor = "BLOCKED" if self.ctx.hal.drop_sensor_active() else "clear"
            text = ("Levels: " + "  ".join(f"{n}={v}" for n, v in lv.items())
                    + f"\nDrop sensor: {sensor}\n" + "\n".join(k.admin_live[-3:]))
        elif p == "sales":
            s = k.store.sales_summary()
            t, a = s["today"], s["all_time"]
            text = (f"Today: {t['orders']} orders, {t['items']} items, {m(t['cash'])}\n"
                    f"All time: {a['orders']} orders, {a['items']} items, {m(a['cash'])}\n"
                    f"Abandoned credit: {m(s['abandoned_credit'])}    "
                    f"Unclaimed coins: {m(s['unclaimed_coins'])}\n"
                    f"Items owed to customers: {s['owed_items']}")
        self.info.setVisible(bool(text))
        _set(self.info, text)
        self.list.set_items([label for label, _ in self.page_items()])
        self.legend.set(green="▲ Up", white="Select", blue="▼ Down")
