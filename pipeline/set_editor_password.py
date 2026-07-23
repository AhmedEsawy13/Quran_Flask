#!/usr/bin/env python3
"""Set username + password on an existing editor_invites row.

Use after running pipeline/supabase_editor_password_auth.sql so legacy
invite-only accounts can log in with username/password.
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import supabase_editor as sb  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description='Set editor account username/password')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--id', help='editor_invites.id')
    g.add_argument('--name', help='Match display_name exactly')
    p.add_argument('--username', required=True, help='Login username')
    p.add_argument('--password', default='', help='Password (generated if omitted)')
    args = p.parse_args()

    if not sb.is_configured():
        print('Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY first.', file=sys.stderr)
        return 1

    username = sb.validate_username(args.username)
    if not username:
        print('Invalid username (3–32 chars: letters, digits, . _ -).', file=sys.stderr)
        return 1

    password = (args.password or '').strip() or secrets.token_urlsafe(10)
    if not sb.validate_password(password):
        print(f'Password too short (min {sb.MIN_PASSWORD_LEN}).', file=sys.stderr)
        return 1

    try:
        row = sb.set_invite_credentials(
            invite_id=(args.id or '').strip() or None,
            display_name=(args.name or '').strip() or None,
            username=username,
            password_hash=sb.hash_password(password),
        )
    except sb.SupabaseEditorError as e:
        print(f'Update failed: {e}', file=sys.stderr)
        print('Did you run pipeline/supabase_editor_password_auth.sql?', file=sys.stderr)
        return 1

    if not row:
        print('No matching invite found.', file=sys.stderr)
        return 1

    print(f"Updated id={row.get('id')} name={row.get('display_name')!r} "
          f"username={row.get('username')!r}")
    print(f'Password (give once / store now): {password}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
