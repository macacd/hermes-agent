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
    
    # Google Workspace OAuth credentials
    google_client_id = _nested(secret, ["integrations", "google", "primary", "clientId"])
    if google_client_id:
        updates["GOOGLE_CLIENT_ID"] = google_client_id
    google_client_secret = _nested(secret, ["integrations", "google", "primary", "clientSecret"])
    if google_client_secret:
        updates["GOOGLE_CLIENT_SECRET"] = google_client_secret
    google_refresh_token = _nested(secret, ["integrations", "google", "primary", "refreshToken"])
    if google_refresh_token:
        updates["GOOGLE_REFRESH_TOKEN"] = google_refresh_token
    google_api_key = _nested(secret, ["integrations", "google", "primary", "generativeApiKey"])
    if google_api_key:
        updates["GOOGLE_API_KEY"] = google_api_key
    
    # Gmail Bridge configuration
    gmail_project_id = _nested(secret, ["gmail", "bridge", "pubsub_project_id"])
    if gmail_project_id:
        updates["GOOGLE_PROJECT_ID"] = gmail_project_id
    gmail_subscription = _nested(secret, ["gmail", "bridge", "subscription_name"])
    if gmail_subscription:
        updates["GMAIL_SUBSCRIPTION"] = gmail_subscription
    gmail_telegram_target = _nested(secret, ["gmail", "bridge", "telegram_target"])
    if gmail_telegram_target:
        updates["GMAIL_TELEGRAM_TARGET"] = gmail_telegram_target
    else:
        # Default Gmail Bridge to main user chat (same as Hermes Gateway)
        updates["GMAIL_TELEGRAM_TARGET"] = "882558885"
    gmail_telegram_thread = _nested(secret, ["gmail", "bridge", "telegram_thread_id"])
    if gmail_telegram_thread:
        updates["GMAIL_TELEGRAM_THREAD"] = gmail_telegram_thread
    gmail_max_messages = _nested(secret, ["gmail", "bridge", "max_messages_per_pull"])
    if gmail_max_messages:
        updates["GMAIL_MAX_MESSAGES"] = str(gmail_max_messages)
    
    # Gmail Bridge OAuth credentials (específicas para Watch API)
    gmail_client_id = _nested(secret, ["gmail", "bridge", "credentials_json", "installed", "client_id"])
    if gmail_client_id:
        updates["GMAIL_CLIENT_ID"] = gmail_client_id
    gmail_client_secret = _nested(secret, ["gmail", "bridge", "credentials_json", "installed", "client_secret"])
    if gmail_client_secret:
        updates["GMAIL_CLIENT_SECRET"] = gmail_client_secret
    gmail_refresh_token = _nested(secret, ["gmail", "bridge", "token_json", "refresh_token"])
    if gmail_refresh_token:
        updates["GMAIL_REFRESH_TOKEN"] = gmail_refresh_token

    # GitHub integration credentials
    github_pat = _nested(secret, ["github", "pat_main"])
    if github_pat:
        updates["GITHUB_TOKEN"] = github_pat
    
    # Scripture Service configuration
    scripture_target = _nested(secret, ["scripture", "telegram_target"])
    if scripture_target:
        updates["SCRIPTURE_TELEGRAM_TARGET"] = scripture_target
    else:
        # Default to main user chat (where user interacts with Hermes Gateway)
        # Use TELEGRAM_ALLOWED_USERS as the target for Scripture delivery
        updates["SCRIPTURE_TELEGRAM_TARGET"] = "882558885"  # Main user chat
    
    github_client_id = _nested(secret, ["integrations", "github", "primary", "clientId"])
    if github_client_id:
        updates["GITHUB_CLIENT_ID"] = github_client_id
    github_client_secret = _nested(secret, ["integrations", "github", "primary", "clientSecret"])
    if github_client_secret:
        updates["GITHUB_CLIENT_SECRET"] = github_client_secret
    
    # ClickUp integration credentials
    clickup_api_key = _nested(secret, ["integrations", "clickup", "apiKey"])
    if clickup_api_key:
        updates["CLICKUP_API_KEY"] = clickup_api_key
    clickup_team_id = _nested(secret, ["integrations", "clickup", "teamId"])
    if clickup_team_id:
        updates["CLICKUP_TEAM_ID"] = clickup_team_id
    
    # Calendar service Telegram target (personal chat)
    calendar_target = _nested(secret, ["calendar", "telegram_target"])
    if calendar_target:
        updates["CALENDAR_TELEGRAM_TARGET"] = calendar_target
    else:
        # Default to personal chat
        updates["CALENDAR_TELEGRAM_TARGET"] = "882558885"

    if not updates:
        print("sync_secrets: no updates found; skipping")
        return

    env_path = Path.home() / ".hermes" / ".env"
    _merge_env(env_path, updates)
    print("sync_secrets: updated", ", ".join(sorted(updates)))


if __name__ == "__main__":
    main()
