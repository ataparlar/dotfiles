#!/usr/bin/env python3
"""
Waybar GPU Monitor Script
Reports usage, temperature, VRAM, and power draw for NVIDIA & Intel GPUs.
Supports cycling display modes (Usage% -> Temp°C -> VRAM) on click.
"""

import json
import subprocess
import sys
from pathlib import Path

MODE_FILE = Path("/tmp/waybar-gpu-mode")
NV_RUNTIME_STATUS = Path("/sys/bus/pci/devices/0000:01:00.0/power/runtime_status")
INTEL_FREQ_PATH = Path("/sys/class/drm/card1/gt_act_freq_mhz")

def get_mode() -> int:
    if MODE_FILE.exists():
        try:
            return int(MODE_FILE.read_text().strip()) % 3
        except Exception:
            return 0
    return 0

def toggle_mode():
    current = get_mode()
    new_mode = (current + 1) % 3
    try:
        MODE_FILE.write_text(str(new_mode))
    except Exception:
        pass
    # Signal waybar to refresh custom/gpu (signal 8 -> SIGRTMIN+8)
    subprocess.run(["pkill", "-RTMIN+8", "waybar"])

def get_intel_info() -> str:
    if INTEL_FREQ_PATH.exists():
        try:
            freq = INTEL_FREQ_PATH.read_text().strip()
            return f"Intel Iris Xe: {freq} MHz"
        except Exception:
            pass
    return ""

def main():
    if "--toggle" in sys.argv:
        toggle_mode()
        return

    mode = get_mode()

    # Check if NVIDIA GPU is suspended to avoid waking it up
    is_suspended = False
    if NV_RUNTIME_STATUS.exists():
        try:
            status = NV_RUNTIME_STATUS.read_text().strip().lower()
            if status == "suspended":
                is_suspended = True
        except Exception:
            pass

    if is_suspended:
        intel_info = get_intel_info()
        tooltip_lines = [
            "GPU: NVIDIA GeForce RTX 3060",
            "Status: Power-save (Suspended)",
        ]
        if intel_info:
            tooltip_lines.append(intel_info)
        tooltip_lines.append("\nClick to cycle display mode")

        print(json.dumps({
            "text": "󰢮 OFF",
            "tooltip": "\n".join(tooltip_lines),
            "class": "off",
            "percentage": 0
        }))
        return

    # Query NVIDIA GPU details
    try:
        res = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True,
            text=True,
            timeout=1.5
        )
        if res.returncode != 0 or not res.stdout.strip():
            raise RuntimeError(res.stderr.strip() or "No output from nvidia-smi")

        parts = [p.strip() for p in res.stdout.strip().split(",")]
        name = parts[0]
        util = int(float(parts[1]))
        temp = int(round(float(parts[2])))
        mem_used = int(float(parts[3]))
        mem_total = int(float(parts[4]))
        power = round(float(parts[5]), 1)
        mem_pct = round((mem_used / mem_total) * 100, 1)

        # Determine display text based on active mode
        if mode == 1:
            text = f"󰢮 {temp}°C"
        elif mode == 2:
            if mem_used >= 1024:
                text = f"󰢮 {mem_used / 1024:.1f}G"
            else:
                text = f"󰢮 {mem_used}M"
        else:
            text = f"󰢮 {util}%"

        # Determine CSS class
        css_class = "normal"
        if util >= 85 or temp >= 85:
            css_class = "critical"
        elif util >= 70 or temp >= 75:
            css_class = "warning"

        mode_labels = ["Usage (%)", "Temperature (°C)", "VRAM (Used)"]
        current_mode_label = mode_labels[mode]

        intel_info = get_intel_info()
        tooltip_lines = [
            f"GPU: {name}",
            f"Usage: {util}%",
            f"Temperature: {temp}°C",
            f"Memory: {mem_used} MiB / {mem_total} MiB ({mem_pct}%)",
            f"Power Draw: {power} W"
        ]
        if intel_info:
            tooltip_lines.append(intel_info)
        tooltip_lines.append(f"\nMode: {current_mode_label} (Click to cycle)")

        print(json.dumps({
            "text": text,
            "tooltip": "\n".join(tooltip_lines),
            "class": css_class,
            "percentage": util
        }))

    except Exception as e:
        intel_info = get_intel_info()
        tooltip = f"GPU monitor: {e}"
        if intel_info:
            tooltip += f"\n{intel_info}"

        print(json.dumps({
            "text": "󰢮 --",
            "tooltip": tooltip,
            "class": "unknown",
            "percentage": 0
        }))

if __name__ == "__main__":
    main()
