#!/usr/bin/env python3
"""Sync Hermes secrets from AWS Secrets Manager into ~/.hermes/.env."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _nested(data: dict, path: list[str]) -> str | None:
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur if isinstance(cur, str) else None


def _merge_env(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text().splitlines() if path.exists() else []
    new_lines: list[str] = []
    touched: set[str] = set()
    for line in existing:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key, _, _ = line.partition("=")
        key = key.strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            touched.add(key)
        else:
            new_lines.append(line)
    for key, value in updates.items():
        if key not in touched:
            new_lines.append(f"{key}={value}")
    path.write_text("\n".join(new_lines).rstrip() + "\n")


def main() -> None:
    secret_id = os.getenv("HERMES_SECRET_ID", "hermes/prod")
    aws_cmd = os.getenv("AWS_CLI", "aws")
    result = subprocess.run(
        [aws_cmd, "secretsmanager", "get-secret-value", "--secret-id", secret_id],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    secret = json.loads(payload.get("SecretString", "{}"))

    updates: dict[str, str] = {}
    if "OPENCODE_ZEN_API_KEY" in secret:
        updates["OPENCODE_ZEN_API_KEY"] = secret["OPENCODE_ZEN_API_KEY"]
    openrouter_key = _nested(secret, ["models", "openrouter", "apiKey"])
    if openrouter_key:
        updates["OPENROUTER_API_KEY"] = openrouter_key
    telegram_token = _nested(secret, ["channels", "telegram", "botToken"])
    if telegram_token:
        updates["TELEGRAM_BOT_TOKEN"] = telegram_token

    if not updates:
        print("sync_secrets: no updates found; skipping")
        return

    env_path = Path.home() / ".hermes" / ".env"
    _merge_env(env_path, updates)
    print("sync_secrets: updated", ", ".join(sorted(updates)))


if __name__ == "__main__":
    main()
