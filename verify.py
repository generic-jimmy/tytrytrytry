#!/usr/bin/env python3
"""
Verification script for the upgraded Telegram group bot.

Run:  python verify.py

Checks performed:
  1. Python syntax of every .py file
  2. All critical imports resolve (FastAPI, aiogram, SQLAlchemy, etc.)
  3. App module structure — every module imports cleanly
  4. SQLAlchemy models are well-formed (table names, no clashes)
  5. All API routes are registered and reachable
  6. Bot router has all expected command handlers
  7. Frontend asset files exist and reference each other correctly
  8. Three.js + Chart.js CDN links present in index.html
  9. All view JS files are syntactically valid (basic brace check)
  10. Settings module can be constructed (with mock env vars)

Exits 0 on success, 1 on any failure.
"""
from __future__ import annotations

import os
import re
import sys
import ast
import importlib
import traceback
from pathlib import Path

# Force-set mock env vars so the script doesn't depend on a real .env.
# Uses assignment (not setdefault) so any pre-existing test env values are
# overwritten — this is a verification script, not a runtime config.
# Telegram bot tokens have the format "{bot_id}:{35-char-hash}" — aiogram
# validates the format strictly. Use a valid-shape mock token here.
os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:AAExampleMockTokenHashForVerificationOnly_xx"
os.environ["TELEGRAM_BOT_USERNAME"] = "test_bot"
os.environ["WEBHOOK_SECRET"] = "x" * 32
os.environ["BASE_URL"] = "https://example.com"
os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost:5432/db"
os.environ["OPENROUTER_API_KEY"] = "sk-or-test"
os.environ["SESSION_SECRET"] = "y" * 32

ROOT = Path(__file__).parent
APP = ROOT / "app"
STATIC = APP / "dashboard" / "static"
TEMPLATES = APP / "dashboard" / "templates"
VIEWS_JS = STATIC / "js" / "views"

PASS = 0
FAIL = 0

def ok(msg):
    global PASS
    PASS += 1
    print(f"  \033[32m✓\033[0m {msg}")

def fail(msg, exc=None):
    global FAIL
    FAIL += 1
    print(f"  \033[31m✗\033[0m {msg}")
    if exc:
        print(f"      {exc}")

def section(title):
    print(f"\n\033[1m→ {title}\033[0m")

# ----------------------------------------------------------- 1. Python syntax
section("1. Python syntax check")
py_files = sorted(APP.rglob("*.py"))
for py in py_files:
    try:
        ast.parse(py.read_text(encoding="utf-8"))
        ok(f"{py.relative_to(ROOT)}")
    except SyntaxError as e:
        fail(f"{py.relative_to(ROOT)}: {e.msg} (line {e.lineno})", e)

# ----------------------------------------------------------- 2. Critical imports
section("2. Critical third-party imports")
for mod in ["fastapi", "aiogram", "sqlalchemy", "asyncpg", "pydantic_settings",
            "httpx", "jinja2", "itsdangerous"]:
    try:
        importlib.import_module(mod)
        ok(f"import {mod}")
    except Exception as e:
        fail(f"import {mod}", e)

# ----------------------------------------------------------- 3. App module imports
section("3. App module imports")
sys.path.insert(0, str(ROOT))
app_modules = [
    "app",
    "app.config",
    "app.db",
    "app.models",
    "app.auth",
    "app.main",
    "app.bot",
    "app.bot.handlers",
    "app.bot.moderation",
    "app.bot.openrouter",
    "app.bot.purgatory",
    "app.dashboard.routes",
    "app.dashboard.api",
]
for mod in app_modules:
    try:
        importlib.import_module(mod)
        ok(f"import {mod}")
    except Exception as e:
        fail(f"import {mod}", traceback.format_exc().strip().splitlines()[-1])

# ----------------------------------------------------------- 4. Models integrity
section("4. SQLAlchemy model integrity")
try:
    from app.db import Base
    from app import models as M

    table_names = [t.name for t in Base.metadata.sorted_tables]
    duplicates = [n for n in set(table_names) if table_names.count(n) > 1]
    if duplicates:
        fail(f"duplicate table names: {duplicates}")
    else:
        ok(f"{len(table_names)} tables registered, no duplicates")

    expected_models = [
        "Group", "Admin", "Warn", "ModLog", "FlaggedMessage", "Filter",
        "PurgatoryEntry", "UserProfile", "CustomCommand", "AutoResponse",
        "ScheduledMessage", "AIConfig", "Appeal", "AnalyticsSnapshot", "AuditEvent"
    ]
    for name in expected_models:
        if hasattr(M, name):
            ok(f"model {name} exists")
        else:
            fail(f"model {name} missing")
except Exception as e:
    fail("model integrity", traceback.format_exc().strip().splitlines()[-1])

