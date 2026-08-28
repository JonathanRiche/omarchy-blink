#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["blinkpy==0.25.9"]
# ///
"""Local JSON bridge between Omarchy's QML shell and BlinkPy."""

from __future__ import annotations

import asyncio
import json
import math
import os
import secrets
import stat
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

MAX_CREDENTIAL_BYTES = 128 * 1024
MAX_CACHE_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 256 * 1024
MAX_STDIN_BYTES = 8 * 1024
MAX_CAMERAS = 64
MAX_SYSTEMS = 16
MAX_NAME_CHARS = 128
MAX_VALUE_CHARS = 64
MAX_ERROR_CHARS = 512
START_TIMEOUT_SECONDS = 120
ACTION_TIMEOUT_SECONDS = 180
LIVE_SETUP_TIMEOUT_SECONDS = 120


def emit(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()
    if len(encoded) > MAX_OUTPUT_BYTES:
        encoded = b'{"ok":false,"error":"Blink response exceeded the safe limit"}'
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()


def open_state_dir(*, create: bool) -> int:
    """Open and validate the state directory without following a final symlink."""
    if create:
        STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(
        STATE_DIR,
        os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise OSError("Blink state path is not a user-owned directory")
        os.fchmod(descriptor, 0o700)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def ensure_state() -> None:
    descriptor = open_state_dir(create=True)
    os.close(descriptor)


def read_json(path: Path, limit: int) -> dict[str, Any]:
    """Read a small, user-owned regular file without following links or FIFOs."""
    directory = -1
    descriptor = -1
    try:
        directory = open_state_dir(create=False)
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW,
            dir_fd=directory,
        )
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
            or info.st_size > limit
        ):
            return {}
        chunks = bytearray()
        while len(chunks) <= limit:
            chunk = os.read(descriptor, min(64 * 1024, limit + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        raw = bytes(chunks)
        if len(raw) > limit:
            return {}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (FileNotFoundError, BlockingIOError, json.JSONDecodeError, OSError):
        return {}
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory >= 0:
            os.close(directory)


def write_private(path: Path, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, indent=2, ensure_ascii=True) + "\n").encode()
    limit = MAX_CREDENTIAL_BYTES if path == CREDENTIALS else MAX_CACHE_BYTES
    if len(encoded) > limit:
        raise ValueError("Blink state exceeded the safe storage limit")
    directory = open_state_dir(create=True)
    descriptor = -1
    temporary_name = ""
    try:
        for _ in range(10):
            temporary_name = f".{path.name}.{secrets.token_hex(16)}.tmp"
            try:
                descriptor = os.open(
                    temporary_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
                break
            except FileExistsError:
                continue
        if descriptor < 0:
            raise OSError("Could not securely create Blink state file")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            descriptor = -1
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=directory,
            dst_dir_fd=directory,
        )
        temporary_name = ""
        os.fsync(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=directory)
            except FileNotFoundError:
                pass
        os.close(directory)


def limited_text(value: Any, limit: int = MAX_VALUE_CHARS) -> str:
    return str(value if value is not None else "")[:limit]


def limited_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return limited_text(value)


def error_text(error: BaseException) -> str:
    return limited_text(str(error) or type(error).__name__, MAX_ERROR_CHARS)


def read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.buffer.readline(MAX_STDIN_BYTES + 1)
    if len(raw) > MAX_STDIN_BYTES:
        raise ValueError("Login input exceeded the safe limit")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise TypeError("Expected a JSON object")
    return parsed


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
        "name": limited_text(name, MAX_NAME_CHARS),
        "armed": bool(attributes.get("arm", False)),
        "motion": bool(attributes.get("motion_detected", False)),
        "battery": limited_text(attributes.get("battery") or "unknown"),
        "batteryLevel": limited_scalar(attributes.get("battery_level")),
        "temperatureC": limited_scalar(attributes.get("temperature_c")),
        "wifi": limited_scalar(attributes.get("wifi_strength")),
        "thumbnail": "",
    }


def limited_items(mapping: Any, limit: int):
    for index, item in enumerate(mapping.items()):
        if index >= limit:
            break
        yield item


