# Deye Single-Phase Inverter Bluetooth (Local BLE + Cloud Coexistence)

Custom Home Assistant integration for **Deye single-phase hybrid inverters** (such as SUN-3K/5K/6K/7.6K/8K-SG01LP1, SUN-5K-SG03LP1, and related single-phase models) communicating directly over **Bluetooth Low Energy (BLE)** via Home Assistant's native Bluetooth or an ESP32 Bluetooth Proxy.

This project is a dedicated single-phase evolution of [PetePeter/deye-bluetooth](https://github.com/PetePeter/deye-bluetooth), introducing a **Cloud Coexistence Engine**, **AUX / SmartLoad / Generator Port Support**, **Automatic UPS vs. Non-Essential Load separation**, and **Single-Phase Register Mapping**.

---

## 🌟 Unique Features & Enhancements

### 1. Cloud Coexistence Engine (No More Cloud Starvation)
* **The Problem:** The Deye inverter's Wi-Fi logger uses a single microcontroller shared between its local BLE transceiver and its Wi-Fi upload module. Standard integrations keep a permanent BLE connection open, which completely starves the Wi-Fi radio and causes the official DeyeCloud / Solarman mobile app to go permanently offline.
* **The Solution:** Our scheduled quiet window engine (`cloud_window_duration` and `cloud_sync_frequency`) periodically pauses BLE traffic cleanly, drops the link, and gives the logger dedicated Wi-Fi time to push telemetry to Deye Cloud.
* **Lab-Tested Timing:** Verified that a **15-second quiet window every 5 minutes** allows 100% reliable Deye Cloud uploads while preserving >95% live 5-second local BLE telemetry.
* **Fully Local Mode Switch:** Don't care about the cloud? Toggle `switch.*_fully_local_mode_no_cloud` to ON, and the integration runs 100% continuous, zero-gap 5.0s local polling.

### 2. Multi-Function AUX / GEN Port Support (SmartLoad & Generator)
Deye hybrid inverters feature a flexible AUX / GEN port that can be configured in the inverter settings. This integration reads and handles the exact operating mode (`0x00EB`):
* **SmartLoad Mode:** When powering non-essential dump loads (water heaters, EV chargers, pool pumps) only during solar surplus, the power is monitored live via register `0x00A6`.
* **Generator Mode:** If a fuel/gas generator is wired to the AUX/GEN port, this port reports live incoming **Generator Power**. You can track generator runtime, incoming watts, and grid/gen connection status (`0x00C2` / `0x00C3`).
* **Micro-Inverter Mode:** Tracks power from AC-coupled microinverters fed into the AUX port.

### 3. Smart Load Separation (UPS Critical Load vs Total House Load)
* Most integrations only report one generic "load power".
* This integration reads both total house load and AUX/Gen port power, automatically calculating **True UPS Load Power** (`house_load - gen_power`).
* Instantly see how much power your critical/backup circuits are using versus your heavy non-essential appliances.

### 4. Single-Phase Modbus Register Mapping
* Upstream PetePeter/deye-bluetooth targets 3-phase commercial/residential inverters (reading L1, L2, L3 phase registers). Polling these on single-phase units causes invalid values, zeroes, or Modbus read timeouts.
* This repository is cleanly mapped for **single-phase Deye hybrid inverters**, tracking PV1, PV2, Battery voltage/current/power/SOC, Grid import/export, and Inverter AC output accurately.

### 5. Proper BLE Communication Toggle
* The master `switch.*_ble_communication` switch drops the persistent BLE session immediately upon toggling OFF and cleanly re-establishes it when toggled ON.

---

## Controls & Entities

| Entity / Control | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `switch.*_ble_communication` | Switch | Master toggle. Turning OFF drops the BLE link immediately and halts polling. | `ON` |
| `switch.*_fully_local_mode_no_cloud` | Switch | If ON, disables the cloud quiet window for 100% uninterrupted 5s local polling. | `OFF` |
| `number.*_cloud_sync_frequency` | Slider (1–60 min) | How often to open a quiet window for DeyeCloud Wi-Fi upload. | `5 min` |
| `number.*_cloud_window_duration` | Slider (10–60 s) | Duration of the quiet window (BLE disconnected). | `15 s` |
| `sensor.*_gen_power` | Sensor (W) | Power on the AUX/GEN port (SmartLoad or Generator). | Dynamic |
| `sensor.*_ups_load_power` | Sensor (W) | Dedicated critical/backup load power. | Dynamic |
| `sensor.*_grid_status` | Sensor | Derived operating state (`BUY`, `SELL`, `IDLE`). | Dynamic |
| `sensor.*_battery_status` | Sensor | Derived battery state (`Charging`, `Discharging`, `Stand-by`). | Dynamic |

---

## Installation via HACS

1. Open **HACS** in Home Assistant.
2. Click the three dots in the top-right corner and select **Custom repositories**.
3. Add repository URL:
   ```
   https://github.com/abinanil123/deye-single-phase-ble
   ```
4. Category: **Integration**.
5. Click **Add**, find **Deye Single-Phase Inverter Bluetooth**, and click **Download**.
6. Restart Home Assistant.
7. Go to **Settings → Devices & Services → Add Integration**, search for **Deye Bluetooth (Local)** and configure your inverter.

---

## ESP32 Bluetooth Proxy Configuration (ESPHome)

If your inverter is out of range of your Home Assistant server, use an ESP32 as an active BLE proxy:

```yaml
esp32_ble_tracker:
  scan_parameters:
    interval: 1100ms
    window: 1100ms
    active: true

bluetooth_proxy:
  active: true

debug:
  update_interval: 60s

sensor:
  - platform: uptime
    name: "BLE Proxy Uptime"
    update_interval: 60s
  - platform: wifi_signal
    name: "BLE Proxy WiFi Signal"
    update_interval: 60s
  - platform: debug
    free:
      name: "BLE Proxy Free Heap"
```

---

## Relationship to PetePeter & Upstream
* This integration is based on and extends the Bluetooth protocol work pioneered by [PetePeter/deye-bluetooth](https://github.com/PetePeter/deye-bluetooth) and the Sunsynk/Deye open-source community.
* While PetePeter's repository targets 3-phase systems with continuous BLE locking, this fork is tailored specifically for **single-phase hybrid inverters** requiring **cloud coexistence** and **AUX / SmartLoad / Generator** monitoring.