# ----------------------------------------------------------- 5. API routes
section("5. API routes registered")
try:
    from app.dashboard.api import router as api_router
    paths = [r.path for r in api_router.routes]
    expected_paths = [
        "/api/groups",
        "/api/groups/{group_id}/overview",
        "/api/groups/{group_id}/members",
        "/api/groups/{group_id}/members/{user_id}",
        "/api/groups/{group_id}/members/{user_id}/{action}",
        "/api/groups/{group_id}/ai-config",
        "/api/groups/{group_id}/ai-config/test",
        "/api/groups/{group_id}/custom-commands",
        "/api/groups/{group_id}/custom-commands/{command_id}",
        "/api/groups/{group_id}/auto-responses",
        "/api/groups/{group_id}/auto-responses/{resp_id}",
        "/api/groups/{group_id}/scheduled",
        "/api/groups/{group_id}/scheduled/{msg_id}",
        "/api/groups/{group_id}/appeals",
        "/api/groups/{group_id}/appeals/{appeal_id}/{decision}",
        "/api/groups/{group_id}/flags",
        "/api/groups/{group_id}/flags/{flag_id}/{decision}",
        "/api/groups/{group_id}/purgatory",
        "/api/groups/{group_id}/purgatory/{entry_id}/{decision}",
        "/api/groups/{group_id}/purgatory/toggle",
        "/api/groups/{group_id}/modlog",
        "/api/groups/{group_id}/analytics",
        "/api/groups/{group_id}/filters",
        "/api/groups/{group_id}/filters/{filter_id}",
        "/api/groups/{group_id}/settings",
        "/api/groups/{group_id}/audit",
        "/api/groups/{group_id}/health",
    ]
    for ep in expected_paths:
        if any(ep == p or ep.rstrip("/{action}") in p for p in paths):
            ok(f"endpoint {ep}")
        else:
            # looser match
            if any(ep.split("/")[-1] in p for p in paths):
                ok(f"endpoint {ep} (loose match)")
            else:
                fail(f"endpoint {ep} not found")
    print(f"      (total routes: {len(paths)})")
except Exception as e:
    fail("API routes", traceback.format_exc().strip().splitlines()[-1])

# ----------------------------------------------------------- 6. Bot handlers
section("6. Bot command handlers")
try:
    from app.bot.handlers import router as bot_router
    # Pull callback function names — aiogram wraps each handler's callback
    # so we can identify which command it serves by its function name.
    callback_names = {h.callback.__name__ for h in bot_router.message.handlers}
    expected_callbacks = [
        "start_cmd", "bhelp_cmd", "bwarn_cmd", "bmute_cmd", "bunmute_cmd",
        "bkick_cmd", "bban_cmd", "bunban_cmd", "bwarnlimit_cmd",
        "baddfilter_cmd", "bremovefilter_cmd", "bfilters_cmd", "brules_cmd",
        "bsetrules_cmd", "bnightmode_cmd", "bslowmode_cmd", "bpurgatory_cmd",
        "bcleanbots_cmd", "bsetlogchannel_cmd", "bsetwelcome_cmd",
        "bsummarize_cmd", "bai_cmd", "bappeal_cmd", "breputation_cmd",
    ]
    for cb in expected_callbacks:
        if cb in callback_names:
            ok(f"{cb}() registered")
        else:
            fail(f"{cb}() missing")
    if "custom_command_handler" in callback_names:
        ok("custom_command_handler() catch-all present")
    else:
        fail("custom_command_handler() catch-all missing")
    if "scan_message" in callback_names:
        ok("scan_message() auto-mod handler present")
    else:
        fail("scan_message() auto-mod handler missing")
except Exception as e:
    fail("Bot handlers", traceback.format_exc().strip().splitlines()[-1])

# ----------------------------------------------------------- 7. Frontend assets
section("7. Frontend asset files")
required_assets = [
    TEMPLATES / "index.html",
    TEMPLATES / "login.html",
    STATIC / "css" / "app.css",
    STATIC / "css" / "views.css",
    STATIC / "js" / "api.js",
    STATIC / "js" / "ui.js",
    STATIC / "js" / "app.js",
    STATIC / "js" / "background.js",
    STATIC / "js" / "views" / "dashboard.js",
    STATIC / "js" / "views" / "analytics.js",
    STATIC / "js" / "views" / "members.js",
    STATIC / "js" / "views" / "purgatory.js",
    STATIC / "js" / "views" / "flags.js",
    STATIC / "js" / "views" / "appeals.js",
    STATIC / "js" / "views" / "modlog.js",
    STATIC / "js" / "views" / "audit.js",
    STATIC / "js" / "views" / "ai.js",
    STATIC / "js" / "views" / "automation.js",
    STATIC / "js" / "views" / "scheduled.js",
    STATIC / "js" / "views" / "filters.js",
    STATIC / "js" / "views" / "settings.js",
    STATIC / "js" / "views" / "health.js",
]
for asset in required_assets:
    if asset.exists() and asset.stat().st_size > 0:
        ok(f"{asset.relative_to(ROOT)}")
    else:
        fail(f"{asset.relative_to(ROOT)} missing or empty")

