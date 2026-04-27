#!/usr/bin/env python3
"""Windows joystick visualizer/calibration helper.

Uses pygame's joystick subsystem (SDL), which supports common Windows
controllers via XInput/DirectInput.
"""

from __future__ import annotations

import argparse
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Optional

import pygame


@dataclass
class StickWidget:
    canvas: tk.Canvas
    marker: int
    value_var: tk.StringVar
    axis_x_index: int
    axis_y_index: int


class JoystickApp:
    def __init__(self, root: tk.Tk, initial_device: Optional[int]) -> None:
        self.root = root
        self.root.title("Windows Joystick Calibrator")
        self.root.geometry("980x700")

        pygame.init()
        pygame.joystick.init()

        self.device_indices: list[int] = []
        self.joystick: Optional[pygame.joystick.Joystick] = None
        self.axis_states: list[float] = []
        self.button_states: list[int] = []
        self.hat_states: list[tuple[int, int]] = []

        self.stick_widgets: list[StickWidget] = []
        self.button_indicators: list[tuple[tk.Label, tk.StringVar]] = []
        self.hat_indicators: list[tuple[tk.Label, tk.StringVar, int, str]] = []
        self.hat_value_vars: list[tk.StringVar] = []

        self._build_ui()
        self.refresh_devices()

        if self.device_indices:
            if initial_device is not None and initial_device in self.device_indices:
                selected_pos = self.device_indices.index(initial_device)
                self.device_var.set(self.device_combo["values"][selected_pos])
                self.connect_selected_device()
            else:
                self.device_var.set(self.device_combo["values"][0])
                self.connect_selected_device()

        self.root.after(16, self.poll_inputs)

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Device:").pack(side=tk.LEFT)
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(top, textvariable=self.device_var, state="readonly", width=45)
        self.device_combo.pack(side=tk.LEFT, padx=(8, 8))

        ttk.Button(top, text="Refresh", command=self.refresh_devices).pack(side=tk.LEFT)
        ttk.Button(top, text="Connect", command=self.connect_selected_device).pack(side=tk.LEFT, padx=(8, 0))

        self.status_var = tk.StringVar(value="No device connected")
        ttk.Label(self.root, textvariable=self.status_var, padding=(10, 4)).pack(fill=tk.X)

        content = ttk.Frame(self.root, padding=10)
        content.pack(fill=tk.BOTH, expand=True)

        axis_frame = ttk.LabelFrame(content, text="Axes", padding=10)
        axis_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
        self.axes_grid = ttk.Frame(axis_frame)
        self.axes_grid.pack(fill=tk.BOTH, expand=True)

        button_frame = ttk.LabelFrame(content, text="Buttons", padding=10)
        button_frame.pack(fill=tk.BOTH, expand=True, side=tk.BOTTOM, pady=(10, 0))
        self.buttons_grid = ttk.Frame(button_frame)
        self.buttons_grid.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.hats_grid = ttk.Frame(button_frame)
        self.hats_grid.pack(fill=tk.X)

    def refresh_devices(self) -> None:
        pygame.joystick.quit()
        pygame.joystick.init()

        values: list[str] = []
        self.device_indices = []

        for index in range(pygame.joystick.get_count()):
            js = pygame.joystick.Joystick(index)
            js.init()
            name = js.get_name()
            guid = js.get_guid() if hasattr(js, "get_guid") else ""
            display = f"{index}: {name}"
            if guid:
                display += f" ({guid[:8]})"
            values.append(display)
            self.device_indices.append(index)
            js.quit()

        self.device_combo["values"] = values
        if values and self.device_var.get() not in values:
            self.device_var.set(values[0])
        if not values:
            self.device_var.set("")
            self.status_var.set("No controllers detected")
            self._reset_dynamic_ui()

    def connect_selected_device(self) -> None:
        selected = self.device_var.get().strip()
        if not selected:
            self.status_var.set("Select a controller first")
            return

        try:
            index = int(selected.split(":", 1)[0])
        except ValueError:
            self.status_var.set("Could not parse selected device")
            return

        if index not in self.device_indices:
            self.status_var.set("Device list changed, press Refresh")
            return

        self.disconnect()

        js = pygame.joystick.Joystick(index)
        js.init()
        self.joystick = js

        axis_count = js.get_numaxes()
        button_count = js.get_numbuttons()
        hat_count = js.get_numhats()

        self.axis_states = [0.0] * axis_count
        self.button_states = [0] * button_count
        self.hat_states = [(0, 0)] * hat_count

        self._rebuild_dynamic_ui(axis_count, button_count, hat_count)
        self.status_var.set(
            f"Connected: {js.get_name()} | axes={axis_count}, buttons={button_count}, hats={hat_count}"
        )

    def disconnect(self) -> None:
        if self.joystick is not None:
            self.joystick.quit()
            self.joystick = None

    def _reset_dynamic_ui(self) -> None:
        for w in self.axes_grid.winfo_children():
            w.destroy()
        for w in self.buttons_grid.winfo_children():
            w.destroy()
        for w in self.hats_grid.winfo_children():
            w.destroy()
        self.stick_widgets.clear()
        self.button_indicators.clear()
        self.hat_indicators.clear()
        self.hat_value_vars.clear()

    def _rebuild_dynamic_ui(self, axis_count: int, button_count: int, hat_count: int) -> None:
        self._reset_dynamic_ui()

        pair_count = (axis_count + 1) // 2
        for pair in range(pair_count):
            axis_x = pair * 2
            axis_y = pair * 2 + 1

            frame = ttk.Frame(self.axes_grid, padding=6)
            frame.grid(row=pair // 3, column=pair % 3, sticky="nsew", padx=6, pady=6)

            ttk.Label(frame, text=f"Stick {pair + 1}: Axis {axis_x}/Axis {axis_y}").pack(anchor="w")

            canvas = tk.Canvas(frame, width=200, height=200, bg="#111111", highlightthickness=1, highlightbackground="#666")
            canvas.pack()
            canvas.create_rectangle(20, 20, 180, 180, outline="#888")
            canvas.create_line(100, 20, 100, 180, fill="#444")
            canvas.create_line(20, 100, 180, 100, fill="#444")
            marker = canvas.create_oval(94, 94, 106, 106, fill="#4caf50", outline="")

            value_var = tk.StringVar(value="x=+0.000 y=+0.000")
            ttk.Label(frame, textvariable=value_var).pack(anchor="w")

            self.stick_widgets.append(
                StickWidget(
                    canvas=canvas,
                    marker=marker,
                    value_var=value_var,
                    axis_x_index=axis_x,
                    axis_y_index=axis_y,
                )
            )

        for i in range(3):
            self.axes_grid.columnconfigure(i, weight=1)

        columns = 6
        for i in range(button_count):
            text_var = tk.StringVar(value=f"{i}: Button {i} [off]")
            widget = tk.Label(
                self.buttons_grid,
                textvariable=text_var,
                relief=tk.RIDGE,
                padx=8,
                pady=4,
                width=20,
                bg="#2d2d2d",
                fg="#ffffff",
            )
            widget.grid(row=i // columns, column=i % columns, sticky="ew", padx=4, pady=4)
            self.button_indicators.append((widget, text_var))

        for col in range(columns):
            self.buttons_grid.columnconfigure(col, weight=1)

        if hat_count:
            ttk.Label(self.hats_grid, text="D-Pad / Hats").grid(row=0, column=0, sticky="w", padx=(2, 2), pady=(2, 6))
            directions = ("Up", "Down", "Left", "Right")
            for hat_index in range(hat_count):
                value_var = tk.StringVar(value=f"Hat {hat_index}: x=0 y=0 [CENTER]")
                ttk.Label(self.hats_grid, textvariable=value_var).grid(
                    row=hat_index + 1, column=0, sticky="w", padx=(2, 8), pady=2
                )
                self.hat_value_vars.append(value_var)

                for dir_col, direction in enumerate(directions, start=1):
                    text_var = tk.StringVar(value=f"{direction} [off]")
                    widget = tk.Label(
                        self.hats_grid,
                        textvariable=text_var,
                        relief=tk.RIDGE,
                        padx=8,
                        pady=4,
                        width=12,
                        bg="#2d2d2d",
                        fg="#ffffff",
                    )
                    widget.grid(row=hat_index + 1, column=dir_col, sticky="ew", padx=4, pady=2)
                    self.hat_indicators.append((widget, text_var, hat_index, direction))

            for col in range(5):
                self.hats_grid.columnconfigure(col, weight=1 if col else 2)

        self._refresh_visuals()

    def _refresh_visuals(self) -> None:
        for stick in self.stick_widgets:
            x = self.axis_states[stick.axis_x_index] if stick.axis_x_index < len(self.axis_states) else 0.0
            y = self.axis_states[stick.axis_y_index] if stick.axis_y_index < len(self.axis_states) else 0.0

            cx = 100 + int(80 * x)
            cy = 100 - int(80 * y)
            stick.canvas.coords(stick.marker, cx - 6, cy - 6, cx + 6, cy + 6)
            stick.value_var.set(f"x={x:+.3f} y={y:+.3f}")

        for i, (widget, text_var) in enumerate(self.button_indicators):
            pressed = bool(self.button_states[i]) if i < len(self.button_states) else False
            text_var.set(f"{i}: Button {i} [{'ON' if pressed else 'off'}]")
            widget.configure(background="#3a7d44" if pressed else "#2d2d2d", foreground="#ffffff")

        for hat_index, value_var in enumerate(self.hat_value_vars):
            x, y = self.hat_states[hat_index] if hat_index < len(self.hat_states) else (0, 0)
            pos_label = "CENTER"
            if x == -1:
                pos_label = "LEFT"
            elif x == 1:
                pos_label = "RIGHT"
            if y == 1:
                pos_label = "UP" if pos_label == "CENTER" else f"{pos_label}+UP"
            elif y == -1:
                pos_label = "DOWN" if pos_label == "CENTER" else f"{pos_label}+DOWN"
            value_var.set(f"Hat {hat_index}: x={x} y={y} [{pos_label}]")

        for widget, text_var, hat_index, direction in self.hat_indicators:
            x, y = self.hat_states[hat_index] if hat_index < len(self.hat_states) else (0, 0)
            active = (
                (direction == "Up" and y == 1)
                or (direction == "Down" and y == -1)
                or (direction == "Left" and x == -1)
                or (direction == "Right" and x == 1)
            )
            text_var.set(f"{direction} [{'ON' if active else 'off'}]")
            widget.configure(background="#3a7d44" if active else "#2d2d2d", foreground="#ffffff")

    def poll_inputs(self) -> None:
        if self.joystick is not None:
            try:
                pygame.event.pump()
            except pygame.error:
                self.status_var.set("Pygame event pump failed; reconnect device")
                self.disconnect()

            for i in range(len(self.axis_states)):
                self.axis_states[i] = self.joystick.get_axis(i)

            for i in range(len(self.button_states)):
                self.button_states[i] = self.joystick.get_button(i)
            for i in range(len(self.hat_states)):
                self.hat_states[i] = self.joystick.get_hat(i)

            self._refresh_visuals()

        self.root.after(16, self.poll_inputs)

    def close(self) -> None:
        self.disconnect()
        pygame.joystick.quit()
        pygame.quit()
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Windows joystick visualizer/calibration GUI")
    parser.add_argument(
        "--device-index",
        type=int,
        default=None,
        help="Controller index to connect at startup (default: first detected controller)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = tk.Tk()
    app = JoystickApp(root, args.device_index)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
