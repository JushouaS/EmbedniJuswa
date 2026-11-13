# Footmop ni Kuya J – Vending Kiosk

A full-screen, **buttons-only** kiosk for a Raspberry Pi 5 with a 3.5" SPI
screen. It sells footmops at **₱5 each**: the customer picks a quantity with
the Green/Blue/White buttons (or just drops coins in), pays with ₱5 coins, and
the machine dispenses one footmop at a time. A TCRT5000 sensor confirms each
drop. Touch and mouse input are ignored completely.

## Customer flow

```
LANDING ──WHITE──► QUANTITY ──WHITE──► PAYMENT ──credit ≥ total──► DISPENSING ──► SUCCESS ──► LANDING
   │ coins inserted ──► QUANTITY (qty already = coins paid)                │ jam / sensor / timeout
   ▼                                                                        ▼
SOLD OUT (stock 0)                                               FAULT (locked until admin clears)
```

The bottom of every screen shows three coloured keycaps in the same order as
the physical buttons, labelled with what each button does right now.

| Screen   | GREEN (left)                         | WHITE (centre) | BLUE (right) |
|----------|--------------------------------------|----------------|--------------|
| Landing  | –                                    | Buy            | –            |
| Quantity | Less (at 1 with nothing paid: **Cancel**) | OK        | More         |
| Payment  | Back                                 | –              | –            |
| Success  | –                                    | Done           | –            |

- Quantity can't go below what's already paid for, so nobody overpays by
  pressing GREEN after inserting coins.
- Coins inserted on the Landing or Quantity screen raise the quantity to
  match (3 coins = 3 footmops), then WHITE dispenses straight away.
- The Payment screen shows one coin circle per ₱5 needed, filling in as coins
  arrive.

## Policies

- **Inactivity:** after 60 s with no button press or coin on the Quantity or
  Payment screen, a *"Still there?"* countdown appears for 15 s. Any input
  dismisses it. If it runs out, the order is cancelled. Any credit is
  **forfeited**: it is not carried over to the next customer. It is logged as
  `ABANDONED` so the owner can reconcile.
- **Overpayment:** with ₱5-only coins and a price that is a multiple of ₱5, a
  customer cannot overpay on the Payment screen. Overpayment can only happen
  if credit was inserted before the quantity was chosen. The order then goes
  through, and the screen says *"Overpayment accepted – no change given"*.
  The amount is recorded.
- **Coins inserted while dispensing:** they are credited to a follow-up order
  for the same customer. The normal timeout rule applies to that order.
- **Coins inserted while sold out or faulted:** they are logged as
  *unclaimed*. Wiring a coin-inhibit relay prevents this entirely (see
  `docs/WIRING.md`).

## Reliability features

- **Single-threaded state machine:**
  - GPIO polling, coin decoding and the dispenser each run on their own
    background thread.
  - Those threads only send queued Qt signals.
  - Buttons and coins are therefore handled one at a time on the GUI
    thread. They cannot race, and the UI never blocks on hardware.
- **Buttons:** polled at 200 Hz. A press only counts once the level has been
  stable for 60 ms.
- **Coins**, filtered in four stages:
  1. a kernel glitch filter (3 ms);
  2. pulse width must be 15–150 ms;
  3. a minimum 40 ms gap between pulses, which rejects bounce;
  4. a stuck-line alarm. Optionally, pulses are grouped into bursts for
     multi-pulse acceptors.
- **Dispensing:** items are dispensed one at a time.
  1. A pre-check confirms the chute is clear.
  2. The motor runs for its set time.
  3. The sensor confirms the drop within a time window.
  4. The stock count goes down only for confirmed items.
- **Motor safety:** an independent hard-cutoff timer, plus `finally` blocks,
  a crash hook, and `ExecStopPost` all switch the relay off. A watchdog in
  the state machine faults the machine if the dispenser never reports back.
- **Fault lock:** a jam, a blocked chute, a dispenser timeout, or a power cut
  mid-dispense locks the machine on an *Out of Service* screen. The fault
  records the number of items owed and stays until an admin clears it.
- **Persistence:** SQLite with WAL and `synchronous=FULL`. Every coin, every
  dispensed item and every stock change is its own committed transaction. At
  boot, half-finished orders are closed out and owed items are raised as a
  fault.
- **Watchdog:** a systemd watchdog (`WatchdogSec=30`) restarts a frozen UI.
  `Restart=always` restarts the app after a crash.

## Admin

