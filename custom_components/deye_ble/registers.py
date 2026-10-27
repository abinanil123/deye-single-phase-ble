"""P2 — Register map, telemetry decoders, and control encoders.

Maps the Deye logger's Modbus holding registers to the Home Assistant entity
keys used by ha-deyecloud-bridge, so the BLE integration is a drop-in.

The telemetry addresses below are the ones this inverter (Deye 8K hybrid,
single-phase LP1 register layout) actually answers on. They come from the ESP32
roof-controller fastpass poller that read this unit before this integration, and
whose values matched Deye Cloud. The map this file previously carried used the
0x02xx layout of the three-phase / high-voltage family, which decodes zeroes and
garbage here (battery voltage 0.0 V, solar power 59395 W, grid frequency 0 Hz).
A same-second comparison against Deye Cloud remains the acceptance test for any
change to this file.

`daily_consumption` has no dedicated register — the cloud computes it — so it is
NOT decoded here; it is derived in the entity layer (P4) from a midnight
baseline of `total_consumption` (0x0055, lifetime load energy), mirroring the
cloud bridge's daily_grid_import sensor.
"""
from __future__ import annotations

from datetime import datetime


# --- Poll plan --------------------------------------------------------------
# Every telemetry key below is covered by exactly one block, and no two blocks
# overlap (decode() resolves a register by finding the block that contains it).
# 0x02xx is deliberately absent: those addresses are not this unit's layout.

# Fast cycle — the live values the dashboard needs (PV power, battery power and
# SOC, SmartLoad, grid power/voltage, inverter output, grid connected, load).
# Four blocks, 42 registers: well under a second on this link.
FAST_BLOCKS: list[tuple[int, int]] = [
    (0x0096, 12),  # grid voltage L1 (0x0096), load voltage L1 (0x009D)
    (0x00A2, 12),  # load current (0x00A4), SmartLoad (0x00A6), internal CT (0x00A7),
                   # grid (0x00A9), external CT (0x00AA), inverter power L1 (0x00AD)
    (0x00B0, 16),  # load power L1 (0x00B0), total load (0x00B2), battery temp (0x00B6),
                   # battery V (0x00B7), SOC (0x00B8), PV1/PV2 power (0x00BA/0x00BB),
                   # battery power/current (0x00BE/0x00BF)
    (0x00C2, 2),   # grid connected (0x00C2), gen connected (0x00C3)
]

# Slow cycle — energy counters, PV string volts/amps, temperatures, status and
# ratings. Polled every SLOW_TELEMETRY_INTERVAL and carried forward between
# reads so lifetime sensors never blank out.
SLOW_BLOCKS: list[tuple[int, int]] = [
    (0x0035, 1),   # max solar power (W)
    (0x003B, 1),   # running status
    (0x0046, 6),   # 0x0046..0x004B — daily + lifetime battery charge/discharge
    (0x004C, 10),  # 0x004C..0x0055 — daily/total grid energy, grid frequency, load energy
    (0x005A, 2),   # 0x005A..0x005B — DC and AC heatsink temperatures
    (0x0060, 2),   # 0x0060..0x0061 — total PV production (uint32, low word first)
    (0x006C, 5),   # 0x006C..0x0070 — daily PV production, PV1 V/I, PV2 V/I
    (0x00EB, 10),  # 0x00EB..0x00F4 — IO/AUX mode (0x00EB), work mode (0x00F4)
    (0x013C, 1),   # BMS battery SOC (%) — cross-check for the fast 0x00B8 value
]

# A full poll is both cycles: first refresh, and any caller wanting a snapshot.
READ_BLOCKS: list[tuple[int, int]] = FAST_BLOCKS + SLOW_BLOCKS

# Control registers, read on the slower config cycle (P3). Only registers whose
# meaning this installation has seen read back sensibly are polled here.
CONTROL_BLOCKS: list[tuple[int, int]] = [
    (0x003E, 3),   # 0x003E..0x0040 inverter real-time clock
    (0x0068, 1),   # 0x0068 zero-export power (W, signed)
    (0x0073, 3),   # 0x0073/0x0074/0x0075 batt shutdown/restart/low SOC (%)
    (0x008E, 2),   # 0x008F max sell power (0x008E is not the work mode here — that is 0x00F4)
    (0x00E4, 1),   # 0x00E4 System Time panel flags — bit 0 is Time Sync
]


