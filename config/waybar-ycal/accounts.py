#!/usr/bin/env python3
"""
Multi-account manager for waybar-ycal / hypr-ycal.
Handles Google OAuth 2.0 tokens and account settings.
"""

import os
import re
import sys
import json
import shutil
from typing import List, Dict, Optional, Tuple

CONFIG_DIR = os.path.expanduser('~/.config/waybar-ycal')
CACHE_DIR = os.path.expanduser('~/.cache/waybar-ycal')
ACCOUNTS_FILE = os.path.join(CONFIG_DIR, 'accounts.json')
TOKENS_DIR = os.path.join(CACHE_DIR, 'tokens')
DEFAULT_CREDENTIALS_FILE = os.path.join(CONFIG_DIR, 'credentials.json')
LEGACY_TOKEN_FILE = os.path.join(CACHE_DIR, 'token.json')

SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/tasks',
]

# Preset palette for account badges / chips
ACCOUNT_COLORS = [
    '#4285f4',  # Google Blue
    '#34a853',  # Google Green
    '#ea4335',  # Google Red
    '#fbbc05',  # Google Yellow
    '#ab47bc',  # Purple
    '#00acc1',  # Cyan
    '#ff7043',  # Coral
]


def ensure_dirs():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(TOKENS_DIR, exist_ok=True)


def sanitize_id(identifier: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9_]', '_', identifier.strip().lower())
    return re.sub(r'_+', '_', cleaned).strip('_')


def _migrate_legacy_token_if_needed() -> List[Dict]:
    """If accounts.json does not exist, migrate from legacy token.json."""
    if os.path.exists(ACCOUNTS_FILE):
        return []

    ensure_dirs()
    if not os.path.exists(LEGACY_TOKEN_FILE):
        return []

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(LEGACY_TOKEN_FILE, SCOPES)
        email = None
        try:
            service = build('calendar', 'v3', credentials=creds)
            primary = service.calendarList().get(calendarId='primary').execute()
            email = primary.get('id')
        except Exception as e:
            print(f"[accounts] Note: could not fetch email during migration ({e})", file=sys.stderr)

        if not email or '@' not in email:
            email = "personal@gmail.com"

        acc_id = sanitize_id(email)
        token_dest = os.path.join(TOKENS_DIR, f"{acc_id}.json")
        shutil.copy2(LEGACY_TOKEN_FILE, token_dest)

        accounts = [
            {
                "id": acc_id,
                "email": email,
                "name": "Personal",
                "token_file": token_dest,
                "credentials_file": DEFAULT_CREDENTIALS_FILE,
                "enabled": True,
                "color": ACCOUNT_COLORS[0],
            }
        ]
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)
        print(f"[accounts] Successfully migrated legacy account '{email}' to {ACCOUNTS_FILE}")
        return accounts
    except Exception as e:
        print(f"[accounts] Migration failed: {e}", file=sys.stderr)
        return []


def load_accounts() -> List[Dict]:
    """Load all configured Google accounts. Performs automatic migration if needed."""
    ensure_dirs()
    if not os.path.exists(ACCOUNTS_FILE):
        migrated = _migrate_legacy_token_if_needed()
        if migrated:
            return migrated
        return []

    try:
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
        if isinstance(accounts, list):
            return accounts
    except Exception as e:
        print(f"[accounts] Error reading {ACCOUNTS_FILE}: {e}", file=sys.stderr)
    return []


def save_accounts(accounts: List[Dict]):
    """Persist accounts list to accounts.json."""
    ensure_dirs()
    tmp_path = ACCOUNTS_FILE + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, ACCOUNTS_FILE)


def get_account(account_id_or_email: str) -> Optional[Dict]:
    """Find account by ID or email."""
    for acc in load_accounts():
        if acc.get('id') == account_id_or_email or acc.get('email') == account_id_or_email:
            return acc
    return None


