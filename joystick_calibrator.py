#!/usr/bin/env python3
"""Linux joystick visualizer/calibration helper.

Uses the legacy joydev interface (/dev/input/js*):
https://www.kernel.org/doc/html/latest/input/joydev/joystick-api.html
"""

from __future__ import annotations

import argparse
import array
import errno
import fcntl
import os
import struct
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import Optional


# joydev event constants from linux/joystick.h
JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80

# ioctl constants from linux/joystick.h
JSIOCGAXES = 0x80016A11
JSIOCGBUTTONS = 0x80016A12


def jsiocgname(length: int) -> int:
    # _IOC(_IOC_READ, 'j', 0x13, len)
    return 0x80006A13 + (length << 16)


JSIOCGAXMAP = 0x80406A32
JSIOCGBTNMAP = 0x80406A34

EVENT_STRUCT = struct.Struct("IhBB")
AXIS_MIN = -32767
AXIS_MAX = 32767


AXIS_NAMES = {
    0x00: "X",
    0x01: "Y",
    0x02: "Z",
    0x03: "Rx",
    0x04: "Ry",
    0x05: "Rz",
    0x06: "Throttle",
    0x07: "Rudder",
    0x08: "Wheel",
    0x09: "Gas",
    0x0A: "Brake",
    0x10: "Hat0X",
    0x11: "Hat0Y",
    0x12: "Hat1X",
    0x13: "Hat1Y",
    0x14: "Hat2X",
    0x15: "Hat2Y",
    0x16: "Hat3X",
    0x17: "Hat3Y",
}

BUTTON_NAMES = {
    0x120: "Trigger",
    0x121: "Thumb",
    0x122: "Thumb2",
    0x123: "Top",
    0x124: "Top2",
    0x125: "Pinkie",
    0x126: "Base",
    0x127: "Base2",
    0x128: "Base3",
    0x129: "Base4",
    0x12A: "Base5",
    0x12B: "Base6",
    0x130: "A",
    0x131: "B",
    0x132: "C",
    0x133: "X",
    0x134: "Y",
    0x135: "Z",
    0x136: "TL",
    0x137: "TR",
    0x138: "TL2",
    0x139: "TR2",
    0x13A: "Select",
    0x13B: "Start",
    0x13C: "Mode",
    0x13D: "ThumbL",
    0x13E: "ThumbR",
    0x220: "DpadUp",
    0x221: "DpadDown",
    0x222: "DpadLeft",
    0x223: "DpadRight",
}


@dataclass
class StickWidget:
    frame: ttk.Frame
    label_var: tk.StringVar
    canvas: tk.Canvas
    marker: int
    value_var: tk.StringVar
    axis_x_index: int
    axis_y_index: int


