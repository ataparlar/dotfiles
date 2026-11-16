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

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

now = datetime.datetime.now()
today = now.date()
cache_data = load_cache()
events = cache_data.get("events", cache_data) if "events" in cache_data else cache_data
cached_accounts = cache_data.get("accounts", []) if isinstance(cache_data, dict) else []
expired_names = [a.get("name", a.get("email", "Account")) for a in cached_accounts if isinstance(a, dict) and a.get("needs_reauth")]
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
if expired_names:
    tooltip_lines.append(f"⚠ Reconnect needed: {', '.join(expired_names)}")
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

classes = []
if today_items:
    classes.append("has-events")
if expired_names:
    classes.append("expired")

prefix = "⚠ " if expired_names else ""
output = {
    "text": f"{prefix}\U000f00ed  {now.strftime('%A %H:%M')}",
    "tooltip": "\n".join(tooltip_lines),
    "class": " ".join(classes),
}

print(json.dumps(output))