def get_credentials_for_account(account_or_id) -> Optional[object]:
    """
    Get valid google.oauth2.credentials.Credentials for a given account dict or id.
    Refreshes expired credentials if refresh_token is available.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    account = account_or_id if isinstance(account_or_id, dict) else get_account(account_or_id)
    if not account:
        return None

    token_file = account.get('token_file')
    if not token_file or not os.path.exists(token_file):
        return None

    try:
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(token_file, 'w', encoding='utf-8') as f:
                    f.write(creds.to_json())
                # Also keep legacy token.json in sync if this is the first / personal account
                accounts = load_accounts()
                if accounts and accounts[0].get('id') == account.get('id'):
                    try:
                        with open(LEGACY_TOKEN_FILE, 'w', encoding='utf-8') as lf:
                            lf.write(creds.to_json())
                    except Exception:
                        pass
            else:
                print(f"[accounts] Credentials for {account.get('email')} are invalid and cannot be refreshed.", file=sys.stderr)
                return None
        return creds
    except Exception as e:
        print(f"[accounts] Error loading credentials for {account.get('email', '?')}: {e}", file=sys.stderr)
        return None


def get_all_active_credentials() -> List[Tuple[Dict, object]]:
    """Returns list of (account, credentials) tuples for all enabled accounts."""
    results = []
    for acc in load_accounts():
        if not acc.get('enabled', True):
            continue
        creds = get_credentials_for_account(acc)
        if creds:
            results.append((acc, creds))
    return results


def add_account_interactive(
    name: Optional[str] = None,
    credentials_file: Optional[str] = None,
    port: int = 0,
    open_browser: bool = True,
    prompt: str = 'select_account',
) -> Optional[Dict]:
    """
    Run an interactive OAuth authorization flow in the browser.
    prompt='select_account' ensures Google asks which account to log into
    (crucial for switching from personal to company account).
    """
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    cred_file = credentials_file or DEFAULT_CREDENTIALS_FILE
    if not os.path.exists(cred_file):
        raise FileNotFoundError(
            f"Google Cloud OAuth credentials file not found: {cred_file}\n"
            f"Please place your client secrets file at {DEFAULT_CREDENTIALS_FILE} "
            f"or specify a custom path."
        )

    ensure_dirs()
    flow = InstalledAppFlow.from_client_secrets_file(cred_file, SCOPES)
    creds = flow.run_local_server(port=port, prompt=prompt, open_browser=open_browser)

    # Detect primary email address
    service = build('calendar', 'v3', credentials=creds)
    primary = service.calendarList().get(calendarId='primary').execute()
    email = primary.get('id')
    if not email or '@' not in email:
        email = f"user_{sanitize_id(primary.get('summary', 'account'))}@gmail.com"

    acc_id = sanitize_id(email)
    token_file = os.path.join(TOKENS_DIR, f"{acc_id}.json")
    with open(token_file, 'w', encoding='utf-8') as f:
        f.write(creds.to_json())

    # Determine friendly name
    accounts = load_accounts()
    if not name:
        domain = email.split('@')[-1].lower() if '@' in email else ''
        if domain == 'gmail.com':
            name = "Personal" if not accounts else f"Google ({email.split('@')[0]})"
        else:
            org = domain.split('.')[0].capitalize()
            name = f"{org} (Company)"

    # Pick an account color not yet taken if possible
    used_colors = {a.get('color') for a in accounts}
    avail_colors = [c for c in ACCOUNT_COLORS if c not in used_colors]
    chosen_color = avail_colors[0] if avail_colors else ACCOUNT_COLORS[len(accounts) % len(ACCOUNT_COLORS)]

    account_entry = {
        "id": acc_id,
        "email": email,
        "name": name,
        "token_file": token_file,
        "credentials_file": cred_file,
        "enabled": True,
        "color": chosen_color,
    }

    # If updating an existing account, replace; otherwise append
    replaced = False
    for i, a in enumerate(accounts):
        if a.get('id') == acc_id or a.get('email') == email:
            accounts[i] = account_entry
            replaced = True
            break
    if not replaced:
        accounts.append(account_entry)

    save_accounts(accounts)

    # Update legacy token.json if this is the only or primary account
    if len(accounts) == 1:
        try:
            shutil.copy2(token_file, LEGACY_TOKEN_FILE)
        except Exception:
            pass

    return account_entry


def remove_account(account_id: str) -> bool:
    """Remove an account by ID and delete its token file."""
    accounts = load_accounts()
    removed = None
    remaining = []
    for a in accounts:
        if a.get('id') == account_id or a.get('email') == account_id:
            removed = a
        else:
            remaining.append(a)

    if removed:
        save_accounts(remaining)
        token_file = removed.get('token_file')
        if token_file and os.path.exists(token_file):
            try:
                os.remove(token_file)
            except Exception:
                pass
        return True
    return False


def toggle_account(account_id: str, enabled: Optional[bool] = None) -> bool:
    """Toggle or set the enabled status of an account."""
    accounts = load_accounts()
    found = False
    for a in accounts:
        if a.get('id') == account_id or a.get('email') == account_id:
            if enabled is None:
                a['enabled'] = not a.get('enabled', True)
            else:
                a['enabled'] = bool(enabled)
            found = True
            break
    if found:
        save_accounts(accounts)
    return found


def rename_account(account_id: str, new_name: str) -> bool:
    """Rename display name of an account."""
    accounts = load_accounts()
    found = False
    for a in accounts:
        if a.get('id') == account_id or a.get('email') == account_id:
            a['name'] = new_name.strip()
            found = True
            break
    if found:
        save_accounts(accounts)
    return found


if __name__ == '__main__':
    # CLI check / test
    print("Testing accounts.py...")
    accs = load_accounts()
    print(f"Loaded {len(accs)} account(s):")
    for a in accs:
        status = "ENABLED" if a.get('enabled', True) else "DISABLED"
        print(f" - [{status}] {a.get('name')} <{a.get('email')}> (id: {a.get('id')})")
