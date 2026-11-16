#!/usr/bin/python3
from ctypes import CDLL
CDLL('libgtk4-layer-shell.so')
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gio, GLib, Gtk4LayerShell, Pango, PangoCairo
import calendar
import datetime
import fcntl
import html
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import tomllib

CACHE_FILE = os.path.expanduser('~/.cache/waybar-ycal/events.json')
SYNC_LOCK_FILE = os.path.expanduser('~/.cache/waybar-ycal/.sync.lock')
PID_FILE = os.path.expanduser('~/.cache/waybar-ycal/popup.pid')
THEME_FILE = os.path.expanduser('~/.config/omarchy/current/theme/colors.toml')
CREDENTIALS_FILE = os.path.expanduser('~/.config/waybar-ycal/credentials.json')
TOKEN_FILE = os.path.expanduser('~/.cache/waybar-ycal/token.json')
SYNC_INTERVAL_SEC = 15 * 60  # 15 minutes

_SYNC_THREAD_LOCK = threading.Lock()

# Nerd Font family used for icon buttons (refresh + edit).
NERD_FONT = "JetBrainsMonoNL Nerd Font, JetBrainsMono Nerd Font, Symbols Nerd Font"

# Multi-account support
from accounts import (
    load_accounts,
    get_account,
    get_credentials_for_account,
    get_credentials_with_status,
    get_all_active_credentials,
    DEFAULT_CREDENTIALS_FILE,
    LEGACY_TOKEN_FILE,
    SCOPES,
)


def _get_credentials(account_id=None):
    """Get valid credentials for account_id or the default active account."""
    if account_id is not None:
        return get_credentials_for_account(account_id)

    accounts = load_accounts()
    for acc in accounts:
        if acc.get('enabled', True):
            creds = get_credentials_for_account(acc)
            if creds:
                return creds

    if os.path.exists(TOKEN_FILE):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
            if not creds.valid:
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
                        f.write(creds.to_json())
            return creds
        except Exception:
            pass
    return None


def _matches_account(item, acc_id, acc_email):
    """Return True if a cached calendar, event, or task list belongs to the account."""
    item_acc_id = item.get('account_id')
    item_email = item.get('account_email')
    if acc_id and item_acc_id == acc_id:
        return True
    if acc_email and item_email == acc_email:
        return True
    return False


def _preserve_cached_calendars_and_events(prev_cache, acc_id, acc_email, unified_calendars, unified_events_by_date):
    """Copy previously cached calendars and events for an account so UI doesn't wipe them on error/expiry."""
    kept = False
    for c in prev_cache.get('calendars', []):
        if isinstance(c, dict) and _matches_account(c, acc_id, acc_email):
            cached_cal = dict(c)
            cached_cal['stale'] = True
            unified_calendars.append(cached_cal)
            kept = True

    for date_key, items in prev_cache.get('events', {}).items():
        if not isinstance(items, list):
            continue
        for ev in items:
            if isinstance(ev, dict) and ev.get('type') == 'event' and _matches_account(ev, acc_id, acc_email):
                unified_events_by_date.setdefault(date_key, []).append(ev)
                kept = True
    return kept


def _preserve_cached_tasks(prev_cache, acc_id, acc_email, unified_task_lists, unified_events_by_date):
    """Copy previously cached task lists and re-index due tasks for an account."""
    kept = False

    def index_due_tasks(tasks):
        for t in tasks:
            if isinstance(t, dict):
                if t.get('due'):
                    unified_events_by_date.setdefault(t['due'], []).append(t)
                index_due_tasks(t.get('subtasks', []))

    for tl in prev_cache.get('task_lists', []):
        if isinstance(tl, dict) and _matches_account(tl, acc_id, acc_email):
            cached_tl = dict(tl)
            cached_tl['stale'] = True
            unified_task_lists.append(cached_tl)
            index_due_tasks(cached_tl.get('tasks', []))
            kept = True
    return kept


def _is_api_auth_error(err):
    """Return True if an API call failed due to revoked/expired auth rather than offline/transient error."""
    status = getattr(getattr(err, 'resp', None), 'status', None)
    if status == 401:
        return True
    msg = str(err).lower()
    return any(k in msg for k in ('invalid_grant', 'invalid credentials', 'unauthenticated', 'expired or revoked'))


def _write_cache_atomic(cache_data):
    """Atomically write cache JSON using a unique temp file to prevent multi-process races."""
    cache_dir = os.path.dirname(CACHE_FILE)
    os.makedirs(cache_dir, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=cache_dir,
            prefix='events.',
            suffix='.tmp',
            delete=False,
        ) as f:
            tmp_path = f.name
            json.dump(cache_data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CACHE_FILE)
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise


def _run_sync():
    """Fetch events from Google Calendar and Google Tasks across all enabled accounts, write to cache. Runs in a thread."""
    with _SYNC_THREAD_LOCK:
        cache_dir = os.path.dirname(CACHE_FILE)
        os.makedirs(cache_dir, exist_ok=True)
        try:
            with open(SYNC_LOCK_FILE, 'w') as lock_f:
                fcntl.flock(lock_f, fcntl.LOCK_EX)
                try:
                    _run_sync_locked()
                finally:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
        except Exception as e:
            print(f'[gcal sync error] {e}', file=sys.stderr)


def _run_sync_locked():
    """Locked implementation of multi-account sync."""
    try:
        from googleapiclient.discovery import build
        from accounts import load_accounts, ensure_dirs

        ensure_dirs()
        accounts = load_accounts()
        if not accounts:
            creds = _get_credentials()
            if creds is None:
                return
            accounts = load_accounts()
            if not accounts:
                return

        prev_cache = {}
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        prev_cache = loaded
            except Exception:
                prev_cache = {}

        today = datetime.date.today()
        # Fetch from 1 year past to 2 years future to cover academic calendars, deadlines, and events
        time_min = (today - datetime.timedelta(days=365)).isoformat() + 'T00:00:00Z'
        time_max = (today + datetime.timedelta(days=730)).isoformat() + 'T23:59:59Z'

        unified_events_by_date = {}
        unified_task_lists = []
        unified_calendars = []
        accounts_data = []

        for acc in accounts:
            if not acc.get('enabled', True):
                continue

            acc_id = acc.get('id')
            acc_name = acc.get('name', 'Google Account')
            acc_email = acc.get('email', '')
            acc_color = acc.get('color', '#4285f4')

            creds, err_kind, err_msg = get_credentials_with_status(acc)

            if not creds:
                acc_status = 'expired' if err_kind == 'auth_expired' else 'error'
                _preserve_cached_calendars_and_events(
                    prev_cache, acc_id, acc_email, unified_calendars, unified_events_by_date
                )
                _preserve_cached_tasks(
                    prev_cache, acc_id, acc_email, unified_task_lists, unified_events_by_date
                )
                accounts_data.append({
                    'id': acc_id,
                    'name': acc_name,
                    'email': acc_email,
                    'color': acc_color,
                    'enabled': True,
                    'status': acc_status,
                    'needs_reauth': (err_kind == 'auth_expired'),
                    'error': err_msg,
                    'stale': True,
                })
                continue

            acc_status = 'ok'
            needs_reauth = False
            acc_error = None
            stale = False

            # Fetch Calendars into staging containers so failure keeps cached data intact
            acc_cals = []
            acc_events_by_date = {}
            try:
                service = build('calendar', 'v3', credentials=creds)
                cal_list = service.calendarList().list().execute()
                raw_cals = cal_list.get('items', [])
                for c in raw_cals:
                    cal_info = {
                        'id': c['id'],
                        'summary': c.get('summary', '(Untitled Calendar)'),
                        'description': c.get('description', ''),
                        'color': c.get('backgroundColor', '#94baa6'),
                        'fg_color': c.get('foregroundColor', '#000000'),
                        'selected': bool(c.get('selected', False)),
                        'primary': bool(c.get('primary', False)),
                        'access_role': c.get('accessRole', 'reader'),
                        'account_id': acc_id,
                        'account_name': acc_name,
                        'account_email': acc_email,
                        'account_color': acc_color,
                    }
                    acc_cals.append(cal_info)

                    # Fetch Events for this calendar
                    try:
                        result = service.events().list(
                            calendarId=c['id'],
                            timeMin=time_min,
                            timeMax=time_max,
                            singleEvents=True,
                            orderBy='startTime',
                            maxResults=2500,
                        ).execute()
                    except Exception as e:
                        print(f"[gcal sync calendar error: {c.get('summary')}] {e}", file=sys.stderr)
                        continue

                    for item in result.get('items', []):
                        start = item.get('start', {})
                        end = item.get('end', {})
                        title = item.get('summary', '(no title)')
                        location = item.get('location', '')
                        description = item.get('description', '')
                        html_link = item.get('htmlLink', '')

                        if 'dateTime' in start:
                            dt = datetime.datetime.fromisoformat(start['dateTime'])
                            dt_end = datetime.datetime.fromisoformat(end.get('dateTime', start['dateTime']))
                            time_str = f"{dt.strftime('%H:%M')}-{dt_end.strftime('%H:%M')}"
                            ev_item = {
                                'type': 'event',
                                'id': item.get('id', ''),
                                'cal_id': c['id'],
                                'cal_summary': c.get('summary', '(Untitled Calendar)'),
                                'cal_color': c.get('backgroundColor', '#94baa6'),
                                'title': title,
                                'time': time_str,
                                'start': start['dateTime'],
                                'end': end.get('dateTime', ''),
                                'location': location,
                                'description': description,
                                'html_link': html_link,
                                'account_id': acc_id,
                                'account_name': acc_name,
                                'account_email': acc_email,
                                'account_color': acc_color,
                            }
                            acc_events_by_date.setdefault(dt.date().isoformat(), []).append(ev_item)
                        elif 'date' in start:
                            d = datetime.date.fromisoformat(start['date'])
                            d_end = datetime.date.fromisoformat(end.get('date', start['date']))
                            ev_item = {
                                'type': 'event',
                                'id': item.get('id', ''),
                                'cal_id': c['id'],
                                'cal_summary': c.get('summary', '(Untitled Calendar)'),
                                'cal_color': c.get('backgroundColor', '#94baa6'),
                                'title': title,
                                'time': 'All day',
                                'start': start['date'],
                                'end': end.get('date', ''),
                                'location': location,
                                'description': description,
                                'html_link': html_link,
                                'account_id': acc_id,
                                'account_name': acc_name,
                                'account_email': acc_email,
                                'account_color': acc_color,
                            }
                            if d == d_end:
                                acc_events_by_date.setdefault(d.isoformat(), []).append(ev_item)
                            else:
                                cur = d
                                while cur < d_end:
                                    acc_events_by_date.setdefault(cur.isoformat(), []).append(ev_item)
                                    cur += datetime.timedelta(days=1)

                unified_calendars.extend(acc_cals)
                for date_key, ev_list in acc_events_by_date.items():
                    unified_events_by_date.setdefault(date_key, []).extend(ev_list)
            except Exception as e:
                print(f"[gcal sync calendar error for account {acc_email}]: {e}", file=sys.stderr)
                stale = True
                acc_error = str(e)
                if _is_api_auth_error(e):
                    acc_status = 'expired'
                    needs_reauth = True
                elif acc_status == 'ok':
                    acc_status = 'error'
                _preserve_cached_calendars_and_events(
                    prev_cache, acc_id, acc_email, unified_calendars, unified_events_by_date
                )

            # Fetch Google Tasks into staging containers
            acc_task_lists = []
            acc_due_tasks = []
            try:
                tasks_service = build('tasks', 'v1', credentials=creds)
                task_lists = tasks_service.tasklists().list().execute()

                for tl in task_lists.get('items', []):
                    tl_id = tl['id']
                    tl_title = tl.get('title', 'Tasks')
                    try:
                        tasks_res = tasks_service.tasks().list(
                            tasklist=tl_id,
                            showCompleted=True,
                            showHidden=True,
                            maxResults=100,
                        ).execute()
                    except Exception:
                        continue

                    raw_tasks = tasks_res.get('items', [])
                    task_map = {}
                    top_level_tasks = []
                    subs_by_parent = {}

                    for task in raw_tasks:
                        t_id = task['id']
                        due = task.get('due')  # RFC 3339 timestamp
                        title = task.get('title', '(no title)')
                        notes = task.get('notes') or ''
                        completed = task.get('status') == 'completed'
                        parent = task.get('parent')

                        # Extract time from notes (e.g. ⏰ 14:30 or [14:30]) or due timestamp
                        time_str = None
                        clean_notes = notes
                        time_m = re.search(r'^(?:⏰\s*|\[)(\d{1,2}:\d{2})(?:\]|\n|\s*)', notes)
                        if time_m:
                            time_str = time_m.group(1)
                            clean_notes = notes[time_m.end():].lstrip()
                        elif due and len(due) > 16 and due[11:16] != '00:00':
                            time_str = due[11:16]

                        task_item = {
                            'type': 'task',
                            'id': t_id,
                            'lid': tl_id,
                            'title': title,
                            'notes': clean_notes,
                            'raw_notes': notes,
                            'done': completed,
                            'due': due[:10] if due else None,
                            'time': time_str,
                            'parent': parent,
                            'position': task.get('position', ''),
                            'account_id': acc_id,
                            'account_name': acc_name,
                            'account_email': acc_email,
                            'account_color': acc_color,
                            'subtasks': [],
                        }
                        task_map[t_id] = task_item
                        if parent:
                            subs_by_parent.setdefault(parent, []).append(task_item)
                        else:
                            top_level_tasks.append(task_item)

                    # Link subtasks to their parent task
                    for pid, subs in subs_by_parent.items():
                        if pid in task_map:
                            parent_task = task_map[pid]
                            for s in subs:
                                s['parent_title'] = parent_task['title']
                            parent_task['subtasks'] = subs
                        else:
                            top_level_tasks.extend(subs)

                    for t_item in task_map.values():
                        if t_item.get('due'):
                            acc_due_tasks.append((t_item['due'], t_item))

                    acc_task_lists.append({
                        'id': tl_id,
                        'title': tl_title,
                        'account_id': acc_id,
                        'account_name': acc_name,
                        'account_email': acc_email,
                        'account_color': acc_color,
                        'tasks': top_level_tasks,
                    })

                unified_task_lists.extend(acc_task_lists)
                for due_date, t_item in acc_due_tasks:
                    unified_events_by_date.setdefault(due_date, []).append(t_item)
            except Exception as e:
                print(f"[tasks sync error for account {acc_email}]: {e}", file=sys.stderr)
                stale = True
                if not acc_error:
                    acc_error = str(e)
                if _is_api_auth_error(e):
                    acc_status = 'expired'
                    needs_reauth = True
                elif acc_status == 'ok':
                    acc_status = 'error'
                _preserve_cached_tasks(
                    prev_cache, acc_id, acc_email, unified_task_lists, unified_events_by_date
                )

            accounts_data.append({
                'id': acc_id,
                'name': acc_name,
                'email': acc_email,
                'color': acc_color,
                'enabled': True,
                'status': acc_status,
                'needs_reauth': needs_reauth,
                'error': acc_error,
                'stale': stale,
            })

        cache_data = {
            'events': unified_events_by_date,
            'task_lists': unified_task_lists,
            'calendars': unified_calendars,
            'accounts': accounts_data,
        }
        _write_cache_atomic(cache_data)

    except Exception as e:
        print(f'[gcal sync error] {e}', file=sys.stderr)


