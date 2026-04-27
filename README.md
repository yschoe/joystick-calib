# joystick-calib
![Joystick Calibrator GUI](screenshot.png)

Simple Linux joystick calibration/visualization GUI using the `joydev` interface (`/dev/input/js*`).

It auto-detects available joystick devices, reads all axes and buttons, and shows live state:
- Axes are rendered as square stick boxes with realtime position markers.
- Buttons are listed with ON/off indicators.

Run:
```bash
python3 joystick_calibrator.py
```