# --- Control register addresses ---------------------------------------------

# Inverter real-time clock, three contiguous registers packed as byte pairs:
#   0x003E  hi = year-2000, lo = month
#   0x003F  hi = day,       lo = hour
#   0x0040  hi = minute,    lo = second
# Writing these registers alone does nothing: the RTC latches them only on the
# Time Sync falling edge below (coordinator.async_sync_clock drives the full
# sequence).
REG_CLOCK = 0x003E
CLOCK_WORD_COUNT = 3

# System Time panel flags. Bit 0 is Time Sync, and the RTC commits the staged
# clock registers when it goes 1 -> 0. Live values are 0x0AEB (on) / 0x0AEA
# (off): the app only ever writes the low byte, and the high byte carries the
# panel's other controls (AM/PM, Auto Dim, Beep, Factory Reset) — so this is
# always a read-modify-write via set_flag, never a literal.
#
# Time Sync OFF also stops the logger's cloud calibration reaching the RTC.
# Since the commit edge *ends* with the bit clear, any writer must put it back
# where it found it, or setting the clock silently disables the only other
# mechanism that corrects it.
REG_TIME_SYNC = 0x00E4
TIME_SYNC_MASK = 0x0001

REG_ZERO_EXPORT_POWER = 0x0068      # zero-export power / grid-comp offset (W, signed) — unverified here
REG_BATT_SHUTDOWN_SOC = 0x0073      # battery shutdown SOC (%) — unverified here
REG_BATT_RESTART_SOC = 0x0074       # battery restart SOC (%) — unverified here
REG_BATT_LOW_SOC = 0x0075           # battery low-warning SOC (%) — unverified here
REG_WORK_MODE = 0x00F4              # work mode, as read by the working ESP32 firmware
REG_IO_MODE = 0x00EB                # SmartLoad / generator / microinverter port mode
REG_MAX_SELL_POWER = 0x008F

# --- Control addresses that are NOT valid on this inverter -------------------
# These were carried over from the three-phase register layout. On this unit the
# same addresses are live telemetry (0x006C daily PV production, 0x006D PV1
# voltage, 0x00A6 gen power, 0x00A7 internal CT, 0x00B2 total load power,
# 0x00BE battery power, 0x00BF battery current), so writing them would clobber
# readings or hit read-only registers. The entities that used them are disabled
# in number.py / switch.py / time.py until the real control addresses have been
# read back from the inverter with the app as the reference.
REG_MAX_CHARGE_CURRENT = 0x006C     # INVALID here: daily PV production
REG_MAX_DISCHARGE_CURRENT = 0x006D  # INVALID here: PV1 voltage
REG_CHARGE_SOC = 0x00A7             # INVALID here: internal CT L1 power
REG_GEN_PEAK_POWER = 0x00BE         # INVALID here: battery power
REG_GRID_PEAK_POWER = 0x00BF        # INVALID here: battery current
REG_TOU_SLOT2_START = 0x0095        # unverified on this unit
REG_TOU_SLOT3_START = 0x0096        # INVALID here: grid voltage L1

# Discharge floor used to be written to the TOU target-SOC slots 0x00A6..0x00AB.
# Those addresses are gen power / internal CT / grid power / external CT on this
# inverter, so the fan-out is empty: nothing may write there. Kept as a name so
# the entity module still imports cleanly.
DISCHARGE_SOC_REGS: list[int] = []

# Peak-shaving controls. 0x00B2 is a packed bitfield on the three-phase family;
# on this unit it is total load power. Kept for import compatibility, not polled.
REG_PEAK_SHAVING_FLAGS = 0x00B2
GEN_PEAK_SHAVE_MASK = 0x0004    # 0x00B2 bit 2 — generator peak-shaving enable
GRID_PEAK_SHAVE_MASK = 0x0010   # 0x00B2 bit 4 — grid peak-shaving enable


def set_flag(raw: int, mask: int, on: bool) -> int:
    """Return *raw* with *mask* bits set when *on*, cleared otherwise.

    Used for read-modify-write on the packed Time Sync flag register so a single
    toggle never clobbers the other panel bits sharing it.
    """
    return (raw | mask) if on else (raw & ~mask)