class JoystickApp:
    def __init__(self, root: tk.Tk, device_path: Optional[str]) -> None:
        self.root = root
        self.root.title("Linux Joystick Calibrator")
        self.root.geometry("980x700")

        self.fd: Optional[int] = None
        self.device_path: Optional[str] = None
        self.device_name = ""
        self.axis_count = 0
        self.button_count = 0

        self.axis_states: list[int] = []
        self.button_states: list[int] = []
        self.axis_labels: list[str] = []
        self.button_labels: list[str] = []

        self.stick_widgets: list[StickWidget] = []
        self.button_indicators: list[tuple[tk.Label, tk.StringVar]] = []

        self._build_ui(device_path)

    def _build_ui(self, initial_device: Optional[str]) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Device:").pack(side=tk.LEFT)

        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(top, textvariable=self.device_var, state="readonly", width=35)
        self.device_combo.pack(side=tk.LEFT, padx=(8, 8))

        ttk.Button(top, text="Refresh", command=self.refresh_devices).pack(side=tk.LEFT)
        ttk.Button(top, text="Connect", command=self.connect_selected_device).pack(side=tk.LEFT, padx=(8, 0))

        self.status_var = tk.StringVar(value="No device connected")
        status = ttk.Label(self.root, textvariable=self.status_var, padding=(10, 4))
        status.pack(fill=tk.X)

        self.content = ttk.Frame(self.root, padding=10)
        self.content.pack(fill=tk.BOTH, expand=True)

        # Axis pane
        axis_frame = ttk.LabelFrame(self.content, text="Axes", padding=10)
        axis_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        self.axes_grid = ttk.Frame(axis_frame)
        self.axes_grid.pack(fill=tk.BOTH, expand=True)

        # Button pane
        button_frame = ttk.LabelFrame(self.content, text="Buttons", padding=10)
        button_frame.pack(fill=tk.BOTH, expand=True, side=tk.BOTTOM, pady=(10, 0))

        self.buttons_grid = ttk.Frame(button_frame)
        self.buttons_grid.pack(fill=tk.BOTH, expand=True)

        self.refresh_devices()
        if initial_device and initial_device in self.device_combo["values"]:
            self.device_var.set(initial_device)
        elif self.device_combo["values"]:
            self.device_var.set(self.device_combo["values"][0])

        if self.device_var.get():
            self.connect_selected_device()

        self.root.after(10, self.poll_events)

    def refresh_devices(self) -> None:
        devices = sorted(str(p) for p in Path("/dev/input").glob("js*"))
        self.device_combo["values"] = devices
        if devices and self.device_var.get() not in devices:
            self.device_var.set(devices[0])
        if not devices:
            self.device_var.set("")
            self.status_var.set("No /dev/input/js* devices found")

    def connect_selected_device(self) -> None:
        selected = self.device_var.get().strip()
        if not selected:
            self.status_var.set("Select a device first")
            return

        self.disconnect()

        try:
            fd = os.open(selected, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            self.status_var.set(f"Open failed: {selected}: {exc}")
            return

        self.fd = fd
        self.device_path = selected
        self.device_name, self.axis_count, self.button_count = self._read_device_info(fd)

        self.axis_states = [0] * self.axis_count
        self.button_states = [0] * self.button_count
        self.axis_labels = self._read_axis_labels(fd, self.axis_count)
        self.button_labels = self._read_button_labels(fd, self.button_count)

        self._rebuild_dynamic_ui()
        self.status_var.set(
            f"Connected: {self.device_name} ({selected}) | axes={self.axis_count}, buttons={self.button_count}"
        )

    def disconnect(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _read_device_info(self, fd: int) -> tuple[str, int, int]:
        name_buf = array.array("B", [0] * 128)
        try:
            fcntl.ioctl(fd, jsiocgname(len(name_buf)), name_buf)
            name = bytes(name_buf).split(b"\x00", 1)[0].decode("utf-8", "replace")
        except OSError:
            name = "Unknown"

        axes_buf = array.array("B", [0])
        buttons_buf = array.array("B", [0])
        fcntl.ioctl(fd, JSIOCGAXES, axes_buf)
        fcntl.ioctl(fd, JSIOCGBUTTONS, buttons_buf)
        return name, axes_buf[0], buttons_buf[0]

    def _read_axis_labels(self, fd: int, count: int) -> list[str]:
        axmap = array.array("B", [0] * 0x40)
        try:
            fcntl.ioctl(fd, JSIOCGAXMAP, axmap)
        except OSError:
            return [f"Axis {i}" for i in range(count)]

        labels: list[str] = []
        for i in range(count):
            code = axmap[i]
            labels.append(AXIS_NAMES.get(code, f"Axis{i}"))
        return labels

    def _read_button_labels(self, fd: int, count: int) -> list[str]:
        btnmap = array.array("H", [0] * 200)
        try:
            fcntl.ioctl(fd, JSIOCGBTNMAP, btnmap)
        except OSError:
            return [f"Button {i}" for i in range(count)]

        labels: list[str] = []
        for i in range(count):
            code = btnmap[i]
            labels.append(BUTTON_NAMES.get(code, f"Btn{i}"))
        return labels

    def _rebuild_dynamic_ui(self) -> None:
        for w in self.axes_grid.winfo_children():
            w.destroy()
        for w in self.buttons_grid.winfo_children():
            w.destroy()
        self.stick_widgets.clear()
        self.button_indicators.clear()

        # Create square stick displays for axis pairs (0,1), (2,3), ...
        pair_count = (self.axis_count + 1) // 2
        for pair in range(pair_count):
            axis_x = pair * 2
            axis_y = pair * 2 + 1

            frame = ttk.Frame(self.axes_grid, padding=6)
            frame.grid(row=pair // 3, column=pair % 3, sticky="nsew", padx=6, pady=6)

            x_label = self.axis_labels[axis_x] if axis_x < len(self.axis_labels) else f"Axis {axis_x}"
            y_label = self.axis_labels[axis_y] if axis_y < len(self.axis_labels) else f"Axis {axis_y}"
            title_var = tk.StringVar(value=f"Stick {pair + 1}: {x_label}/{y_label}")
            ttk.Label(frame, textvariable=title_var).pack(anchor="w")

            canvas = tk.Canvas(frame, width=200, height=200, bg="#111111", highlightthickness=1, highlightbackground="#666")
            canvas.pack()
            canvas.create_rectangle(20, 20, 180, 180, outline="#888")
            canvas.create_line(100, 20, 100, 180, fill="#444")
            canvas.create_line(20, 100, 180, 100, fill="#444")
            marker = canvas.create_oval(94, 94, 106, 106, fill="#4caf50", outline="")

            value_var = tk.StringVar(value="x=0 y=0")
            ttk.Label(frame, textvariable=value_var).pack(anchor="w")

            stick = StickWidget(
                frame=frame,
                label_var=title_var,
                canvas=canvas,
                marker=marker,
                value_var=value_var,
                axis_x_index=axis_x,
                axis_y_index=axis_y,
            )
            self.stick_widgets.append(stick)

        for i in range(3):
            self.axes_grid.columnconfigure(i, weight=1)

        # Create button indicators
        columns = 6
        for i in range(self.button_count):
            label = self.button_labels[i] if i < len(self.button_labels) else f"Button {i}"
            text_var = tk.StringVar(value=f"{i}: {label} [off]")
            widget = tk.Label(
                self.buttons_grid,
                textvariable=text_var,
                relief=tk.RIDGE,
                padx=8,
                pady=4,
                width=22,
                bg="#2d2d2d",
                fg="#ffffff",
            )
            widget.grid(row=i // columns, column=i % columns, sticky="ew", padx=4, pady=4)
            self.button_indicators.append((widget, text_var))

        for col in range(columns):
            self.buttons_grid.columnconfigure(col, weight=1)

        self._refresh_visuals()

    def _refresh_visuals(self) -> None:
        for stick in self.stick_widgets:
            x_raw = self.axis_states[stick.axis_x_index] if stick.axis_x_index < len(self.axis_states) else 0
            y_raw = self.axis_states[stick.axis_y_index] if stick.axis_y_index < len(self.axis_states) else 0
            x_norm = self._normalize_axis(x_raw)
            y_norm = self._normalize_axis(y_raw)

            # Stick box is 20..180 on each axis. Invert Y so up is positive.
            cx = 100 + int(80 * x_norm)
            cy = 100 - int(80 * y_norm)
            stick.canvas.coords(stick.marker, cx - 6, cy - 6, cx + 6, cy + 6)
            stick.value_var.set(f"x={x_raw:+6d} y={y_raw:+6d}")

        for i, (widget, text_var) in enumerate(self.button_indicators):
            pressed = bool(self.button_states[i]) if i < len(self.button_states) else False
            label = self.button_labels[i] if i < len(self.button_labels) else f"Button {i}"
            state_txt = "ON" if pressed else "off"
            text_var.set(f"{i}: {label} [{state_txt}]")
            widget.configure(background="#3a7d44" if pressed else "#2d2d2d", foreground="#ffffff")

    @staticmethod
    def _normalize_axis(raw_value: int) -> float:
        if raw_value >= 0:
            return min(1.0, raw_value / AXIS_MAX)
        return max(-1.0, raw_value / -AXIS_MIN)

    def poll_events(self) -> None:
        if self.fd is not None:
            while True:
                try:
                    data = os.read(self.fd, EVENT_STRUCT.size)
                except BlockingIOError:
                    break
                except OSError as exc:
                    if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        break
                    self.status_var.set(f"Read error on {self.device_path}: {exc}")
                    self.disconnect()
                    break

                if len(data) != EVENT_STRUCT.size:
                    break

                _time_ms, value, event_type, number = EVENT_STRUCT.unpack(data)
                event_type &= ~JS_EVENT_INIT

                if event_type == JS_EVENT_AXIS and number < len(self.axis_states):
                    self.axis_states[number] = value
                elif event_type == JS_EVENT_BUTTON and number < len(self.button_states):
                    self.button_states[number] = value

            self._refresh_visuals()

        self.root.after(10, self.poll_events)



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Linux joystick visualizer/calibration GUI")
    parser.add_argument(
        "--device",
        default=None,
        help="Joystick device path (default: first /dev/input/js*)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = tk.Tk()
    app = JoystickApp(root, args.device)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.disconnect(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