def sync_in_background():
    threading.Thread(target=_run_sync, daemon=True).start()
    return True  # Keep GLib timer repeating

CURRENT_THEME_FILE = os.path.expanduser('~/.config/waybar-ycal/current_theme.json')

def load_theme():
    if os.path.exists(CURRENT_THEME_FILE):
        try:
            with open(CURRENT_THEME_FILE, 'r') as f:
                d = json.load(f)
                return {
                    'foreground': d.get('text_fg', '#d8deda'),
                    'background': '#1b221f',
                    'accent': d.get('accent', '#94baa6'),
                    **d
                }
        except Exception:
            pass
    defaults = {
        'foreground': '#d8deda',
        'background': '#1b221f',
        'accent': '#94baa6',
    }
    try:
        with open(THEME_FILE, 'rb') as f:
            t = tomllib.load(f)
            return {**defaults, **t}
    except Exception:
        return defaults

def hex_to_rgb_float(hex_color):
    h = hex_color.lstrip('#')
    return int(h[0:2], 16)/255, int(h[2:4], 16)/255, int(h[4:6], 16)/255

def hex_to_rgba(hex_color, alpha):
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f'rgba({r}, {g}, {b}, {alpha})'

def _load_cache_dict():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

def load_data():
    data = _load_cache_dict()
    if 'events' in data:
        return data.get('events', {}), data.get('task_lists', []), data.get('calendars', [])
    if data:
        return data, [], []
    return {}, [], []

def load_calendars():
    return _load_cache_dict().get('calendars', [])

def load_cached_accounts():
    """Return cached account runtime statuses (e.g. needs_reauth, error, stale)."""
    return _load_cache_dict().get('accounts', [])

def load_events():
    events, _, _ = load_data()
    return events


class ClickShield(Gtk.Window):
    """Transparent fullscreen window that catches clicks outside the popup."""
    def __init__(self, app, on_click):
        super().__init__(application=app)
        self.set_decorated(False)
        self.add_css_class('click-shield')
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.TOP)
        for edge in [Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM,
                     Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT]:
            Gtk4LayerShell.set_anchor(self, edge, True)
        Gtk4LayerShell.set_exclusive_zone(self, -1)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.NONE)
        box = Gtk.Box()
        box.set_hexpand(True)
        box.set_vexpand(True)
        self.set_child(box)
        gesture = Gtk.GestureClick()
        gesture.connect('pressed', lambda *_: on_click())
        box.add_controller(gesture)
        self.set_visible(False)


