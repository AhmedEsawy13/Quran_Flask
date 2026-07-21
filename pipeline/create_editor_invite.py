#!/usr/bin/env python3
"""Create a mushaf-editor invite (hashed code → editor_invites).

Requires SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, EDITOR_SESSION_SECRET.
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
    p = argparse.ArgumentParser(description='Create a mushaf-editor invite code')
    p.add_argument('--name', required=True, help='Display name shown in the editor')
    p.add_argument('--role', choices=('editor', 'admin'), default='editor')
    p.add_argument('--code', default='', help='Plaintext code (generated if omitted)')
    args = p.parse_args()

    if not sb.is_configured():
        print('Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY first.', file=sys.stderr)
        return 1

    code = (args.code or '').strip() or secrets.token_urlsafe(12)
    code_hash = sb.hash_invite_code(code)
    row = sb.insert_invite(
        display_name=args.name.strip(),
        role=args.role,
        code_hash=code_hash,
    )
    print(f"Created invite id={row.get('id')} name={args.name!r} role={args.role}")
    print(f"Plaintext code (give once): {code}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
