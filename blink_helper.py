#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["blinkpy==0.25.9"]
# ///
"""Local JSON bridge between Omarchy's QML shell and BlinkPy."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from aiohttp import ClientSession
from blinkpy.auth import Auth, BlinkTwoFARequiredError
from blinkpy.blinkpy import Blink

STATE_DIR = (
    Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    / "omarchy-blink"
)
CREDENTIALS = STATE_DIR / "credentials.json"
CACHE = STATE_DIR / "status.json"
THUMBNAILS = STATE_DIR / "thumbnails"


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def ensure_state() -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    THUMBNAILS.mkdir(mode=0o700, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    os.chmod(THUMBNAILS, 0o700)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def write_private(path: Path, payload: dict[str, Any]) -> None:
    ensure_state()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def sanitized_login(auth: Auth) -> dict[str, Any]:
    data = dict(auth.login_attributes)
    data.pop("password", None)
    return {key: value for key, value in data.items() if value is not None}


async def make_blink(data: dict[str, Any]) -> tuple[Blink, ClientSession]:
    session = ClientSession()
    blink = Blink(refresh_rate=60, session=session)
    blink.auth = Auth(data, no_prompt=True, session=session)
    return blink, session


def camera_payload(name: str, camera: Any) -> dict[str, Any]:
    attributes = camera.attributes
    return {
        "name": name,
        "armed": bool(attributes.get("arm", False)),
        "motion": bool(attributes.get("motion_detected", False)),
        "battery": attributes.get("battery") or "unknown",
        "batteryLevel": attributes.get("battery_level"),
        "temperatureC": attributes.get("temperature_c"),
        "wifi": attributes.get("wifi_strength"),
        "thumbnail": "",
    }


async def collect_status(blink: Blink) -> dict[str, Any]:
    cameras = [camera_payload(name, camera) for name, camera in blink.cameras.items()]
    systems = [
        {"name": name, "armed": bool(module.arm), "online": bool(module.available)}
        for name, module in blink.sync.items()
    ]
    payload = {
        "ok": True,
        "connected": True,
        "armed": any(system["armed"] for system in systems),
        "systems": systems,
        "cameras": cameras,
    }
    write_private(CACHE, payload)
    return payload


async def status() -> int:
    data = read_json(CREDENTIALS)
    if not data:
        cached = read_json(CACHE)
        emit(
            cached
            if cached
            else {"ok": True, "connected": False, "systems": [], "cameras": []}
        )
        return 0
    blink, session = await make_blink(data)
    try:
        if not await blink.start():
            raise RuntimeError("Blink rejected the saved session")
        write_private(CREDENTIALS, sanitized_login(blink.auth))
        emit(await collect_status(blink))
        return 0
    except Exception as error:  # noqa: BLE001 - BlinkPy leaks transport exceptions.
        cached = read_json(CACHE)
        emit(
            {
                **cached,
                "ok": False,
                "connected": bool(cached),
                "error": str(error) or type(error).__name__,
            }
        )
        return 1
    finally:
        await session.close()


async def login() -> int:
    ensure_state()
    try:
        request = json.loads(sys.stdin.readline())
        username = str(request.get("username", "")).strip()
        password = str(request.get("password", ""))
        if not username or not password:
            raise ValueError("Email and password are required")
    except (json.JSONDecodeError, ValueError) as error:
        emit({"event": "error", "error": str(error)})
        return 2

    blink, session = await make_blink({"username": username, "password": password})
    try:
        try:
            ready = await blink.start()
        except BlinkTwoFARequiredError:
            emit({"event": "needs_2fa"})
            line = sys.stdin.readline()
            if not line:
                raise RuntimeError("2FA login was cancelled")
            code = str(json.loads(line).get("code", "")).strip()
            if not code or not await blink.send_2fa_code(code):
                raise RuntimeError("That 2FA code was not accepted")
            ready = True
        if not ready:
            raise RuntimeError("Blink login failed; check your email and password")
        write_private(CREDENTIALS, sanitized_login(blink.auth))
        payload = await collect_status(blink)
        emit({"event": "connected", "status": payload})
        return 0
    except Exception as error:  # noqa: BLE001 - convert library errors to JSON.
        emit({"event": "error", "error": str(error) or type(error).__name__})
        return 1
    finally:
        await session.close()


async def set_armed(value: bool) -> int:
    data = read_json(CREDENTIALS)
    if not data:
        emit({"ok": False, "error": "Connect Blink first"})
        return 2
    blink, session = await make_blink(data)
    try:
        if not await blink.start():
            raise RuntimeError("Could not connect to Blink")
        for module in blink.sync.values():
            await module.async_arm(value)
        await asyncio.sleep(2)
        await blink.refresh(force_cache=True)
        write_private(CREDENTIALS, sanitized_login(blink.auth))
        emit(await collect_status(blink))
        return 0
    except Exception as error:  # noqa: BLE001 - convert library errors to JSON.
        emit({"ok": False, "error": str(error) or type(error).__name__})
        return 1
    finally:
        await session.close()


async def live(camera_name: str) -> int:
    data = read_json(CREDENTIALS)
    if not data:
        emit({"event": "error", "error": "Connect Blink first"})
        return 2
    blink, session = await make_blink(data)
    stream = None
    try:
        if not await blink.start():
            raise RuntimeError("Could not connect to Blink")
        camera = blink.cameras.get(camera_name)
        if camera is None:
            raise RuntimeError(f"Camera not found: {camera_name}")
        stream = await camera.init_livestream()
        await stream.start()
        emit({"event": "live_ready", "url": stream.url, "camera": camera_name})
        # Blink live sessions are intentionally bounded. Closing the panel or
        # stopping playback terminates this process sooner.
        await asyncio.wait_for(stream.feed(), timeout=300)
        return 0
    except TimeoutError:
        emit({"event": "live_ended", "camera": camera_name})
        return 0
    except Exception as error:  # noqa: BLE001 - convert library errors to JSON.
        emit({"event": "error", "error": str(error) or type(error).__name__})
        return 1
    finally:
        if stream is not None:
            stream.stop()
        await session.close()


def logout() -> int:
    for path in (CREDENTIALS, CACHE):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    emit({"ok": True, "connected": False, "systems": [], "cameras": []})
    return 0


async def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "status":
        return await status()
    if command == "login":
        return await login()
    if command == "arm":
        return await set_armed(True)
    if command == "disarm":
        return await set_armed(False)
    if command == "live":
        if len(sys.argv) < 3:
            emit({"event": "error", "error": "Choose a camera"})
            return 2
        return await live(sys.argv[2])
    if command == "logout":
        return logout()
    emit({"ok": False, "error": f"Unknown command: {command}"})
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
