#!/usr/bin/env python3
"""
CLI helper to add, list, or manage multiple Google Accounts for waybar-ycal / hypr-ycal.
"""

import os
import sys
import argparse
import subprocess

# Ensure we can import accounts and popup from the same directory
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from accounts import (
    load_accounts,
    save_accounts,
    add_account_interactive,
    reconnect_account,
    get_credentials_with_status,
    remove_account,
    toggle_account,
    rename_account,
    DEFAULT_CREDENTIALS_FILE,
)


def list_accounts():
    accounts = load_accounts()
    print("=" * 60)
    print("  Connected Google Accounts (hypr-ycal / waybar-ycal)")
    print("=" * 60)
    if not accounts:
        print("  No accounts connected yet.")
        print(f"  Run '{sys.argv[0]}' to add an account.")
        print("=" * 60)
        return

    for idx, a in enumerate(accounts, 1):
        if not a.get('enabled', True):
            status = "✕ DISABLED"
        else:
            creds, err_kind, _ = get_credentials_with_status(a)
            if creds:
                status = "✓ ENABLED "
            elif err_kind == 'auth_expired':
                status = "⚠ EXPIRED "
            else:
                status = "! ERROR   "
        color_dot = a.get('color', '#4285f4')
        print(f"  [{idx}] {status}  {a.get('name', 'Account'):<16} <{a.get('email')}>")
        print(f"      ID: {a.get('id')} | Color: {color_dot}")
        print(f"      Token: {a.get('token_file')}")
        if status.startswith("⚠"):
            print(f"      Action: run '{sys.argv[0]} --reconnect {a.get('id')}' or click Reconnect in UI")
        if a.get('credentials_file') != DEFAULT_CREDENTIALS_FILE:
            print(f"      Credentials: {a.get('credentials_file')}")
    print("=" * 60)


def trigger_sync_and_reload():
    print("[*] Triggering calendar and task sync across all accounts...")
    try:
        from popup import _run_sync
        _run_sync()
        print("[✓] Sync completed successfully.")
    except Exception as e:
        print(f"[!] Warning: sync encountered an issue: {e}")

    print("[*] Reloading hypr-ycal & waybar-ycal services...")
    # Send SIGUSR1 / SIGUSR2 if PID exists, or restart via systemctl
    try:
        res = subprocess.run(
            ['systemctl', '--user', 'restart', 'waybar-ycal-bg.service', 'waybar-ycal.service'],
            capture_output=True,
            text=True
        )
        if res.returncode == 0:
            print("[✓] Desktop services restarted and UI updated.")
        else:
            print(f"[*] Note: systemctl output: {res.stderr.strip() or res.stdout.strip()}")
    except Exception as e:
        print(f"[*] Note: could not restart systemd user service ({e})")


def main():
    parser = argparse.ArgumentParser(
        description="Add and manage multiple Google accounts for hypr-ycal / waybar-ycal"
    )
    parser.add_argument(
        '-n', '--name',
        help="Friendly name for the account (e.g. 'Company', 'Work', 'Personal')",
        default=None
    )
    parser.add_argument(
        '-c', '--credentials',
        help=f"Path to OAuth credentials JSON file (default: {DEFAULT_CREDENTIALS_FILE})",
        default=None
    )
    parser.add_argument(
        '-l', '--list',
        action='store_true',
        help="List all connected accounts and exit"
    )
    parser.add_argument(
        '-r', '--remove',
        metavar='ACCOUNT_ID',
        help="Remove an account by ID or email"
    )
    parser.add_argument(
        '-t', '--toggle',
        metavar='ACCOUNT_ID',
        help="Toggle enabled/disabled status of an account"
    )
    parser.add_argument(
        '--reconnect',
        metavar='ACCOUNT_ID',
        help="Re-authenticate an existing expired account (by ID or email)"
    )
    parser.add_argument(
        '--sync-only',
        action='store_true',
        help="Run sync now and reload services"
    )

    args = parser.parse_args()

    if args.list:
        list_accounts()
        return

    if args.sync_only:
        trigger_sync_and_reload()
        return

    if args.reconnect:
        try:
            acc = reconnect_account(args.reconnect)
            print(f"[✓] Reconnected {acc.get('name')} <{acc.get('email')}>!")
            trigger_sync_and_reload()
            list_accounts()
        except Exception as e:
            print(f"[✕] Reconnect failed: {e}")
            sys.exit(1)
        return

    if args.remove:
        if remove_account(args.remove):
            print(f"[✓] Successfully removed account '{args.remove}'.")
            trigger_sync_and_reload()
        else:
            print(f"[✕] Account '{args.remove}' not found.")
        return

    if args.toggle:
        if toggle_account(args.toggle):
            print(f"[✓] Toggled account '{args.toggle}'.")
            trigger_sync_and_reload()
        else:
            print(f"[✕] Account '{args.toggle}' not found.")
        return

    print("=" * 60)
    print("  Google Account Authentication (hypr-ycal / waybar-ycal)")
    print("=" * 60)

    cred_file = args.credentials
    if not cred_file:
        if not os.path.exists(DEFAULT_CREDENTIALS_FILE):
            print(f"[!] Default credentials file not found at: {DEFAULT_CREDENTIALS_FILE}")
            cred_file = input("Enter path to your Google Cloud client credentials.json: ").strip()
            cred_file = os.path.expanduser(cred_file)
        else:
            cred_file = DEFAULT_CREDENTIALS_FILE

    if not os.path.exists(cred_file):
        print(f"[✕] Error: Credentials file does not exist: {cred_file}")
        sys.exit(1)

    name = args.name
    if name is None:
        try:
            suggested = "Company" if load_accounts() else "Personal"
            user_input = input(f"Enter account label/name [default: {suggested}]: ").strip()
            name = user_input if user_input else suggested
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(0)

    print("\n[*] Starting OAuth authentication...")
    print("[*] A browser window will open shortly.")
    print("    -> Sign in with your desired Google account (Personal or Company).")
    print("    -> Grant permissions for Google Calendar (readonly) and Google Tasks.")
    print("-" * 60)

    try:
        acc = add_account_interactive(
            name=name,
            credentials_file=cred_file,
            prompt='select_account consent',
        )
        print("-" * 60)
        print(f"[✓] SUCCESS! Added account: {acc.get('name')} <{acc.get('email')}>")
        print(f"    Account ID: {acc.get('id')}")
        print(f"    Token saved to: {acc.get('token_file')}")
        print("=" * 60)

        trigger_sync_and_reload()
        list_accounts()

    except Exception as e:
        print(f"\n[✕] Authorization failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