# --- Work mode enum ---------------------------------------------------------

WORK_MODE_LABELS: dict[int, str] = {
    0: "Sell to Grid",
    1: "Zero Export to Load",
    2: "Zero Export to CT",
}

_WORK_MODE_IDS: dict[str, int] = {v: k for k, v in WORK_MODE_LABELS.items()}

IO_MODE_LABELS: dict[int, str] = {
    0: "Disabled",
    1: "SmartLoad",
    2: "Microinverter",
    3: "Generator",
}


# --- Decode map --------------------------------------------------------------
# Each entry: (absolute_register, scale, signed, offset).
# Decoded value = (signed16(raw) if signed else raw - offset) * scale.
# Temperatures use offset=1000, scale=0.1  ->  (raw - 1000) / 10  °C.

_DECODE_MAP: dict[str, tuple[int, float, bool, int]] = {
    # Live power (W). solar_power is computed below as PV1 + PV2.
    "pv1_power":               (0x00BA, 1,    False, 0),
    "pv2_power":               (0x00BB, 1,    False, 0),
    "grid_power":              (0x00A9, 1,    True,  0),     # negative = exporting
    "battery_power":           (0x00BE, 1,    True,  0),     # negative = charging
    "house_load":              (0x00B2, 1,    True,  0),     # total load power
    "ups_power":               (0x00B0, 1,    True,  0),     # load power L1 (essential)
    "load_power_l1":           (0x00B0, 1,    True,  0),
    "gen_power":               (0x00A6, 1,    True,  0),     # Gen / SmartLoad port
    "external_ct_l1_power":    (0x00AA, 1,    True,  0),
    "internal_ct_l1_power":    (0x00A7, 1,    True,  0),
    "inverter_power_l1":       (0x00AD, 1,    True,  0),

    # Battery
    "battery_soc":             (0x00B8, 1,    False, 0),     # % (fast block)
    "battery_soc_bms":         (0x013C, 1,    False, 0),     # % (BMS mirror, slow)
    "battery_voltage":         (0x00B7, 0.01, False, 0),     # V
    "battery_current":         (0x00BF, 0.01, True,  0),     # A
    "battery_temp":            (0x00B6, 0.1,  False, 1000),  # °C

    # PV strings
    "pv1_voltage":             (0x006D, 0.1,  False, 0),     # V
    "pv1_current":             (0x006E, 0.1,  False, 0),     # A
    "pv2_voltage":             (0x006F, 0.1,  False, 0),     # V
    "pv2_current":             (0x0070, 0.1,  False, 0),     # A

    # AC metrics
    "grid_voltage_l1":         (0x0096, 0.1,  False, 0),     # V
    "grid_frequency":          (0x004F, 0.01, False, 0),     # Hz
    "load_voltage_l1":         (0x009D, 0.1,  False, 0),     # V
    "load_current_l1":         (0x00A4, 0.01, True,  0),     # A

    # Temperatures (heatsinks)
    "dc_temperature":          (0x005A, 0.1,  False, 1000),  # °C
    "inverter_temp":           (0x005B, 0.1,  False, 1000),  # °C (AC heatsink)

    # Status / rating
    "running_status":          (0x003B, 1,    False, 0),     # 0 standby .. 4 fault
    "max_solar_power":         (0x0035, 1,    False, 0),     # W

    # Energy — daily (kWh)
    "daily_solar":             (0x006C, 0.1,  False, 0),
    "daily_grid_import":       (0x004C, 0.1,  False, 0),
    "daily_grid_export":       (0x004D, 0.1,  False, 0),
    "daily_load_energy":       (0x0054, 0.1,  False, 0),

    # Energy — lifetime totals (kWh). total_solar is a 32-bit pair, see decode().
    "total_grid_import":       (0x004E, 0.1,  False, 0),
    "total_grid_export":       (0x0051, 0.1,  False, 0),
    "total_consumption":       (0x0055, 0.1,  False, 0),  # lifetime load energy
    "total_load_energy":       (0x0055, 0.1,  False, 0),

    # Control mirrors (decoded from CONTROL_BLOCKS)
    "zero_export_power":       (0x0068, 1,    True,  0),     # W (grid-comp offset)
    "batt_shutdown_soc":       (0x0073, 1,    False, 0),     # %
    "batt_restart_soc":        (0x0074, 1,    False, 0),     # %
    "batt_low_soc":            (0x0075, 1,    False, 0),     # %
    "max_sell_power":          (0x008F, 1,    False, 0),     # W
    # work_mode (enum) and the 0x00E4 Time Sync bit are handled specially below.
}