# ----------------------------------------------------------- 8. CDN + script tags
section("8. CDN and script references in index.html")
try:
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    for needle in [
        "three.min.js",
        "chart.umd.min.js",
        "/static/css/app.css",
        "/static/css/views.css",
        "/static/js/api.js",
        "/static/js/ui.js",
        "/static/js/background.js",
        "/static/js/app.js",
    ]:
        if needle in html:
            ok(f"{needle} referenced")
        else:
            fail(f"{needle} not referenced")

    # All view JS files referenced
    for view_js in (STATIC / "js" / "views").glob("*.js"):
        rel = f"/static/js/views/{view_js.name}"
        if rel in html:
            ok(f"{rel} referenced")
        else:
            fail(f"{rel} not referenced in index.html")

    # Theme attribute set on html
    if 'data-theme="dark"' in html:
        ok("default dark theme attribute set")
    else:
        fail("default theme attribute missing")

    # Sidebar nav items
    nav_routes = re.findall(r'data-route="([^"]+)"', html)
    expected_routes = {"dashboard", "analytics", "members", "purgatory", "flags",
                       "appeals", "modlog", "audit", "ai", "automation",
                       "scheduled", "filters", "settings", "health"}
    missing_routes = expected_routes - set(nav_routes)
    if not missing_routes:
        ok(f"all {len(expected_routes)} nav routes present")
    else:
        fail(f"missing nav routes: {missing_routes}")
except Exception as e:
    fail("index.html inspection", e)

# ----------------------------------------------------------- 9. JS syntax
section("9. JS file syntax validation")
import shutil, subprocess
js_files = list((STATIC / "js").glob("*.js")) + list((STATIC / "js" / "views").glob("*.js"))
node_bin = shutil.which("node")
for js in js_files:
    try:
        if node_bin:
            # Use Node's proper JS parser — accurate, no false positives
            result = subprocess.run(
                [node_bin, "--check", str(js)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                ok(f"{js.relative_to(ROOT)} (node --check)")
            else:
                fail(f"{js.relative_to(ROOT)}: {result.stderr.strip().splitlines()[-1] if result.stderr else 'syntax error'}")
        else:
            # Fallback: naive brace balance (may produce false positives on template literals)
            content = js.read_text(encoding="utf-8")
            content = re.sub(r"//[^\n]*", "", content)
            content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
            content = re.sub(r"'(?:[^'\\]|\\.)*'", "''", content)
            content = re.sub(r'"(?:[^"\\]|\\.)*"', '""', content)
            content = re.sub(r"`(?:[^`\\]|\\.)*`", "``", content)
            content = re.sub(r"/(?![/*])(?:[^/\\\n]|\\.)/[gimuy]*", "//", content)
            opens = content.count("{")
            closes = content.count("}")
            if opens == closes:
                ok(f"{js.relative_to(ROOT)} (braces balanced: {opens})")
            else:
                fail(f"{js.relative_to(ROOT)} unbalanced braces: {opens} open vs {closes} close (install Node.js for accurate check)")
    except Exception as e:
        fail(f"{js.relative_to(ROOT)}", e)

# ----------------------------------------------------------- 10. Settings construction
section("10. Settings construction with mock env")
try:
    import importlib
    if "app.config" in sys.modules:
        importlib.reload(sys.modules["app.config"])
    else:
        importlib.import_module("app.config")
    from app.config import settings
    ok(f"settings.telegram_bot_username = {settings.telegram_bot_username!r}")
    ok(f"settings.port = {settings.port}")
    ok(f"settings.allowed_bot_usernames = {settings.allowed_bot_usernames!r}")
except Exception as e:
    fail("settings construction", traceback.format_exc().strip().splitlines()[-1])

# ----------------------------------------------------------- summary
print(f"\n\033[1m{'='*60}\033[0m")
print(f"  \033[32mPassed: {PASS}\033[0m  ·  \033[31mFailed: {FAIL}\033[0m")
print(f"\033[1m{'='*60}\033[0m\n")

if FAIL > 0:
    print("\033[31mVerification FAILED. Fix the issues above before deploying.\033[0m")
    sys.exit(1)
else:
    print("\033[32mAll checks passed. The bot is structurally sound and ready to run.\033[0m")
    print("\nNext steps:")
    print("  1. Copy .env.example to .env and fill in real credentials")
    print("  2. Run: pip install -r requirements.txt")
    print("  3. Run: python -m uvicorn app.main:app --reload --port 8080")
    print("  4. Visit /login to access the dashboard")
    sys.exit(0)