def bounded_cached_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Rebuild cached output so corrupted local JSON cannot inflate the QML model."""
    cameras = []
    raw_cameras = payload.get("cameras", [])
    if isinstance(raw_cameras, list):
        for camera in raw_cameras[:MAX_CAMERAS]:
            if not isinstance(camera, dict):
                continue
            cameras.append(
                {
                    "name": limited_text(camera.get("name"), MAX_NAME_CHARS),
                    "armed": bool(camera.get("armed", False)),
                    "motion": bool(camera.get("motion", False)),
                    "battery": limited_text(camera.get("battery") or "unknown"),
                    "batteryLevel": limited_scalar(camera.get("batteryLevel")),
                    "temperatureC": limited_scalar(camera.get("temperatureC")),
                    "wifi": limited_scalar(camera.get("wifi")),
                    "thumbnail": "",
                }
            )
    systems = []
    raw_systems = payload.get("systems", [])
    if isinstance(raw_systems, list):
        for system in raw_systems[:MAX_SYSTEMS]:
            if not isinstance(system, dict):
                continue
            systems.append(
                {
                    "name": limited_text(system.get("name"), MAX_NAME_CHARS),
                    "armed": bool(system.get("armed", False)),
                    "online": bool(system.get("online", False)),
                }
            )
    result = {
        "ok": bool(payload.get("ok", True)),
        "connected": bool(payload.get("connected", False)),
        "armed": bool(payload.get("armed", False)),
        "systems": systems,
        "cameras": cameras,
    }
    if payload.get("error"):
        result["error"] = limited_text(payload["error"], MAX_ERROR_CHARS)
    return result


async def collect_status(blink: Blink) -> dict[str, Any]:
    cameras = []
    for name, camera in limited_items(blink.cameras, MAX_CAMERAS):
        cameras.append(camera_payload(name, camera))
    systems = []
    for name, module in limited_items(blink.sync, MAX_SYSTEMS):
        systems.append(
            {
                "name": limited_text(name, MAX_NAME_CHARS),
                "armed": bool(module.arm),
                "online": bool(module.available),
            }
        )
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
    data = read_json(CREDENTIALS, MAX_CREDENTIAL_BYTES)
    if not data:
        cached = bounded_cached_status(read_json(CACHE, MAX_CACHE_BYTES))
        emit(
            cached
            if cached
            else {"ok": True, "connected": False, "systems": [], "cameras": []}
        )
        return 0
    blink, session = await make_blink(data)
    try:
        async with asyncio.timeout(START_TIMEOUT_SECONDS):
            if not await blink.start():
                raise RuntimeError("Blink rejected the saved session")
        write_private(CREDENTIALS, sanitized_login(blink.auth))
        emit(await collect_status(blink))
        return 0
    except Exception as error:  # noqa: BLE001 - BlinkPy leaks transport exceptions.
        cached = bounded_cached_status(read_json(CACHE, MAX_CACHE_BYTES))
        emit(
            {
                **cached,
                "ok": False,
                "connected": bool(cached.get("connected", False)),
                "error": error_text(error),
            }
        )
        return 1
    finally:
        await session.close()


async def login() -> int:
    ensure_state()
    try:
        request = read_stdin_json()
        username = limited_text(request.get("username", ""), 320).strip()
        password = limited_text(request.get("password", ""), 1024)
        if not username or not password:
            raise ValueError("Email and password are required")
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        emit({"event": "error", "error": str(error)})
        return 2

    blink, session = await make_blink({"username": username, "password": password})
    try:
        try:
            async with asyncio.timeout(START_TIMEOUT_SECONDS):
                ready = await blink.start()
        except BlinkTwoFARequiredError:
            emit({"event": "needs_2fa"})
            request = read_stdin_json()
            if not request:
                raise RuntimeError("2FA login was cancelled")
            code = limited_text(request.get("code", ""), 32).strip()
            async with asyncio.timeout(START_TIMEOUT_SECONDS):
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
        emit({"event": "error", "error": error_text(error)})
        return 1
    finally:
        await session.close()


async def set_armed(value: bool) -> int:
    data = read_json(CREDENTIALS, MAX_CREDENTIAL_BYTES)
    if not data:
        emit({"ok": False, "error": "Connect Blink first"})
        return 2
    blink, session = await make_blink(data)
    try:
        async with asyncio.timeout(ACTION_TIMEOUT_SECONDS):
            if not await blink.start():
                raise RuntimeError("Could not connect to Blink")
            for _, module in limited_items(blink.sync, MAX_SYSTEMS):
                await module.async_arm(value)
            await asyncio.sleep(2)
            await blink.refresh(force_cache=True)
        write_private(CREDENTIALS, sanitized_login(blink.auth))
        emit(await collect_status(blink))
        return 0
    except Exception as error:  # noqa: BLE001 - convert library errors to JSON.
        emit({"ok": False, "error": error_text(error)})
        return 1
    finally:
        await session.close()


async def live(camera_name: str) -> int:
    camera_name = limited_text(camera_name, MAX_NAME_CHARS)
    data = read_json(CREDENTIALS, MAX_CREDENTIAL_BYTES)
    if not data:
        emit({"event": "error", "error": "Connect Blink first"})
        return 2
    blink, session = await make_blink(data)
    stream = None
    try:
        async with asyncio.timeout(LIVE_SETUP_TIMEOUT_SECONDS):
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
        emit({"event": "error", "error": error_text(error)})
        return 1
    finally:
        if stream is not None:
            stream.stop()
        await session.close()


def logout() -> int:
    directory = -1
    try:
        directory = open_state_dir(create=False)
    except FileNotFoundError:
        pass
    try:
        for path in (CREDENTIALS, CACHE) if directory >= 0 else ():
            try:
                os.unlink(path.name, dir_fd=directory)
            except FileNotFoundError:
                pass
    finally:
        if directory >= 0:
            os.close(directory)
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