# 32-bit lifetime PV production, little-endian word pair.
REG_TOTAL_PRODUCTION = 0x0060

# 32-bit lifetime battery energy counters, little-endian word pairs, 0.1 kWh.
# Verified against Deye Cloud on 2026-10-26: 0x0048/0x0049 = 3308 -> 330.8 kWh
# (cloud total charge), 0x004A/0x004B = 2231 -> 223.1 kWh (cloud total discharge).
REG_TOTAL_BATTERY_CHARGE = 0x0048
REG_TOTAL_BATTERY_DISCHARGE = 0x004A
_BATTERY_TOTALS: tuple[tuple[str, int], ...] = (
    ("total_battery_charge", REG_TOTAL_BATTERY_CHARGE),
    ("total_battery_discharge", REG_TOTAL_BATTERY_DISCHARGE),
)


# --- Decode -----------------------------------------------------------------

def _signed16(raw: int) -> int:
    """Interpret a 16-bit unsigned value as signed (two's complement)."""
    return raw if raw < 0x8000 else raw - 0x10000


def _lookup(words_by_reg: dict[int, list[int]], reg: int) -> int | None:
    """Return the raw word at absolute register *reg*, or None if not polled."""
    for block_start, words in words_by_reg.items():
        offset = reg - block_start
        if 0 <= offset < len(words):
            return words[offset]
    return None


def decode(words_by_reg: dict[int, list[int]]) -> dict[str, float | int | str | datetime]:
    """Decode raw register words into HA entity key/value pairs.

    *words_by_reg* maps each polled block's start address to its list of
    register values (as returned by ``protocol.parse_read``). Keys whose
    registers were not present in *words_by_reg* are omitted, so a partial
    poll yields a partial dict rather than wrong values.
    """
    result: dict[str, float | int | str | datetime] = {}

    for key, (reg, scale, signed, offset) in _DECODE_MAP.items():
        raw = _lookup(words_by_reg, reg)
        if raw is None:
            continue
        value = _signed16(raw) if signed else raw
        value = (value - offset) * scale
        result[key] = int(value) if (scale == 1 and offset == 0) else round(value, 2)

    # Lifetime PV production is one 32-bit counter split over two registers,
    # low word first: (w0 | w1 << 16) * 0.1 kWh.
    low = _lookup(words_by_reg, REG_TOTAL_PRODUCTION)
    high = _lookup(words_by_reg, REG_TOTAL_PRODUCTION + 1)
    if low is not None and high is not None:
        result["total_solar"] = round(((high << 16) | low) * 0.1, 2)

    # Lifetime battery charge / discharge: same uint32 LE pair layout, 0.1 kWh.
    for key, reg in _BATTERY_TOTALS:
        low = _lookup(words_by_reg, reg)
        high = _lookup(words_by_reg, reg + 1)
        if low is not None and high is not None:
            result[key] = round(((high << 16) | low) * 0.1, 2)

    # Solar power is the sum of the two strings. PV2 reads 0 while unwired, so
    # this tracks PV1 exactly today and needs no change when PV2 is connected.
    if "pv1_power" in result or "pv2_power" in result:
        result["solar_power"] = int(
            result.get("pv1_power", 0) + result.get("pv2_power", 0)
        )

    work_mode_raw = _lookup(words_by_reg, REG_WORK_MODE)
    if work_mode_raw is not None:
        result["work_mode"] = WORK_MODE_LABELS.get(work_mode_raw, f"Unknown ({work_mode_raw})")

    io_mode_raw = _lookup(words_by_reg, REG_IO_MODE)
    if io_mode_raw is not None:
        result["io_mode"] = IO_MODE_LABELS.get(io_mode_raw, f"Unknown ({io_mode_raw})")

    # Inverter RTC — three packed registers, decoded together. An implausible
    # frame yields no key at all: undecoded beats quietly wrong for a clock.
    clock_words = [_lookup(words_by_reg, REG_CLOCK + i) for i in range(CLOCK_WORD_COUNT)]
    if all(w is not None for w in clock_words):
        clock = decode_clock(clock_words)
        if clock is not None:
            result["inverter_clock"] = clock

    # Time Sync enable — bit 0 of the packed System Time panel register. Only
    # the decoded bool is published; a writer must re-read the raw word inside
    # its own session, since the other bits are not ours to replay.
    time_sync_raw = _lookup(words_by_reg, REG_TIME_SYNC)
    if time_sync_raw is not None:
        result["time_sync"] = bool(time_sync_raw & TIME_SYNC_MASK)

    # UPS load = total load minus the SmartLoad / generator port contribution.
    if "house_load" in result and "gen_power" in result:
        result["ups_load_power"] = round(result["house_load"] - result["gen_power"], 1)
    elif "ups_power" in result:
        result["ups_load_power"] = result["ups_power"]

    # Derived operating states, using the same 20 W dead-bands as the original
    # ESP32 firmware. Both source values are in the fast blocks, so these track
    # every poll. Sign convention is Deye's: grid_power > 0 is import (BUY) and
    # battery_power < 0 is charge current into the battery.
    if "grid_power" in result:
        grid_power = result["grid_power"]
        result["grid_status"] = (
            "BUY" if grid_power > 20 else "SELL" if grid_power < -20 else "IDLE"
        )
    if "battery_power" in result:
        battery_power = result["battery_power"]
        result["battery_status"] = (
            "Charging"
            if battery_power < -20
            else "Discharging" if battery_power > 20 else "Stand-by"
        )

    return result


