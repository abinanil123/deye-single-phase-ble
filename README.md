# Deye Single-Phase Inverter Bluetooth (Local BLE + Cloud Coexistence)

Custom Home Assistant integration for **Deye single-phase hybrid inverters** (such as SUN-5K-SG03LP1, SUN-8K-SG01LP1, etc.) communicating directly over **Bluetooth Low Energy (BLE)** via Home Assistant Bluetooth or an ESP32 Bluetooth Proxy.

This project enhances earlier community implementations with a **Cloud Coexistence Engine** and **Single-Phase Register Mapping**, solving the common logger contention problem where local BLE polling completely starves the official DeyeCloud / Solarman cloud feed.

---

## Key Features

1. **Fast 5-Second Local Polling:**
   * Ultra-responsive live power telemetry (Grid, PV/Solar, Battery, Inverter Load, Temperatures, Daily Energy).
2. **Cloud Coexistence Engine:**
   * Solves Deye Wi-Fi logger lockups. The inverter's logger shares a single microcontroller between its Wi-Fi upload module and its local BLE radio.
   * Introduces scheduled quiet windows (`cloud_window_duration` and `cloud_sync_frequency`) so your official Deye Cloud / Solarman mobile app continues to update reliably in parallel.
3. **Verified Minimal Duration:**
   * Empirically tested and verified: a 15-second quiet window every 5 minutes allows 100% reliable DeyeCloud uploads while maintaining 95%+ live 5-second local BLE coverage.
4. **Fully Local Mode:**
   * Optional toggle switch: turn OFF cloud coexistence to achieve 100% uninterrupted local 5-second polling if you do not use Deye cloud services.
5. **BLE Communication Switch:**
   * Master switch that immediately disconnects the persistent BLE connection and pauses polling for maintenance or temporary cloud-only operation.
6. **Optimized for Single-Phase Models:**
   * Tailored Modbus register addresses specifically for Deye single-phase hybrid inverters (preventing invalid multi-phase register errors).

---

## Controls & Entities

| Entity / Control | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `switch.*_ble_communication` | Switch | Master toggle. Turning OFF drops the BLE link immediately and halts polling. | `ON` |
| `switch.*_fully_local_mode_no_cloud` | Switch | If ON, disables the cloud quiet window for 100% uninterrupted 5s local polling. | `OFF` |
| `number.*_cloud_sync_frequency` | Slider (1–60 min) | How often to open a quiet window for DeyeCloud Wi-Fi upload. | `5 min` |
| `number.*_cloud_window_duration` | Slider (10–60 s) | Duration of the quiet window (BLE disconnected). | `15 s` |

---

## Installation via HACS

1. Open **HACS** in Home Assistant.
2. Click the three dots in the top-right corner and select **Custom repositories**.
3. Add the URL: `https://github.com/abinanil123/deye-single-phase-ble`
4. Category: **Integration**.
5. Click **Add**, find **Deye Single-Phase Inverter Bluetooth**, and click **Download**.
6. Restart Home Assistant.
7. Go to **Settings → Devices & Services → Add Integration**, search for **Deye Bluetooth (Local)** and follow the prompt.

---

## ESP32 Bluetooth Proxy Configuration (ESPHome)

If your inverter is out of range of your Home Assistant server, you can use an ESP32 as an active BLE proxy. Here is a recommended ESPHome snippet with diagnostic sensors:

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

## Credits & Acknowledgments
* Based on earlier work by [PetePeter](https://github.com/PetePeter/deye-bluetooth) and the Sunsynk/Deye community.
* Single-phase register tuning and Cloud Coexistence engine developed and verified on Deye 8K hybrid systems.