class CalendarPopup(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("waybar-ycal")
        self.set_default_size(-1, -1)

        self.today = datetime.date.today()
        self.year = self.today.year
        self.month = self.today.month
        self.selected_date = self.today
        self.events, self.task_lists, self.calendars = load_data()
        self._selected_btn = None
        self._cred_poll_timer = None
        self._tasks_visible = True
        self._collapsed_parents = set()
        self._dialog_mode = 'create'
        self._dialog_task = None
        self._dialog_lists = []
        self._dialog_parent_ids = []
        self._shield = ClickShield(app, self._hide)

        try:
            gfile = Gio.File.new_for_path(CACHE_FILE)
            self._file_monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self._file_monitor.connect("changed", self._on_file_changed)
        except Exception:
            self._file_monitor = None

        self._setup_window()
        self._apply_css()
        self._build_ui()

    def _on_file_changed(self, monitor, file, other_file, event_type):
        if event_type in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            if self.get_visible():
                GLib.idle_add(self._reload_ui)

    def _reload_ui(self):
        self.events, self.task_lists, self.calendars = load_data()
        self._build_grid()
        self._update_day_panel(self.selected_date)
        self._build_task_lists()
        return False

    def _setup_window(self):
        self.set_decorated(False)
        self.set_resizable(False)
        self.connect("close-request", lambda *_: self._hide())

        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.TOP, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.LEFT, False)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT, False)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, 4)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.ON_DEMAND)

        # Intercept Escape to close dialog first if open, or hide window
        key_ctrl = Gtk.EventControllerKey()
        def on_window_key(ctrl, keyval, keycode, state):
            if keyval == 65307:  # Escape
                if hasattr(self, 'dialog_scrim') and self.dialog_scrim.get_visible():
                    self.close_task_dialog()
                    return True
                self._hide()
                return True
            return False
        key_ctrl.connect("key-pressed", on_window_key)
        self.add_controller(key_ctrl)

        self.set_visible(False)

    def toggle(self):
        if self.get_visible():
            self._hide()
        else:
            self._show()

    def _show(self):
        self._apply_css()
        self._shield.present()
        if not os.path.exists(CREDENTIALS_FILE):
            self._show_setup_screen('no_credentials')
            self.present()
            return
        if not os.path.exists(TOKEN_FILE):
            self._show_setup_screen('no_token')
            self.present()
            return
        self._reset_to_today()
        self._show_calendar()
        self.present()

    def _reset_to_today(self):
        self.today = datetime.date.today()
        self.year = self.today.year
        self.month = self.today.month
        self.selected_date = self.today
        self.events, self.task_lists, self.calendars = load_data()

    def _show_calendar(self):
        self.set_child(self.root_overlay)
        self._build_grid()
        self.month_label.set_markup(
            f"<b>{datetime.date(self.year, self.month, 1).strftime('%B %Y').upper()}</b>"
        )
        self._update_day_panel(self.today)
        self._build_task_lists()

    def _make_setup_card(self, title_text, msg_text):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.add_css_class('popup-bg')
        box.set_size_request(360, -1)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)

        title = Gtk.Label(label=title_text)
        title.add_css_class('setup-title')

        msg = Gtk.Label(label=msg_text)
        msg.add_css_class('setup-msg')
        msg.set_justify(Gtk.Justification.CENTER)

        box.append(title)
        box.append(msg)
        return box

    def _show_setup_screen(self, state):
        self.set_default_size(-1, -1)
        if self._cred_poll_timer is not None:
            GLib.source_remove(self._cred_poll_timer)
            self._cred_poll_timer = None

        if state == 'no_credentials':
            short_path = CREDENTIALS_FILE.replace(os.path.expanduser('~'), '~')
            box = self._make_setup_card(
                "Connect Google Calendar",
                f"Place your OAuth credentials at:\n{short_path}\n\nWaiting for file...",
            )
            open_btn = Gtk.Button(label="Open Google Cloud Console")
            open_btn.add_css_class('add-btn')
            open_btn.connect("clicked", self._on_open_console_clicked)
            box.append(open_btn)

            def poll_for_credentials():
                if os.path.exists(CREDENTIALS_FILE):
                    self._cred_poll_timer = None
                    self._show_setup_screen('no_token')
                    return False
                return True
            self._cred_poll_timer = GLib.timeout_add(2000, poll_for_credentials)

        elif state == 'no_token':
            box = self._make_setup_card(
                "Connect Google Account",
                "Click below to open a browser and\nauthenticate with Google.",
            )
            auth_btn = Gtk.Button(label="Authenticate")
            auth_btn.add_css_class('add-btn')
            auth_btn.connect("clicked", self._on_auth_clicked)
            box.append(auth_btn)

        self.set_child(box)

    def _on_open_console_clicked(self, btn):
        os.makedirs(os.path.dirname(CREDENTIALS_FILE), exist_ok=True)
        btn.set_sensitive(False)
        btn.set_label("Opened — place credentials.json and wait...")
        subprocess.Popen(['xdg-open', 'https://console.cloud.google.com/apis/credentials'])

    def _on_auth_clicked(self, btn):
        btn.set_sensitive(False)
        btn.set_label("Opening browser...")
        def do_auth():
            try:
                _get_credentials()
                _run_sync()
                def after():
                    self._reset_to_today()
                    self._show_calendar()
                    return False
                GLib.idle_add(after)
            except Exception as e:
                def after_err():
                    btn.set_label("Failed — try again")
                    btn.set_sensitive(True)
                    return False
                GLib.idle_add(after_err)
        threading.Thread(target=do_auth, daemon=True).start()

    def _hide(self):
        self._shield.set_visible(False)
        if self._cred_poll_timer is not None:
            GLib.source_remove(self._cred_poll_timer)
            self._cred_poll_timer = None
        if hasattr(self, 'dialog_scrim'):
            self.dialog_scrim.set_visible(False)
        self.set_visible(False)

    def _build_ui(self):
        # Root overlay for modal dialogs on top of main calendar content
        self.root_overlay = Gtk.Overlay()
        self.set_child(self.root_overlay)

        # Outer horizontal box: calendar left, day panel center, task lists right
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.main_box.set_size_request(-1, 380)
        self.main_box.add_css_class('popup-bg')
        self.root_overlay.set_child(self.main_box)

        # ── Left: calendar ──────────────────────────────────────
        self.left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.left_box.set_size_request(220, -1)
        self.main_box.append(self.left_box)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header.set_size_request(-1, 32)
        prev_btn = Gtk.Button(label="‹")
        prev_btn.connect("clicked", lambda _: self._navigate(-1))

        self.month_label = Gtk.Label()
        self.month_label.set_markup(
            f"<b>{datetime.date(self.year, self.month, 1).strftime('%B %Y').upper()}</b>"
        )
        self.month_label.set_hexpand(True)

        next_btn = Gtk.Button(label="›")
        next_btn.connect("clicked", lambda _: self._navigate(1))

        self._refresh_angle = 0.0
        self._refresh_spin_timer = None
        self._refresh_da = Gtk.DrawingArea()
        self._refresh_da.set_size_request(20, 20)
        self._refresh_da.set_draw_func(self._draw_refresh_icon)

        self.refresh_btn = Gtk.Button()
        self.refresh_btn.set_child(self._refresh_da)
        self.refresh_btn.set_size_request(28, 28)
        self.refresh_btn.set_valign(Gtk.Align.CENTER)
        self.refresh_btn.add_css_class('refresh-btn')
        self.refresh_btn.set_tooltip_text("Sync Google Calendar & Tasks")
        self.refresh_btn.connect("clicked", self._on_refresh_clicked)

        # Toggle Google Tasks lists side by side
        self.tasks_toggle_btn = Gtk.Button()
        tasks_toggle_lbl = Gtk.Label(label="\uf0ae")
        tasks_toggle_lbl.set_halign(Gtk.Align.CENTER)
        tasks_toggle_lbl.set_valign(Gtk.Align.CENTER)
        self.tasks_toggle_btn.set_child(tasks_toggle_lbl)
        self.tasks_toggle_btn.set_size_request(28, 28)
        self.tasks_toggle_btn.set_valign(Gtk.Align.CENTER)
        self.tasks_toggle_btn.add_css_class('refresh-btn')
        self.tasks_toggle_btn.add_css_class('nerd')
        self.tasks_toggle_btn.add_css_class('active-toggle')
        self.tasks_toggle_btn.set_tooltip_text("Toggle Google Tasks lists")
        self.tasks_toggle_btn.connect("clicked", self._on_toggle_tasks_clicked)

        header.append(prev_btn)
        header.append(self.month_label)
        header.append(next_btn)
        header.append(self.refresh_btn)
        header.append(self.tasks_toggle_btn)
        self.left_box.append(header)

        self.grid = None
        self._build_grid()

        # ── Divider ──────────────────────────────────────────────
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.add_css_class('panel-divider')
        self.main_box.append(sep)

        # ── Middle: day panel ────────────────────────────────────
        self.right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.right_box.set_size_request(190, -1)
        self.right_box.add_css_class('day-panel')
        self.main_box.append(self.right_box)

        # Date heading
        self.day_label = Gtk.Label()
        self.day_label.set_halign(Gtk.Align.START)
        self.day_label.add_css_class('day-heading')
        self.right_box.append(self.day_label)

        # Scrollable event list
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.right_box.append(scroll)

        self.events_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scroll.set_child(self.events_box)

        # Buttons at the bottom: + Event, + Task, Open Calendar in browser
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        btn_row.set_size_request(-1, 32)

        add_ev_btn = Gtk.Button(label="+ Event")
        add_ev_btn.add_css_class('add-btn')
        add_ev_btn.set_hexpand(True)
        add_ev_btn.set_tooltip_text("Add Google Calendar event")
        add_ev_btn.connect("clicked", self._on_add_clicked)

        add_task_btn = Gtk.Button(label="+ Task")
        add_task_btn.add_css_class('add-btn')
        add_task_btn.set_hexpand(True)
        add_task_btn.set_tooltip_text("Add Google Task for this day")
        add_task_btn.connect("clicked", lambda *_: self.open_task_dialog(mode='create', default_date=self.selected_date))

        edit_btn = Gtk.Button()
        edit_lbl = Gtk.Label(label="\uf044")
        edit_lbl.set_halign(Gtk.Align.CENTER)
        edit_lbl.set_valign(Gtk.Align.CENTER)
        edit_btn.set_child(edit_lbl)
        edit_btn.set_size_request(30, -1)
        edit_btn.set_hexpand(False)
        edit_btn.add_css_class('add-btn')
        edit_btn.add_css_class('nerd')
        edit_btn.set_tooltip_text("Open day in Google Calendar")
        edit_btn.connect("clicked", self._on_edit_clicked)

        btn_row.append(add_ev_btn)
        btn_row.append(add_task_btn)
        btn_row.append(edit_btn)
        self.right_box.append(btn_row)

        self._update_day_panel(self.today)

        # ── Task Lists container (side by side near the existings) ─
        self.task_lists_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.task_lists_scroll = Gtk.ScrolledWindow()
        self.task_lists_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.task_lists_scroll.set_propagate_natural_width(True)
        self.task_lists_scroll.set_child(self.task_lists_box)
        self.main_box.append(self.task_lists_scroll)

        self._build_task_lists()
        self._build_task_dialog()

    def _build_grid(self):
        if self.grid is not None:
            self.left_box.remove(self.grid)
        self._selected_btn = None

        self.grid = Gtk.Grid()
        self.grid.set_row_spacing(4)
        self.grid.set_column_spacing(0)
        self.grid.set_column_homogeneous(True)

        day_names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        for col, name in enumerate(day_names):
            lbl = Gtk.Label(label=name)
            lbl.add_css_class('weekday')
            if col >= 5:
                lbl.add_css_class('weekend-label')
            lbl.set_size_request(28, 18)
            self.grid.attach(lbl, col, 0, 1, 1)

        first = datetime.date(self.year, self.month, 1)
        start = first - datetime.timedelta(days=first.weekday())
        last = datetime.date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])
        weeks = math.ceil((first.weekday() + last.day) / 7)
        total_days = weeks * 7

        for i in range(total_days):
            date = start + datetime.timedelta(days=i)
            day_events = self.events.get(date.isoformat(), [])

            overlay = Gtk.Overlay()
            overlay.set_size_request(28, 28)

            number = Gtk.Label(label=str(date.day))
            number.set_halign(Gtk.Align.CENTER)
            number.set_valign(Gtk.Align.CENTER)
            overlay.set_child(number)

            has_events = any(isinstance(e, str) or (isinstance(e, dict) and e.get('type') == 'event') for e in day_events)
            has_tasks = any(isinstance(e, dict) and e.get('type') == 'task' and not e.get('done') for e in day_events)

            if has_events or has_tasks:
                bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
                bar_box.set_halign(Gtk.Align.CENTER)
                bar_box.set_valign(Gtk.Align.END)
                bar_box.set_margin_bottom(4)
                w = 8 if (has_events and has_tasks) else 18
                if has_tasks:
                    task_bar = Gtk.Box()
                    task_bar.add_css_class('task-bar')
                    task_bar.set_size_request(w, 2)
                    bar_box.append(task_bar)
                if has_events:
                    bar = Gtk.Box()
                    bar.add_css_class('event-bar')
                    bar.set_size_request(w, 2)
                    bar_box.append(bar)
                overlay.add_overlay(bar_box)

            btn = Gtk.Button()
            btn.set_child(overlay)
            btn.set_size_request(28, 28)
            btn.date = date
            btn.connect("clicked", self._on_day_clicked)

            if date.month != self.month:
                btn.add_css_class("other-month")
            if date.weekday() >= 5:
                btn.add_css_class("weekend")
            if date == self.today:
                btn.add_css_class("today")
            if date == self.selected_date:
                btn.add_css_class("selected")
                self._selected_btn = btn

            row = i // 7 + 1
            col = i % 7
            self.grid.attach(btn, col, row, 1, 1)

        self.left_box.append(self.grid)

    def _on_day_clicked(self, btn):
        if self._selected_btn is not None:
            self._selected_btn.remove_css_class('selected')
        self._selected_btn = btn
        btn.add_css_class('selected')
        self.selected_date = btn.date
        self._update_day_panel(btn.date)

    def _make_event_row(self, ev):
        """Build a single event or task row for the day panel."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        if isinstance(ev, dict) and (ev.get('type') == 'task' or 'lid' in ev):
            # Task row: dot, title button with time/notes, done toggle
            done = ev.get('done', False)
            is_sub = bool(ev.get('parent'))

            if is_sub:
                glyph = Gtk.Label(label="↳")
                glyph.add_css_class('subtask-glyph')
                row.append(glyph)

            dot = Gtk.Label(label="•")
            dot.add_css_class('done-dot' if done else 'task-dot')
            row.append(dot)

            title_btn = Gtk.Button()
            title_btn.add_css_class('task-title-btn')
            title_btn.set_hexpand(True)
            title_btn.connect("clicked", lambda *_: self.open_task_dialog(mode='edit', task=ev))

            label = Gtk.Label()
            label.set_halign(Gtk.Align.START)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.add_css_class('event-name')

            title = ev.get('title', '(no title)')
            time_part = f"<span alpha='75%' size='small'>{ev['time']}</span>  " if ev.get('time') else ""
            notes_icon = " <span alpha='50%' size='small'>\uf249</span>" if ev.get('notes') else ""

            if done:
                label.set_markup(f"{time_part}<span alpha='50%'><s>{html.escape(title)}</s></span>{notes_icon}")
            else:
                label.set_markup(f"{time_part}{html.escape(title)}{notes_icon}")

            title_btn.set_child(label)
            row.append(title_btn)

            tooltip_lines = [title]
            if ev.get('time'):
                tooltip_lines.append(f"Time: {ev['time']}")
            if is_sub and ev.get('parent_title'):
                tooltip_lines.append(f"Parent: {ev['parent_title']}")
            if ev.get('notes'):
                tooltip_lines.append(f"Notes:\n{ev['notes']}")
            row.set_tooltip_text("\n".join(tooltip_lines))

            toggle = Gtk.Button(label="✓")
            toggle.add_css_class('done-toggle')
            toggle.add_css_class('done-toggle-active' if done else 'done-toggle-inactive')
            toggle.connect("clicked", self._on_task_toggle, ev)
            row.append(toggle)
        elif isinstance(ev, dict) and ev.get('type') == 'event':
            cal_color = ev.get('cal_color', '#94baa6')
            cal_name = ev.get('cal_summary', 'Event')
            title = ev.get('title', '(no title)')
            time_str = ev.get('time', '')
            time_part = f"<span alpha='75%' size='small'>{html.escape(time_str)}</span>  " if time_str else ""

            # Colored dot
            dot = Gtk.Label()
            dot.set_markup(f"<span foreground='{cal_color}'>●</span>")
            row.append(dot)

            # Title & Time button
            title_btn = Gtk.Button()
            title_btn.add_css_class('task-title-btn')
            title_btn.set_hexpand(True)

            label = Gtk.Label()
            label.set_halign(Gtk.Align.START)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.add_css_class('event-name')
            label.set_markup(f"{time_part}<span foreground='{cal_color}' size='smaller'><b>[{html.escape(cal_name)}]</b></span> {html.escape(title)}")
            title_btn.set_child(label)
            if ev.get('html_link'):
                title_btn.connect("clicked", lambda *_, url=ev['html_link']: subprocess.Popen(['xdg-open', url]))
            row.append(title_btn)

            tooltip_lines = [f"{cal_name}: {title}"]
            if time_str:
                tooltip_lines.append(f"Time: {time_str}")
            if ev.get('location'):
                tooltip_lines.append(f"Location: {ev['location']}")
            if ev.get('description'):
                tooltip_lines.append(f"Description:\n{ev['description']}")
            row.set_tooltip_text("\n".join(tooltip_lines))
        else:
            # Event row: accent dot + title
            dot = Gtk.Label(label="•")
            dot.add_css_class('event-dot')
            name = Gtk.Label(label=str(ev))
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.set_tooltip_text(str(ev))
            name.add_css_class('event-name')
            row.append(dot)
            row.append(name)

        return row

    def _update_day_panel(self, date):
        # Update heading
        if date == self.today:
            heading = f"<b>Today</b>  <span alpha='60%'>{date.strftime('%d %b').lstrip('0')}</span>"
        else:
            heading = f"<b>{date.strftime('%A')}</b>  <span alpha='60%'>{date.strftime('%d %b').lstrip('0')}</span>"
        self.day_label.set_markup(heading)

        while True:
            child = self.events_box.get_first_child()
            if child is None:
                break
            self.events_box.remove(child)

        raw_events = self.events.get(date.isoformat(), [])
        # Sort order: undone tasks (0) → events (1) → done tasks (2)
        day_events = sorted(
            raw_events,
            key=lambda e: 0 if (isinstance(e, dict) and e.get('type') == 'task' and not e.get('done')) else (2 if (isinstance(e, dict) and e.get('type') == 'task' and e.get('done')) else 1)
        )
        if day_events:
            for ev in day_events:
                self.events_box.append(self._make_event_row(ev))
        else:
            empty = Gtk.Label(label="No events")
            empty.add_css_class('no-events')
            empty.set_halign(Gtk.Align.START)
            self.events_box.append(empty)

    def _on_add_clicked(self, _):
        d = self.selected_date
        url = (f"https://calendar.google.com/calendar/r/eventedit"
               f"?dates={d.strftime('%Y%m%d')}/{d.strftime('%Y%m%d')}")
        subprocess.Popen(['xdg-open', 'https://calendar.google.com/calendar/r/eventedit'])
        self._hide()

    def _on_edit_clicked(self, _):
        d = self.selected_date
        url = f"https://calendar.google.com/calendar/r/day/{d.year}/{d.month}/{d.day}"
        subprocess.Popen(['xdg-open', url])
        self._hide()

    def _on_task_toggle(self, btn, task):
        btn.set_sensitive(False)
        btn.add_css_class('pulsing')
        def do_toggle():
            try:
                from googleapiclient.discovery import build
                creds = _get_credentials(task.get('account_id'))
                if creds is None:
                    raise RuntimeError('Account session expired — please reconnect.')
                service = build('tasks', 'v1', credentials=creds)
                new_status = 'needsAction' if task.get('done') else 'completed'
                service.tasks().patch(
                    tasklist=task['lid'],
                    task=task['id'],
                    body={'status': new_status},
                ).execute()
                _run_sync()
                def after():
                    self.events, self.task_lists, self.calendars = load_data()
                    self._build_grid()
                    self._update_day_panel(self.selected_date)
                    self._build_task_lists()
                    return False
                GLib.idle_add(after)
            except Exception as e:
                print(f'[task toggle error] {e}', file=sys.stderr)
                def after_err():
                    btn.remove_css_class('pulsing')
                    btn.set_sensitive(True)
                    return False
                GLib.idle_add(after_err)
        threading.Thread(target=do_toggle, daemon=True).start()

    def _on_toggle_tasks_clicked(self, _):
        self._tasks_visible = not self._tasks_visible
        self.task_lists_scroll.set_visible(self._tasks_visible)
        if self._tasks_visible:
            self.tasks_toggle_btn.add_css_class('active-toggle')
        else:
            self.tasks_toggle_btn.remove_css_class('active-toggle')

    def _build_task_lists(self):
        while True:
            child = self.task_lists_box.get_first_child()
            if child is None:
                break
            self.task_lists_box.remove(child)

        if not self.task_lists:
            self.task_lists_scroll.set_visible(False)
            return

        self.task_lists_scroll.set_visible(self._tasks_visible)

        for tl in self.task_lists:
            sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
            sep.add_css_class('panel-divider')
            self.task_lists_box.append(sep)

            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            col.set_size_request(210, -1)
            col.add_css_class('day-panel')
            self.task_lists_box.append(col)

            tl_tasks = tl.get('tasks', [])

            def count_pending(tasks):
                c = 0
                for t in tasks:
                    if not t.get('done'):
                        c += 1
                    c += count_pending(t.get('subtasks', []))
                return c

            pending_count = count_pending(tl_tasks)

            header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            header_lbl = Gtk.Label()
            header_lbl.set_markup(
                f"<b>{html.escape(tl.get('title', 'Tasks'))}</b>  <span alpha='60%'>({pending_count})</span>"
            )
            header_lbl.set_halign(Gtk.Align.START)
            header_lbl.set_hexpand(True)
            header_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            header_lbl.set_tooltip_text(tl.get('title', 'Tasks'))
            header_lbl.add_css_class('day-heading')
            header_box.append(header_lbl)
            col.append(header_box)

            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_vexpand(True)
            col.append(scroll)

            tasks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            scroll.set_child(tasks_box)

            sorted_tasks = sorted(
                tl_tasks,
                key=lambda t: (1 if t.get('done') else 0, t.get('due') or '9999-99-99')
            )

            if sorted_tasks:
                for task in sorted_tasks:
                    tasks_box.append(self._make_task_item_row(task, is_subtask=False))
            else:
                empty = Gtk.Label(label="No tasks")
                empty.add_css_class('no-events')
                empty.set_halign(Gtk.Align.START)
                tasks_box.append(empty)

            col.append(self._make_task_list_bottom_row(tl))

    def _make_task_item_row(self, task, is_subtask=False):
        done = task.get('done', False)
        subtasks = task.get('subtasks', [])
        has_subtasks = bool(subtasks) and not is_subtask

        item_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        if is_subtask:
            item_row.set_margin_start(16)
            glyph = Gtk.Label(label="↳")
            glyph.add_css_class('subtask-glyph')
            item_row.append(glyph)

        dot = Gtk.Label(label="•")
        dot.add_css_class('done-dot' if done else 'task-dot')
        item_row.append(dot)

        # Subtasks expand/collapse toggle button for parent tasks
        subtasks_container = None
        if has_subtasks:
            is_collapsed = task['id'] in self._collapsed_parents
            subs_done = sum(1 for s in subtasks if s.get('done'))
            toggle_lbl = Gtk.Label(label=f"{'▶' if is_collapsed else '▼'} {subs_done}/{len(subtasks)}")
            toggle_lbl.add_css_class('subtask-badge')

            toggle_btn = Gtk.Button()
            toggle_btn.set_child(toggle_lbl)
            toggle_btn.add_css_class('subtasks-toggle-btn')
            toggle_btn.set_tooltip_text(f"{subs_done}/{len(subtasks)} subtasks done. Click to toggle expand.")

            def on_toggle_subs(_):
                if task['id'] in self._collapsed_parents:
                    self._collapsed_parents.remove(task['id'])
                    toggle_lbl.set_label(f"▼ {subs_done}/{len(subtasks)}")
                    if subtasks_container:
                        subtasks_container.set_visible(True)
                else:
                    self._collapsed_parents.add(task['id'])
                    toggle_lbl.set_label(f"▶ {subs_done}/{len(subtasks)}")
                    if subtasks_container:
                        subtasks_container.set_visible(False)
            toggle_btn.connect("clicked", on_toggle_subs)
            item_row.append(toggle_btn)

        # Title button: clicking opens edit dialog
        title_btn = Gtk.Button()
        title_btn.add_css_class('task-title-btn')
        title_btn.set_hexpand(True)
        title_btn.connect("clicked", lambda *_: self.open_task_dialog(mode='edit', task=task))

        name_lbl = Gtk.Label()
        name_lbl.set_halign(Gtk.Align.START)
        name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        name_lbl.add_css_class('event-name')

        title = task.get('title', '(no title)')
        due = task.get('due')
        due_time = task.get('time')

        due_badge = ""
        if due:
            try:
                d_obj = datetime.date.fromisoformat(due)
                today = datetime.date.today()
                time_str = f" {due_time}" if due_time else ""
                if d_obj == today:
                    due_badge = f"<span alpha='85%' size='small' foreground='#ffb86c'>Today{time_str}</span>"
                elif d_obj < today and not done:
                    due_badge = f"<span size='small' foreground='#ff5555'>{d_obj.strftime('%d %b')}{time_str}</span>"
                else:
                    due_badge = f"<span alpha='50%' size='small'>{d_obj.strftime('%d %b')}{time_str}</span>"
            except Exception:
                due_badge = ""

        notes_icon = " <span alpha='50%' size='small'>\uf249</span>" if task.get('notes') else ""

        if done:
            name_lbl.set_markup(f"<span alpha='50%'><s>{html.escape(title)}</s></span>{notes_icon}")
        else:
            if due_badge:
                name_lbl.set_markup(f"{html.escape(title)}  {due_badge}{notes_icon}")
            else:
                name_lbl.set_markup(f"{html.escape(title)}{notes_icon}")

        title_btn.set_child(name_lbl)
        item_row.append(title_btn)

        # Rich Tooltip
        tooltip_parts = [title]
        if due:
            t_str = f" {due_time}" if due_time else ""
            tooltip_parts.append(f"Due: {due}{t_str}")
        if is_subtask and task.get('parent_title'):
            tooltip_parts.append(f"Parent: {task['parent_title']}")
        if task.get('notes'):
            tooltip_parts.append(f"Notes:\n{task['notes']}")
        if has_subtasks:
            subs_done = sum(1 for s in subtasks if s.get('done'))
            tooltip_parts.append(f"Subtasks: {subs_done}/{len(subtasks)} done")
        item_row.set_tooltip_text("\n".join(tooltip_parts))

        # Add subtask button on parent tasks
        if not is_subtask:
            add_sub_btn = Gtk.Button()
            add_sub_lbl = Gtk.Label(label="↳+")
            add_sub_lbl.set_halign(Gtk.Align.CENTER)
            add_sub_lbl.set_valign(Gtk.Align.CENTER)
            add_sub_btn.set_child(add_sub_lbl)
            add_sub_btn.add_css_class('task-row-btn')
            add_sub_btn.set_tooltip_text("Add subtask")
            add_sub_btn.connect(
                "clicked",
                lambda *_: self.open_task_dialog(
                    mode='create',
                    default_list_id=task['lid'],
                    default_parent_id=task['id']
                )
            )
            item_row.append(add_sub_btn)

        # Edit task details button
        edit_btn = Gtk.Button()
        edit_lbl = Gtk.Label(label="\uf044")
        edit_lbl.set_halign(Gtk.Align.CENTER)
        edit_lbl.set_valign(Gtk.Align.CENTER)
        edit_btn.set_child(edit_lbl)
        edit_btn.add_css_class('task-row-btn')
        edit_btn.add_css_class('nerd')
        edit_btn.set_tooltip_text("Edit task details")
        edit_btn.connect("clicked", lambda *_: self.open_task_dialog(mode='edit', task=task))
        item_row.append(edit_btn)

        # Done toggle button
        toggle = Gtk.Button(label="✓")
        toggle.add_css_class('done-toggle')
        toggle.add_css_class('done-toggle-active' if done else 'done-toggle-inactive')
        toggle.connect("clicked", self._on_task_toggle, task)
        item_row.append(toggle)

        if not has_subtasks:
            return item_row

        # For parent tasks, wrap in container box with nested subtasks
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        container.append(item_row)

        subtasks_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        is_collapsed = task['id'] in self._collapsed_parents
        subtasks_container.set_visible(not is_collapsed)

        sorted_subs = sorted(
            subtasks,
            key=lambda t: (1 if t.get('done') else 0, t.get('due') or '9999-99-99')
        )
        for sub in sorted_subs:
            subtasks_container.append(self._make_task_item_row(sub, is_subtask=True))

        container.append(subtasks_container)
        return container

    def _make_task_list_bottom_row(self, tl):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        btn_row.set_size_request(-1, 32)

        add_btn = Gtk.Button(label="+ Add")
        add_btn.add_css_class('add-btn')
        add_btn.set_hexpand(True)
        add_btn.set_tooltip_text("Quick task add (title only)")

        detail_btn = Gtk.Button()
        detail_lbl = Gtk.Label(label="\uf013")
        detail_lbl.set_halign(Gtk.Align.CENTER)
        detail_lbl.set_valign(Gtk.Align.CENTER)
        detail_btn.set_child(detail_lbl)
        detail_btn.set_size_request(28, -1)
        detail_btn.add_css_class('add-btn')
        detail_btn.add_css_class('nerd')
        detail_btn.set_tooltip_text("Detailed task options (datetime, notes, subtask)")
        detail_btn.connect("clicked", lambda *_: self.open_task_dialog(mode='create', default_list_id=tl['id']))

        open_btn = Gtk.Button()
        open_lbl = Gtk.Label(label="\uf08e")
        open_lbl.set_halign(Gtk.Align.CENTER)
        open_lbl.set_valign(Gtk.Align.CENTER)
        open_btn.set_child(open_lbl)
        open_btn.set_size_request(28, -1)
        open_btn.set_hexpand(False)
        open_btn.add_css_class('add-btn')
        open_btn.add_css_class('nerd')
        open_btn.set_tooltip_text("Open Google Tasks in browser")
        open_btn.connect(
            "clicked",
            lambda _: subprocess.Popen(['xdg-open', 'https://calendar.google.com/calendar/u/0/r/tasks'])
        )

        btn_row.append(add_btn)
        btn_row.append(detail_btn)
        btn_row.append(open_btn)
        container.append(btn_row)

        entry_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        entry_row.set_visible(False)

        entry = Gtk.Entry()
        entry.set_placeholder_text("Task title (Enter to save)...")
        entry.add_css_class('task-entry')
        entry.set_hexpand(True)
        entry_row.append(entry)

        expand_btn = Gtk.Button()
        expand_lbl = Gtk.Label(label="…")
        expand_lbl.set_halign(Gtk.Align.CENTER)
        expand_lbl.set_valign(Gtk.Align.CENTER)
        expand_btn.set_child(expand_lbl)
        expand_btn.set_size_request(28, -1)
        expand_btn.add_css_class('add-btn')
        expand_btn.set_tooltip_text("Expand to detailed form")
        entry_row.append(expand_btn)

        container.append(entry_row)

        def on_add_clicked(_):
            btn_row.set_visible(False)
            entry_row.set_visible(True)
            entry.set_text("")
            entry.grab_focus()

        def on_activate(ent):
            val = ent.get_text().strip()
            if val:
                ent.set_sensitive(False)
                self._add_task_to_list(tl['id'], val)
            btn_row.set_visible(True)
            entry_row.set_visible(False)
            entry.set_sensitive(True)

        def on_cancel():
            btn_row.set_visible(True)
            entry_row.set_visible(False)

        def on_expand(_):
            current_text = entry.get_text().strip()
            on_cancel()
            self.open_task_dialog(mode='create', default_list_id=tl['id'])
            if current_text:
                self.dialog_title_entry.set_text(current_text)

        add_btn.connect("clicked", on_add_clicked)
        entry.connect("activate", on_activate)
        expand_btn.connect("clicked", on_expand)

        key_ctrl = Gtk.EventControllerKey()
        def on_key(ctrl, keyval, keycode, state):
            if keyval == 65307:  # Escape key
                on_cancel()
                return True
            return False
        key_ctrl.connect("key-pressed", on_key)
        entry.add_controller(key_ctrl)

        return container

    def _add_task_to_list(self, lid, title):
        def do_add():
            try:
                from googleapiclient.discovery import build
                acc_id = None
                for tl in getattr(self, 'task_lists', []):
                    if tl.get('id') == lid:
                        acc_id = tl.get('account_id')
                        break
                creds = _get_credentials(acc_id)
                if creds is None:
                    return
                service = build('tasks', 'v1', credentials=creds)
                service.tasks().insert(tasklist=lid, body={'title': title}).execute()
                _run_sync()
                def after():
                    self.events, self.task_lists, self.calendars = load_data()
                    self._build_grid()
                    self._update_day_panel(self.selected_date)
                    self._build_task_lists()
                    return False
                GLib.idle_add(after)
            except Exception as e:
                print(f'[add task error] {e}', file=sys.stderr)
        threading.Thread(target=do_add, daemon=True).start()

    # ── Task Creation & Editing Dialog ──────────────────────────────
    def _build_task_dialog(self):
        self.dialog_scrim = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.dialog_scrim.add_css_class('dialog-scrim')
        self.dialog_scrim.set_visible(False)
        self.root_overlay.add_overlay(self.dialog_scrim)

        self.dialog_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.dialog_card.add_css_class('dialog-card')
        self.dialog_card.set_size_request(360, -1)
        self.dialog_card.set_halign(Gtk.Align.CENTER)
        self.dialog_card.set_valign(Gtk.Align.CENTER)
        self.dialog_scrim.append(self.dialog_card)

        # Header: Title + Close Button
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.dialog_title_lbl = Gtk.Label()
        self.dialog_title_lbl.set_markup("<b>New Task</b>")
        self.dialog_title_lbl.set_halign(Gtk.Align.START)
        self.dialog_title_lbl.set_hexpand(True)
        self.dialog_title_lbl.add_css_class('dialog-title')
        hdr.append(self.dialog_title_lbl)

        close_btn = Gtk.Button(label="✕")
        close_btn.add_css_class('dialog-close-btn')
        close_btn.connect("clicked", lambda *_: self.close_task_dialog())
        hdr.append(close_btn)
        self.dialog_card.append(hdr)

        # Scrolled form container
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(420)
        scroll.set_propagate_natural_height(True)
        self.dialog_card.append(scroll)

        form_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroll.set_child(form_box)

        # List selector
        list_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        list_lbl = Gtk.Label(label="List:")
        list_lbl.set_size_request(50, -1)
        list_lbl.set_halign(Gtk.Align.START)
        list_lbl.add_css_class('dialog-label')
        list_row.append(list_lbl)

        self.dialog_list_dropdown = Gtk.DropDown()
        self.dialog_list_dropdown.set_hexpand(True)
        self.dialog_list_dropdown.connect("notify::selected", lambda *_: self._on_dialog_list_changed())
        list_row.append(self.dialog_list_dropdown)
        form_box.append(list_row)

        # Parent task selector (for subtasks)
        parent_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        parent_lbl = Gtk.Label(label="Parent:")
        parent_lbl.set_size_request(50, -1)
        parent_lbl.set_halign(Gtk.Align.START)
        parent_lbl.add_css_class('dialog-label')
        parent_row.append(parent_lbl)

        self.dialog_parent_dropdown = Gtk.DropDown()
        self.dialog_parent_dropdown.set_hexpand(True)
        parent_row.append(self.dialog_parent_dropdown)
        form_box.append(parent_row)

        # Task Title
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title_lbl = Gtk.Label(label="Title:")
        title_lbl.set_halign(Gtk.Align.START)
        title_lbl.add_css_class('dialog-label')
        title_box.append(title_lbl)

        self.dialog_title_entry = Gtk.Entry()
        self.dialog_title_entry.set_placeholder_text("Task title...")
        self.dialog_title_entry.add_css_class('task-entry')
        self.dialog_title_entry.connect("activate", lambda *_: self._save_task())
        title_box.append(self.dialog_title_entry)
        form_box.append(title_box)

        # Date Section
        date_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        date_hdr = Gtk.Label(label="Due Date:")
        date_hdr.set_halign(Gtk.Align.START)
        date_hdr.add_css_class('dialog-label')
        date_box.append(date_hdr)

        date_presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        btn_today = Gtk.Button(label="Today")
        btn_today.add_css_class('pill-btn')
        btn_today.connect("clicked", lambda *_: self.dialog_date_entry.set_text(datetime.date.today().isoformat()))

        btn_tmrw = Gtk.Button(label="Tomorrow")
        btn_tmrw.add_css_class('pill-btn')
        btn_tmrw.connect("clicked", lambda *_: self.dialog_date_entry.set_text((datetime.date.today() + datetime.timedelta(days=1)).isoformat()))

        btn_mon = Gtk.Button(label="Next Mon")
        btn_mon.add_css_class('pill-btn')
        def on_next_mon(_):
            t = datetime.date.today()
            d = (0 - t.weekday()) % 7
            if d == 0: d = 7
            self.dialog_date_entry.set_text((t + datetime.timedelta(days=d)).isoformat())
        btn_mon.connect("clicked", on_next_mon)

        btn_clear_d = Gtk.Button(label="Clear")
        btn_clear_d.add_css_class('pill-btn')
        btn_clear_d.connect("clicked", lambda *_: self.dialog_date_entry.set_text(""))

        date_presets.append(btn_today)
        date_presets.append(btn_tmrw)
        date_presets.append(btn_mon)
        date_presets.append(btn_clear_d)
        date_box.append(date_presets)

        self.dialog_date_entry = Gtk.Entry()
        self.dialog_date_entry.set_placeholder_text("YYYY-MM-DD")
        self.dialog_date_entry.add_css_class('task-entry')
        date_box.append(self.dialog_date_entry)
        form_box.append(date_box)

        # Time Section
        time_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        time_hdr = Gtk.Label(label="Time (optional):")
        time_hdr.set_halign(Gtk.Align.START)
        time_hdr.add_css_class('dialog-label')
        time_box.append(time_hdr)

        time_presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for t_val in ["09:00", "13:00", "17:00", "20:00"]:
            b = Gtk.Button(label=t_val)
            b.add_css_class('pill-btn')
            b.connect("clicked", lambda _, val=t_val: self.dialog_time_entry.set_text(val))
            time_presets.append(b)
        b_clear_t = Gtk.Button(label="Clear")
        b_clear_t.add_css_class('pill-btn')
        b_clear_t.connect("clicked", lambda *_: self.dialog_time_entry.set_text(""))
        time_presets.append(b_clear_t)
        time_box.append(time_presets)

        self.dialog_time_entry = Gtk.Entry()
        self.dialog_time_entry.set_placeholder_text("HH:MM (e.g. 14:30)")
        self.dialog_time_entry.add_css_class('task-entry')
        time_box.append(self.dialog_time_entry)
        form_box.append(time_box)

        # Notes / Description
        notes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        notes_hdr = Gtk.Label(label="Description / Notes:")
        notes_hdr.set_halign(Gtk.Align.START)
        notes_hdr.add_css_class('dialog-label')
        notes_box.append(notes_hdr)

        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        notes_scroll.set_size_request(-1, 65)
        self.dialog_notes_view = Gtk.TextView()
        self.dialog_notes_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.dialog_notes_view.add_css_class('task-notes-view')
        notes_scroll.set_child(self.dialog_notes_view)
        notes_box.append(notes_scroll)
        form_box.append(notes_box)

        # Subtasks container for edit mode
        self.dialog_subtasks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        form_box.append(self.dialog_subtasks_box)

        # Footer Actions
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        footer.set_margin_top(6)

        self.dialog_delete_btn = Gtk.Button(label="🗑 Delete")
        self.dialog_delete_btn.add_css_class('dialog-delete-btn')
        self.dialog_delete_btn.connect("clicked", lambda *_: self._delete_task())
        footer.append(self.dialog_delete_btn)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        footer.append(spacer)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.add_css_class('dialog-cancel-btn')
        cancel_btn.connect("clicked", lambda *_: self.close_task_dialog())
        footer.append(cancel_btn)

        self.dialog_save_btn = Gtk.Button(label="Save")
        self.dialog_save_btn.add_css_class('dialog-save-btn')
        self.dialog_save_btn.connect("clicked", lambda *_: self._save_task())
        footer.append(self.dialog_save_btn)

        self.dialog_card.append(footer)

    def _update_dialog_lists(self, selected_lid=None):
        titles = [tl['title'] for tl in self.task_lists]
        self._dialog_lists = self.task_lists
        model = Gtk.StringList.new(titles if titles else ["Default"])
        self.dialog_list_dropdown.set_model(model)
        selected_idx = 0
        if selected_lid:
            for idx, tl in enumerate(self.task_lists):
                if tl['id'] == selected_lid:
                    selected_idx = idx
                    break
        self.dialog_list_dropdown.set_selected(selected_idx)

    def _update_dialog_parents(self, selected_parent_id=None):
        idx = self.dialog_list_dropdown.get_selected()
        if idx >= len(self._dialog_lists):
            self.dialog_parent_dropdown.set_model(Gtk.StringList.new(["None (Top-level task)"]))
            self._dialog_parent_ids = [None]
            return

        current_tl = self._dialog_lists[idx]
        top_tasks = current_tl.get('tasks', [])
        editing_id = self._dialog_task['id'] if (self._dialog_mode == 'edit' and self._dialog_task) else None

        parent_titles = ["None (Top-level task)"]
        self._dialog_parent_ids = [None]

        for t in top_tasks:
            if editing_id and t['id'] == editing_id:
                continue
            parent_titles.append(f"↳ {t['title']}")
            self._dialog_parent_ids.append(t['id'])

        model = Gtk.StringList.new(parent_titles)
        self.dialog_parent_dropdown.set_model(model)

        selected_pos = 0
        if selected_parent_id:
            for p_idx, pid in enumerate(self._dialog_parent_ids):
                if pid == selected_parent_id:
                    selected_pos = p_idx
                    break
        self.dialog_parent_dropdown.set_selected(selected_pos)

    def _on_dialog_list_changed(self):
        self._update_dialog_parents()

    def _get_selected_list_id(self):
        idx = self.dialog_list_dropdown.get_selected()
        if idx < len(self._dialog_lists):
            return self._dialog_lists[idx]['id']
        return self._dialog_lists[0]['id'] if self._dialog_lists else None

    def _get_selected_parent_id(self):
        idx = self.dialog_parent_dropdown.get_selected()
        if idx < len(self._dialog_parent_ids):
            return self._dialog_parent_ids[idx]
        return None

    def open_task_dialog(self, mode='create', task=None, default_list_id=None, default_parent_id=None, default_date=None):
        self._dialog_mode = mode
        self._dialog_task = task

        # Clear existing subtasks display
        while True:
            child = self.dialog_subtasks_box.get_first_child()
            if child is None:
                break
            self.dialog_subtasks_box.remove(child)

        target_lid = default_list_id
        if task:
            target_lid = task.get('lid')
        elif not target_lid and self.task_lists:
            target_lid = self.task_lists[0]['id']

        self._update_dialog_lists(target_lid)
        self._update_dialog_parents(default_parent_id if mode == 'create' else (task.get('parent') if task else None))

        if mode == 'create':
            if default_parent_id:
                p_title = ""
                for tl in self.task_lists:
                    for t in tl.get('tasks', []):
                        if t['id'] == default_parent_id:
                            p_title = t.get('title', '')
                            break
                self.dialog_title_lbl.set_markup(f"<b>New Subtask</b> <span alpha='60%'>under {html.escape(p_title)}</span>")
                self.dialog_save_btn.set_label("Create Subtask")
            else:
                self.dialog_title_lbl.set_markup("<b>New Task</b>")
                self.dialog_save_btn.set_label("Create Task")

            self.dialog_delete_btn.set_visible(False)
            self.dialog_title_entry.set_text("")

            if default_date:
                self.dialog_date_entry.set_text(default_date.isoformat())
            else:
                self.dialog_date_entry.set_text("")

            self.dialog_time_entry.set_text("")
            self.dialog_notes_view.get_buffer().set_text("")

        elif mode == 'edit' and task:
            is_sub = bool(task.get('parent'))
            if is_sub:
                self.dialog_title_lbl.set_markup(f"<b>Edit Subtask</b> <span alpha='60%'>({html.escape(task.get('parent_title', ''))})</span>")
            else:
                self.dialog_title_lbl.set_markup("<b>Edit Task</b>")

            self.dialog_save_btn.set_label("Save Changes")
            self.dialog_delete_btn.set_visible(True)

            self.dialog_title_entry.set_text(task.get('title', ''))
            self.dialog_date_entry.set_text(task.get('due') or '')
            self.dialog_time_entry.set_text(task.get('time') or '')
            self.dialog_notes_view.get_buffer().set_text(task.get('notes') or '')

            # If editing parent task that has subtasks: show subtasks in dialog
            subtasks = task.get('subtasks', [])
            if not is_sub:
                subs_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                subs_lbl = Gtk.Label()
                subs_lbl.set_markup(f"<b>Subtasks ({len(subtasks)}):</b>")
                subs_lbl.set_halign(Gtk.Align.START)
                subs_lbl.set_hexpand(True)
                subs_lbl.add_css_class('dialog-label')
                subs_hdr.append(subs_lbl)

                add_sub_inline_btn = Gtk.Button(label="+ Add subtask")
                add_sub_inline_btn.add_css_class('pill-btn')
                add_sub_inline_btn.connect(
                    "clicked",
                    lambda *_: self.open_task_dialog(
                        mode='create',
                        default_list_id=task['lid'],
                        default_parent_id=task['id']
                    )
                )
                subs_hdr.append(add_sub_inline_btn)
                self.dialog_subtasks_box.append(subs_hdr)

                if subtasks:
                    for s in subtasks:
                        s_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                        s_glyph = Gtk.Label(label="↳")
                        s_glyph.add_css_class('subtask-glyph')
                        s_name = Gtk.Label()
                        s_name.set_halign(Gtk.Align.START)
                        s_name.set_hexpand(True)
                        s_name.set_ellipsize(Pango.EllipsizeMode.END)
                        s_name.add_css_class('event-name')
                        if s.get('done'):
                            s_name.set_markup(f"<span alpha='50%'><s>{html.escape(s['title'])}</s></span>")
                        else:
                            s_name.set_text(s['title'])

                        s_edit_btn = Gtk.Button()
                        s_edit_lbl = Gtk.Label(label="\uf044")
                        s_edit_lbl.set_halign(Gtk.Align.CENTER)
                        s_edit_lbl.set_valign(Gtk.Align.CENTER)
                        s_edit_btn.set_child(s_edit_lbl)
                        s_edit_btn.add_css_class('task-row-btn')
                        s_edit_btn.add_css_class('nerd')
                        s_edit_btn.connect("clicked", lambda _, sub_task=s: self.open_task_dialog(mode='edit', task=sub_task))

                        s_toggle = Gtk.Button(label="✓")
                        s_toggle.add_css_class('done-toggle')
                        s_toggle.add_css_class('done-toggle-active' if s.get('done') else 'done-toggle-inactive')
                        s_toggle.connect("clicked", self._on_task_toggle, s)

                        s_row.append(s_glyph)
                        s_row.append(s_name)
                        s_row.append(s_edit_btn)
                        s_row.append(s_toggle)
                        self.dialog_subtasks_box.append(s_row)

        self.dialog_scrim.set_visible(True)
        self.dialog_title_entry.grab_focus()

    def close_task_dialog(self):
        self.dialog_scrim.set_visible(False)
        self._dialog_task = None

    def _save_task(self):
        title = self.dialog_title_entry.get_text().strip()
        if not title:
            self.dialog_title_entry.grab_focus()
            return

        date_str = self.dialog_date_entry.get_text().strip() or None
        time_str = self.dialog_time_entry.get_text().strip() or None
        notes_buf = self.dialog_notes_view.get_buffer()
        notes_text = notes_buf.get_text(notes_buf.get_start_iter(), notes_buf.get_end_iter(), True).strip()

        # Combine time into notes if time_str provided
        if time_str:
            if not notes_text.startswith(f"⏰ {time_str}"):
                notes_text = f"⏰ {time_str}\n{notes_text}".strip()

        due_iso = None
        if date_str:
            try:
                datetime.date.fromisoformat(date_str)
                due_iso = f"{date_str}T00:00:00.000Z"
            except ValueError:
                pass

        lid = self._get_selected_list_id()
        parent_id = self._get_selected_parent_id()
        mode = self._dialog_mode
        task = self._dialog_task

        self.dialog_save_btn.set_sensitive(False)
        self.dialog_save_btn.add_css_class('pulsing')

        def do_save():
            try:
                from googleapiclient.discovery import build
                acc_id = None
                if task:
                    acc_id = task.get('account_id')
                if not acc_id and lid:
                    for tl in getattr(self, 'task_lists', []):
                        if tl.get('id') == lid:
                            acc_id = tl.get('account_id')
                            break
                creds = _get_credentials(acc_id)
                if creds is None:
                    raise RuntimeError('Account session expired — please reconnect.')
                service = build('tasks', 'v1', credentials=creds)

                body = {
                    'title': title,
                    'notes': notes_text if notes_text else '',
                }
                if due_iso:
                    body['due'] = due_iso
                elif mode == 'edit':
                    body['due'] = None

                if mode == 'create':
                    insert_kwargs = {'tasklist': lid, 'body': body}
                    if parent_id:
                        insert_kwargs['parent'] = parent_id
                    service.tasks().insert(**insert_kwargs).execute()
                elif mode == 'edit' and task:
                    service.tasks().patch(tasklist=task['lid'], task=task['id'], body=body).execute()
                    old_parent = task.get('parent')
                    if parent_id != old_parent:
                        move_kwargs = {'tasklist': task['lid'], 'task': task['id']}
                        if parent_id:
                            move_kwargs['parent'] = parent_id
                        service.tasks().move(**move_kwargs).execute()

                _run_sync()

                def after():
                    self.dialog_save_btn.remove_css_class('pulsing')
                    self.dialog_save_btn.set_sensitive(True)
                    self.close_task_dialog()
                    self.events, self.task_lists, self.calendars = load_data()
                    self._build_grid()
                    self._update_day_panel(self.selected_date)
                    self._build_task_lists()
                    return False
                GLib.idle_add(after)
            except Exception as e:
                print(f'[save task error] {e}', file=sys.stderr)
                def after_err():
                    self.dialog_save_btn.remove_css_class('pulsing')
                    self.dialog_save_btn.set_sensitive(True)
                    return False
                GLib.idle_add(after_err)

        threading.Thread(target=do_save, daemon=True).start()

    def _delete_task(self):
        task = self._dialog_task
        if not task:
            return

        self.dialog_delete_btn.set_sensitive(False)
        self.dialog_delete_btn.add_css_class('pulsing')

        def do_delete():
            try:
                from googleapiclient.discovery import build
                creds = _get_credentials(task.get('account_id'))
                if creds is None:
                    raise RuntimeError('Account session expired — please reconnect.')
                service = build('tasks', 'v1', credentials=creds)
                service.tasks().delete(tasklist=task['lid'], task=task['id']).execute()
                _run_sync()

                def after():
                    self.dialog_delete_btn.remove_css_class('pulsing')
                    self.dialog_delete_btn.set_sensitive(True)
                    self.close_task_dialog()
                    self.events, self.task_lists, self.calendars = load_data()
                    self._build_grid()
                    self._update_day_panel(self.selected_date)
                    self._build_task_lists()
                    return False
                GLib.idle_add(after)
            except Exception as e:
                print(f'[delete task error] {e}', file=sys.stderr)
                def after_err():
                    self.dialog_delete_btn.remove_css_class('pulsing')
                    self.dialog_delete_btn.set_sensitive(True)
                    return False
                GLib.idle_add(after_err)

        threading.Thread(target=do_delete, daemon=True).start()

    def _draw_refresh_icon(self, da, ctx, width, height):
        r, g, b = self._refresh_fg

        if not hasattr(self, '_refresh_layout'):
            self._refresh_layout = PangoCairo.create_layout(ctx)
            font_name = NERD_FONT.split(',')[0].strip()
            self._refresh_layout.set_font_description(
                Pango.FontDescription.from_string(f"{font_name} 12"))
            self._refresh_layout.set_text("\uf021")
            ink, _ = self._refresh_layout.get_pixel_extents()
            self._refresh_ink = ink
        else:
            PangoCairo.update_layout(ctx, self._refresh_layout)

        ink = self._refresh_ink
        x = (width - ink.width) / 2 - ink.x
        y = (height - ink.height) / 2 - ink.y

        if self._refresh_angle != 0.0:
            ctx.translate(width / 2, height / 2)
            ctx.rotate(self._refresh_angle)
            ctx.translate(-width / 2, -height / 2)

        ctx.set_source_rgba(r, g, b, 1.0)
        ctx.move_to(x, y)
        PangoCairo.show_layout(ctx, self._refresh_layout)

    def _on_refresh_clicked(self, _):
        self.refresh_btn.set_sensitive(False)

        def tick():
            self._refresh_angle += 0.15
            self._refresh_da.queue_draw()
            return not self.refresh_btn.get_sensitive()
        self._refresh_spin_timer = GLib.timeout_add(16, tick)

        def do_sync():
            _run_sync()
            def after():
                if self._refresh_spin_timer:
                    GLib.source_remove(self._refresh_spin_timer)
                    self._refresh_spin_timer = None
                self._refresh_angle = 0.0
                self._refresh_da.queue_draw()
                self.events, self.task_lists, self.calendars = load_data()
                self._build_grid()
                self._update_day_panel(self.selected_date)
                self._build_task_lists()
                self.refresh_btn.set_sensitive(True)
                return False
            GLib.idle_add(after)
        threading.Thread(target=do_sync, daemon=True).start()

    def _navigate(self, delta):
        self.month += delta
        if self.month < 1:
            self.month = 12
            self.year -= 1
        elif self.month > 12:
            self.month = 1
            self.year += 1
        self.month_label.set_markup(
            f"<b>{datetime.date(self.year, self.month, 1).strftime('%B %Y').upper()}</b>"
        )
        self._build_grid()

    def _apply_css(self):
        t = load_theme()
        fg = t['foreground']
        bg = t['background']
        accent = t['accent']
        red = '#ff5555'
        self._refresh_fg = hex_to_rgb_float(fg)

        css = f"""
      window {{
          background: transparent;
      }}
      .click-shield {{
          background: rgba(0, 0, 0, 0.01);
      }}
      .popup-bg {{
          background: {hex_to_rgba(bg, 0.92)};
          border-radius: 12px;
          border: 1px solid {hex_to_rgba(accent, 0.35)};
          padding: 10px;
      }}
      button {{
          background: transparent;
          border: 1px solid transparent;
          border-radius: 10px;
          color: {fg};
          font-size: 11px;
          font-weight: 500;
      }}
      button:hover {{
          background: rgba(255, 255, 255, 0.07);
      }}
      button:active {{
          background: rgba(255, 255, 255, 0.18);
          transition: background 50ms;
      }}
      button:focus,
      button:focus-visible {{
          outline: none;
          box-shadow: none;
      }}
      label {{
          color: {fg};
      }}
      .weekday {{
          color: {hex_to_rgba(fg, 0.4)};
          font-size: 11px;
      }}
      .other-month {{
          opacity: 0.2;
      }}
      .other-month:hover {{
          background: transparent;
      }}
      .weekend {{
          background: {hex_to_rgba(fg, 0.04)};
          border-radius: 10px;
      }}
      .weekend-label {{
          color: {hex_to_rgba(accent, 0.6)};
      }}
      .today {{
          background: {hex_to_rgba(accent, 0.5)};
          border-radius: 10px;
          font-weight: bold;
      }}
      .today:hover {{
          background: {hex_to_rgba(accent, 0.65)};
      }}
      .selected {{
          border: 1px solid {hex_to_rgba(accent, 0.8)};
          border-radius: 10px;
      }}
      .today.selected {{
          border: 1px solid {fg};
      }}
      .event-bar {{
          background: {hex_to_rgba(accent, 0.9)};
          border-radius: 2px;
          min-height: 2px;
      }}
      .today .event-bar {{
          background: {fg};
      }}
      .panel-divider {{
          background: {hex_to_rgba(accent, 0.2)};
          min-width: 1px;
          margin: 0 8px;
      }}
      .day-panel {{
          padding: 2px 4px 2px 0;
      }}
      .day-heading {{
          font-size: 11px;
          margin-bottom: 4px;
      }}
      .event-dot {{
          color: {hex_to_rgba(accent, 0.9)};
          font-size: 10px;
      }}
      .event-name {{
          font-size: 11px;
          color: {fg};
      }}
      .task-bar {{
          background: {hex_to_rgba(red, 0.9)};
          border-radius: 2px;
          min-height: 2px;
      }}
      .task-dot {{
          color: {hex_to_rgba(red, 0.9)};
          font-size: 10px;
      }}
      .done-dot {{
          color: {hex_to_rgba('#50fa7b', 0.9)};
          font-size: 10px;
      }}
      .done-toggle {{
          font-size: 10px;
          min-width: 18px;
          min-height: 18px;
          padding: 0;
          border-radius: 4px;
      }}
      .done-toggle-inactive {{
          border: 1px solid {hex_to_rgba(fg, 0.2)};
          color: transparent;
      }}
      .done-toggle-inactive:hover {{
          border-color: {hex_to_rgba('#50fa7b', 0.6)};
          color: {hex_to_rgba('#50fa7b', 0.6)};
      }}
      .done-toggle-active {{
          border: 1px solid {hex_to_rgba('#50fa7b', 0.6)};
          color: {hex_to_rgba('#50fa7b', 0.9)};
          background: {hex_to_rgba('#50fa7b', 0.15)};
      }}
      .no-events {{
          font-size: 11px;
          color: {hex_to_rgba(fg, 0.35)};
          font-style: italic;
      }}
      .add-btn {{
          background: {hex_to_rgba(accent, 0.15)};
          border: 1px solid {hex_to_rgba(accent, 0.35)};
          border-radius: 8px;
          color: {fg};
          font-size: 11px;
          padding: 4px 0;
          margin-top: 4px;
      }}
      .add-btn:hover {{
          background: {hex_to_rgba(accent, 0.28)};
      }}
      .refresh-btn {{
          background: {hex_to_rgba(accent, 0.15)};
          border: 1px solid {hex_to_rgba(accent, 0.35)};
          color: {fg};
          font-size: 15px;
          padding: 0;
      }}
      .refresh-btn:hover {{
          background: {hex_to_rgba(accent, 0.28)};
      }}
      .refresh-btn.active-toggle {{
          background: {hex_to_rgba(accent, 0.35)};
          border-color: {hex_to_rgba(accent, 0.8)};
      }}
      .task-entry {{
          background: rgba(255, 255, 255, 0.08);
          border: 1px solid rgba(255, 255, 255, 0.15);
          border-radius: 8px;
          color: {fg};
          font-size: 11px;
          padding: 4px 8px;
          margin-top: 2px;
      }}
      .task-entry:focus {{
          border-color: {hex_to_rgba(accent, 0.8)};
          background: rgba(255, 255, 255, 0.12);
      }}
      .add-btn.nerd {{
          font-family: "{NERD_FONT}";
          font-size: 13px;
          padding: 0;
      }}
      .add-btn.nerd label {{
          all: unset;
          font-family: "{NERD_FONT}";
          font-size: 13px;
          color: {fg};
          margin-left: -2px;
      }}
      .task-title-btn {{
          background: transparent;
          border: none;
          padding: 1px 3px;
          margin: 0;
          border-radius: 4px;
      }}
      .task-title-btn:hover {{
          background: rgba(255, 255, 255, 0.06);
      }}
      .subtask-glyph {{
          color: {hex_to_rgba(fg, 0.45)};
          font-size: 10px;
          margin-right: 2px;
      }}
      .subtask-badge {{
          font-size: 9px;
          color: {hex_to_rgba(accent, 0.9)};
          background: {hex_to_rgba(accent, 0.15)};
          border-radius: 4px;
          padding: 1px 4px;
      }}
      .subtasks-toggle-btn {{
          padding: 0 4px;
          min-width: 16px;
          min-height: 16px;
          border-radius: 4px;
      }}
      .subtasks-toggle-btn:hover {{
          background: rgba(255, 255, 255, 0.1);
      }}
      .task-row-btn {{
          font-size: 10px;
          min-width: 18px;
          min-height: 18px;
          padding: 0;
          border-radius: 4px;
          color: {hex_to_rgba(fg, 0.55)};
      }}
      .task-row-btn:hover {{
          color: {fg};
          background: rgba(255, 255, 255, 0.12);
      }}
      .task-row-btn.nerd label {{
          all: unset;
          font-family: "{NERD_FONT}";
          font-size: 10px;
          color: {hex_to_rgba(fg, 0.55)};
      }}
      .task-row-btn.nerd:hover label {{
          color: {fg};
      }}
      .dialog-scrim {{
          background: rgba(0, 0, 0, 0.6);
          border-radius: 12px;
      }}
      .dialog-card {{
          background: {hex_to_rgba(bg, 0.98)};
          border: 1px solid {hex_to_rgba(accent, 0.45)};
          border-radius: 12px;
          padding: 14px;
          margin: 10px;
      }}
      .dialog-title {{
          font-size: 13px;
          font-weight: bold;
          color: {fg};
      }}
      .dialog-close-btn {{
          color: {hex_to_rgba(fg, 0.6)};
          font-size: 12px;
          padding: 2px 6px;
          border-radius: 6px;
      }}
      .dialog-close-btn:hover {{
          color: {fg};
          background: rgba(255, 255, 255, 0.1);
      }}
      .dialog-label {{
          font-size: 11px;
          font-weight: 500;
          color: {hex_to_rgba(fg, 0.75)};
      }}
      .pill-btn {{
          background: {hex_to_rgba(accent, 0.12)};
          border: 1px solid {hex_to_rgba(accent, 0.25)};
          border-radius: 6px;
          color: {fg};
          font-size: 10px;
          padding: 2px 6px;
      }}
      .pill-btn:hover {{
          background: {hex_to_rgba(accent, 0.28)};
          border-color: {hex_to_rgba(accent, 0.5)};
      }}
      .task-notes-view {{
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(255, 255, 255, 0.15);
          border-radius: 8px;
          color: {fg};
          font-size: 11px;
          padding: 6px;
      }}
      .task-notes-view:focus {{
          border-color: {hex_to_rgba(accent, 0.8)};
          background: rgba(255, 255, 255, 0.08);
      }}
      .dialog-save-btn {{
          background: {hex_to_rgba(accent, 0.85)};
          border: 1px solid {accent};
          border-radius: 8px;
          color: #ffffff;
          font-weight: 600;
          font-size: 11px;
          padding: 4px 12px;
      }}
      .dialog-save-btn:hover {{
          background: {accent};
      }}
      .dialog-delete-btn {{
          background: {hex_to_rgba(red, 0.15)};
          border: 1px solid {hex_to_rgba(red, 0.4)};
          border-radius: 8px;
          color: {red};
          font-size: 11px;
          padding: 4px 10px;
      }}
      .dialog-delete-btn:hover {{
          background: {hex_to_rgba(red, 0.3)};
      }}
      .dialog-cancel-btn {{
          background: rgba(255, 255, 255, 0.08);
          border: 1px solid rgba(255, 255, 255, 0.15);
          border-radius: 8px;
          color: {fg};
          font-size: 11px;
          padding: 4px 10px;
      }}
      .dialog-cancel-btn:hover {{
          background: rgba(255, 255, 255, 0.15);
      }}
      dropdown {{
          background: rgba(255, 255, 255, 0.07);
          border: 1px solid rgba(255, 255, 255, 0.15);
          border-radius: 8px;
          color: {fg};
          font-size: 11px;
          padding: 2px 6px;
      }}
      dropdown:focus {{
          border-color: {hex_to_rgba(accent, 0.8)};
      }}
      @keyframes pulse {{
          0%, 100% {{ opacity: 1; }}
          50%       {{ opacity: 0.25; }}
      }}
      .pulsing {{
          animation: pulse 0.6s ease-in-out infinite;
      }}
      .setup-title {{
          font-size: 14px;
          font-weight: bold;
          color: {fg};
          margin-top: 8px;
          margin-bottom: 6px;
      }}
      .setup-msg {{
          font-size: 11px;
          color: {hex_to_rgba(fg, 0.6)};
          margin-bottom: 12px;
      }}
      """.encode()
        if not hasattr(self, '_css_provider'):
            self._css_provider = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(
                self.get_display(), self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        self._css_provider.load_from_data(css)


win = None

def on_activate(app):
    global win
    win = CalendarPopup(app)
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: win.toggle() or True)
    sync_in_background()
    GLib.timeout_add_seconds(SYNC_INTERVAL_SEC, sync_in_background)


def main():
    global win
    app = Gtk.Application(application_id="com.waybar.ycal")
    app.connect("activate", on_activate)
    try:
        app.run(None)
    finally:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)


if __name__ == '__main__':
    main()

