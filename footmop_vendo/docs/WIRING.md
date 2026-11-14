# Wiring – Footmop ni Kuya J (Raspberry Pi 5 + 3.5" GPIO screen)

> Safety first: the Pi's GPIO pins are **3.3 V only** and have no protection.
> Never connect 5 V or 12 V signals directly to a GPIO pin.

## Which pins are free

The 3.5" XPT2046 screen plugs onto **physical pins 1–26**. It uses SPI0
(GPIO 7, 8, 9, 10, 11) plus GPIO 17, 24 and 25 for touch and display control.
All peripherals therefore go on **physical pins 27–40**. The app refuses to
start if you configure a pin the screen uses.

| Function             | BCM GPIO | Physical pin | Other side                         |
|----------------------|----------|--------------|------------------------------------|
| Green button (left)  | GPIO 5   | 29           | GND (pin 30)                       |
| Blue button (right)  | GPIO 6   | 31           | GND (pin 34)                       |
| White button (OK)    | GPIO 13  | 33           | GND (pin 34)                       |
| Coin signal          | GPIO 19  | 35           | optocoupler output (see below)     |
| TCRT5000 drop sensor | GPIO 26  | 37           | sensor module **DO** pin           |
| Motor relay IN       | GPIO 20  | 38           | relay/MOSFET module input          |
| GND                  | –        | 30, 34, 39   |                                    |
| Coin inhibit (recommended) | GPIO 21 | 40      | relay that powers the coin slot    |

**Power for the sensor and modules.** The 3.3 V and 5 V pins (1, 2, 4, 17) are
under the screen. To reach them, use one of:

- a 40-pin GPIO splitter or extension board,
- the pass-through header on the screen, if it has one,
- wires soldered to the underside of those pins on the Pi.

## Buttons

Wire each button between its GPIO and GND. The app turns on the internal
pull-up resistor, so a press reads LOW. Debouncing is done in software
(60 ms stable time).

## Coin acceptor (single-coin ₱5, 12 V)

Most coin slots used in Philippine piso machines run on 12 V and have an
open-collector **COIN** output. Isolate it with a **PC817 optocoupler**:

```
 +12V ──[1 kΩ]──► PC817 pin 1 (anode)
 COIN wire ─────► PC817 pin 2 (cathode)          (COIN sinks to GND during a pulse)
 PC817 pin 4 (collector) ─────► GPIO 19 (pin 35)  (internal pull-up to 3.3 V)
 PC817 pin 3 (emitter)   ─────► Pi GND (pin 39)
 Coin acceptor GND ─────► 12 V supply GND (NOT connected to the Pi)
```

- Set the acceptor's **NO/NC** switch to **NO**, so the line rests HIGH and
  pulses LOW. That matches `coin.active_low = true`.
- If the acceptor has a pulse-speed switch (fast/medium/slow), pick one. Then
  run `tools/coin_probe.py`, read the pulse width it prints, and set
  `pulse_min_ms` and `pulse_max_ms` around it. Example: if the probe shows
  about 50 ms, set min = 20 and max = 120.
- If your acceptor sends more than one pulse per coin, set `pulses_per_coin`.
- Before wiring, measure the COIN wire with a multimeter. If it outputs a
  voltage of its own instead of pulling to GND, the opto LED goes between COIN
  and GND instead.

## TCRT5000 drop sensor

- Power the module from **3.3 V**, not 5 V. Its DO pin is pulled up to the
  module's supply, so a 5 V module would push 5 V into the Pi.
- Mount it in the chute where every footmop passes within about **2–15 mm** of
  the sensor face. The TCRT5000 is a short-range reflective sensor.
- Turn the module's potentiometer until its DO LED switches cleanly when a
  footmop passes and stays off when the chute is empty.
- Most modules pull DO **LOW** when they detect something
  (`sensor_active_low = true`). Check this on the admin **Test hardware**
  page: `sensor=` should change when you hold a footmop in front of it.
- If dark or fluffy footmops are missed, move the sensor closer, block outside
  light from it, or switch to a slotted IR break-beam sensor. The app works
  with either; only the active level may change.

The app checks the sensor **before** each item. If the sensor already reads
"blocked", it refuses to run the motor and shows *Chute Blocked*.

## Motor relay (boot safety)

GPIO 20 normally has a pull-**down** at power-on, so it reads LOW before the
app starts. Confirm this on your Pi with `pinctrl get 20` before the app runs:
it should show `pd` / `lo`.

- **Use an active-HIGH relay or MOSFET module.** IN high = motor on. The
  motor then stays off during boot, a crash and shutdown without any extra
  setup. Keep `relay_active_high = true` and add `gpio=20=op,dl` to
  `/boot/firmware/config.txt`.
- With a common **active-LOW** relay module, the motor would run during every
  boot. If you must use one:
  1. set `relay_active_high = false`;
  2. add `gpio=20=op,dh` to `/boot/firmware/config.txt`;
  3. accept that there is a short window during early boot where the pin is
     not yet driven.
- Power the motor from its own supply, never from the Pi. Put a flyback diode
  (1N4007) across a DC motor.

## Coin inhibit (strongly recommended)

The kiosk only accepts coins on the **Payment screen**. To enforce that
physically, put a relay on the coin acceptor's 12 V supply line, driven by
GPIO 21, and set `pins.coin_enable = 21`. The coin slot is then powered only
while the Payment screen is showing. On every other screen, coins fall
straight through to the return cup instead of being swallowed.

Without the relay, coins inserted at those times are kept by the machine and
**logged** (Admin → Sales report → Unclaimed coins).
