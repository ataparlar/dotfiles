#!/usr/bin/python3
import json
import datetime
import os

CACHE_FILE = os.path.expanduser('~/.cache/waybar-ycal/events.json')
CONFIG_FILE = os.path.expanduser('~/.config/waybar-ycal/config.json')

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def load_events():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
                if isinstance(data, dict) and "events" in data:
                    return data["events"]
                return data
        except Exception:
            pass
    return {}

now = datetime.datetime.now()
today = now.date()
events = load_events()
config = load_config()
vis_cals = config.get('visible_calendars')
show_tasks = config.get('show_tasks_on_calendar', True)

raw_today_items = events.get(today.isoformat(), [])
today_items = []
for it in raw_today_items:
    if isinstance(it, dict) and it.get('type') == 'task':
        if show_tasks:
            today_items.append(it)
    elif isinstance(it, dict) and it.get('type') == 'event':
        if vis_cals is None or it.get('cal_id') in vis_cals:
            today_items.append(it)
    else:
        today_items.append(it)

tooltip_lines = [f"📅 {now.strftime('%A, %d %B %Y')}"]
if today_items:
    tooltip_lines.append("")
    for it in today_items:
        if isinstance(it, dict) and it.get('type') == 'event':
            time_part = f" ({it['time']})" if it.get('time') else ""
            tooltip_lines.append(f"• [{it.get('cal_summary', 'Event')}] {it.get('title', '')}{time_part}")
        elif isinstance(it, dict) and it.get('type') == 'task':
            st = "✓" if it.get('done') else "○"
            tooltip_lines.append(f"{st} [Task] {it.get('title', '')}")
        else:
            tooltip_lines.append(f"• {str(it)}")
else:
    tooltip_lines.append("No events or tasks scheduled for today")

output = {
    "text": f"\U000f00ed  {now.strftime('%A %H:%M')}",
    "tooltip": "\n".join(tooltip_lines),
    "class": "has-events" if today_items else ""
}

print(json.dumps(output))