Admin mode can be opened from the Landing, Sold out or Fault screen:

- **Open admin:** hold **GREEN + BLUE for 3 s**, then enter the PIN:
  GREEN/BLUE change the highlighted digit, WHITE moves to the next digit and
  submits after the last one.
- **Menus:** GREEN = up, BLUE = down, WHITE = select.
- **Stock and price:** GREEN = −, BLUE = +, WHITE = save. Hold + or − to
  repeat; stock speeds up after about 2 s.
- **Exit:** hold **WHITE for 2 s** on any admin page (or pick "Exit admin").
  Admin also closes itself after 2 minutes idle.
- **Lockout:** 5 wrong PINs lock the keypad for 60 s.

Admin pages:

- **Stock / Restock:** set the stock count.
- **Price:** in ₱5 steps.
- **Faults:** read and clear faults.
- **Test hardware:** live input levels and events, plus a one-item test
  dispense.
- **Sales report:** today and all-time sales, abandoned credit, unclaimed
  coins, items owed.
- **Exit.**

Change the PIN in `/etc/footmop/config.toml`.

## Try it on a PC (no Pi needed)

```bash
pip install PyQt5
python3 -m footmop --mock --windowed --seed-stock 10            # 480x320
python3 -m footmop --mock --windowed --size 800x480 --seed-stock 10
```

| Key                       | Simulates                                  |
|---------------------------|--------------------------------------------|
| ← / A                     | GREEN button                               |
| → / D                     | BLUE button                                |
| Enter / Space / S         | WHITE button                               |
| C or 5                    | insert ₱5 coin (real pulse through the decoder) |
| N                         | coin-line noise (should be rejected)       |
| J                         | toggle motor jam                           |
| B                         | toggle chute blocked                       |
| hold ← + → for 3 s        | admin (PIN 1234); hold Enter 2 s to leave  |
| Esc                       | quit                                       |

To run the unit tests: `python3 -m pytest -q`

## Install on the Pi

1. Use Raspberry Pi OS Bookworm (64-bit). Lite is recommended for a kiosk.
2. Set up the 3.5" screen driver. See `docs/DISPLAY_SETUP.md`.
3. Wire the hardware. See `docs/WIRING.md`.
4. Install and configure:

   ```bash
   unzip footmop_vendo.zip && cd footmop_vendo
   sudo ./deploy/install.sh                 # or: FOOTMOP_DISPLAY_MODE=desktop sudo -E ./deploy/install.sh
   sudo nano /etc/footmop/config.toml       # set admin PIN, check pins
   sudo nano /boot/firmware/config.txt      # add: gpio=20=op,dl
   sudo reboot
   ```

5. Calibrate the coin acceptor:

   ```bash
   sudo systemctl stop footmop
   python3 /opt/footmop/tools/coin_probe.py --gpio 19    # insert coins, read widths
   ```

   Set `pulse_min_ms` and `pulse_max_ms` in the config to bracket the widths
   you see, then `sudo systemctl start footmop`.

6. On first boot the stock is 0, so the screen shows SOLD OUT. Open admin and
   set the stock.

Useful commands:

```bash
journalctl -u footmop -f                      # live log
tail -f /var/log/footmop/footmop.log
sqlite3 /var/lib/footmop/footmop.db "select * from sessions order by id desc limit 10;"
```

## Project layout

```
footmop/
  config.py            config dataclasses + validation (bad price, pin clashes with the screen…)
  core/debounce.py     button debouncer (pure)
  core/coin.py         coin pulse decoder + worker thread
  core/store.py        SQLite persistence + boot recovery
  core/state.py        kiosk state machine (pure, unit-tested)
  core/dispenser.py    per-item motor/sensor sequence with hard cutoff
  hal/lgpio_hal.py     real GPIO (Pi 5 aware)
  hal/mock_hal.py      keyboard-driven simulator
  ui/                  PyQt5 screens, scaling, admin, signal bridge
deploy/                installer, systemd unit, launcher, relay-off hook
docs/                  wiring + display setup
tools/coin_probe.py    measure real coin pulse widths
tests/                 39 unit tests (state machine, decoder, debounce, store, dispenser)
```

## Not yet verified on real hardware

All logic has been tested with unit tests and a scripted end-to-end run on
the simulator. These things depend on your physical parts and still need
checking on the real machine:

- coin pulse widths, using `coin_probe.py`;
- the TCRT5000 position and threshold;
- whether your relay module is active-high or active-low;
- the vendor's display driver.