# --- Encoders ---------------------------------------------------------------

def decode_clock(words: list[int]) -> datetime | None:
    """Decode the three packed RTC registers to a naive local ``datetime``.

    The inverter stores a bare wall clock with no timezone, so the result is
    deliberately naive — attaching a timezone below the entity layer would
    invent information the device never reported.

    Returns ``None`` when the frame does not describe a real date/time (the
    ``datetime`` constructor rejects month 13, day 32, hour 24, and friends).
    """
    if len(words) < CLOCK_WORD_COUNT:
        return None
    year, month = 2000 + (words[0] >> 8), words[0] & 0xFF
    day, hour = words[1] >> 8, words[1] & 0xFF
    minute, second = words[2] >> 8, words[2] & 0xFF
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def encode_clock(value: datetime) -> list[int]:
    """Encode a local ``datetime`` to the three packed RTC registers.

    Inverse of :func:`decode_clock`. Only the wall-clock fields are used, so an
    aware value encodes as the site time it displays — the inverter has no
    timezone to convert into. The words are staged in the registers; committing
    them is the Time Sync edge's job (see REG_TIME_SYNC).
    """
    if not 2000 <= value.year <= 2255:
        raise ValueError(f"year out of register range: {value.year}")
    return [
        ((value.year - 2000) << 8) | value.month,
        (value.day << 8) | value.hour,
        (value.minute << 8) | value.second,
    ]


def encode_work_mode(label: str) -> int:
    """Encode a work-mode label to its register value (0, 1, or 2)."""
    return _WORK_MODE_IDS[label]


def encode_hhmm(time_str: str) -> int:
    """Encode ``'HH:MM'`` to decimal HHMM for a TOU time register.

    Example: ``'14:00'`` -> ``1400`` (``0x0578``). Rejects malformed or
    out-of-range times.
    """
    parts = time_str.split(":")
    if len(parts) != 2 or not all(len(p) == 2 and p.isdigit() for p in parts):
        raise ValueError(f"expected canonical 'HH:MM', got {time_str!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time out of range: {time_str!r}")
    return hour * 100 + minute


def decode_hhmm(raw: int) -> str:
    """Decode a TOU time register value to ``'HH:MM'``.

    Example: ``0x05DC`` (1500) -> ``'15:00'``. Rejects out-of-range raw values.
    """
    hour, minute = divmod(raw, 100)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid HHMM register value: {raw}")
    return f"{hour:02d}:{minute:02d}"
