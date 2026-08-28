"""Regression tests for helper trust-boundary hardening."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import blink_helper as helper


class SecureStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state = Path(self.temporary.name) / "state"
        self.credentials = self.state / "credentials.json"
        self.cache = self.state / "status.json"
        self.paths = patch.multiple(
            helper,
            STATE_DIR=self.state,
            CREDENTIALS=self.credentials,
            CACHE=self.cache,
        )
        self.paths.start()

    def tearDown(self):
        self.paths.stop()
        self.temporary.cleanup()

    def test_private_round_trip_and_permissions(self):
        helper.write_private(self.credentials, {"token": "secret"})
        self.assertEqual(
            helper.read_json(self.credentials, helper.MAX_CREDENTIAL_BYTES),
            {"token": "secret"},
        )
        self.assertEqual(self.credentials.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(self.state.glob("*.tmp")), [])

    def test_symlink_is_not_followed(self):
        helper.ensure_state()
        target = self.state / "target.json"
        target.write_text('{"token":"stolen"}')
        target.chmod(0o600)
        self.credentials.symlink_to(target)
        self.assertEqual(
            helper.read_json(self.credentials, helper.MAX_CREDENTIAL_BYTES), {}
        )

    def test_fifo_is_rejected_without_blocking(self):
        helper.ensure_state()
        os.mkfifo(self.credentials)
        self.assertEqual(
            helper.read_json(self.credentials, helper.MAX_CREDENTIAL_BYTES), {}
        )

    def test_oversized_file_is_rejected(self):
        helper.ensure_state()
        self.credentials.write_bytes(b" " * 129)
        self.assertEqual(helper.read_json(self.credentials, 128), {})

    def test_logout_does_not_follow_state_directory_symlink(self):
        victim = Path(self.temporary.name) / "victim"
        victim.mkdir(mode=0o700)
        victim_credentials = victim / self.credentials.name
        victim_cache = victim / self.cache.name
        victim_credentials.write_text("keep credentials")
        victim_cache.write_text("keep cache")
        self.state.symlink_to(victim, target_is_directory=True)

        with self.assertRaises(OSError), patch.object(helper, "emit"):
            helper.logout()

        self.assertTrue(victim_credentials.exists())
        self.assertTrue(victim_cache.exists())

    def test_mapping_iteration_is_bounded(self):
        mapping = {str(index): index for index in range(helper.MAX_SYSTEMS + 10)}
        items = list(helper.limited_items(mapping, helper.MAX_SYSTEMS))
        self.assertEqual(len(items), helper.MAX_SYSTEMS)

    def test_cached_models_and_fields_are_bounded(self):
        payload = {
            "connected": True,
            "cameras": [
                {"name": "x" * 1000, "battery": "y" * 1000}
                for _ in range(helper.MAX_CAMERAS + 10)
            ],
            "systems": [{"name": "z" * 1000} for _ in range(helper.MAX_SYSTEMS + 10)],
            "error": "e" * 1000,
        }
        bounded = helper.bounded_cached_status(payload)
        self.assertEqual(len(bounded["cameras"]), helper.MAX_CAMERAS)
        self.assertEqual(len(bounded["systems"]), helper.MAX_SYSTEMS)
        self.assertEqual(len(bounded["cameras"][0]["name"]), helper.MAX_NAME_CHARS)
        self.assertEqual(len(bounded["error"]), helper.MAX_ERROR_CHARS)
        self.assertLessEqual(len(json.dumps(bounded).encode()), helper.MAX_OUTPUT_BYTES)


class BoundedActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_armed_caps_remote_actions(self):
        class FakeModule:
            def __init__(self):
                self.calls = 0

            async def async_arm(self, _value):
                self.calls += 1

        class FakeBlink:
            def __init__(self):
                self.auth = type(
                    "FakeAuth", (), {"login_attributes": {"token": "test"}}
                )()
                self.modules = [FakeModule() for _ in range(helper.MAX_SYSTEMS + 20)]
                self.sync = {
                    str(index): module for index, module in enumerate(self.modules)
                }

            async def start(self):
                return True

            async def refresh(self, **_kwargs):
                return True

        fake_blink = FakeBlink()
        fake_session = type("FakeSession", (), {"close": AsyncMock()})()
        make_blink = AsyncMock(return_value=(fake_blink, fake_session))
        status = {"ok": True, "connected": True, "systems": [], "cameras": []}

        with (
            patch.object(helper, "read_json", return_value={"token": "test"}),
            patch.object(helper, "make_blink", make_blink),
            patch.object(helper, "write_private"),
            patch.object(helper, "collect_status", AsyncMock(return_value=status)),
            patch.object(helper.asyncio, "sleep", AsyncMock()),
            patch.object(helper, "emit"),
        ):
            result = await helper.set_armed(True)

        self.assertEqual(result, 0)
        self.assertEqual(
            sum(module.calls for module in fake_blink.modules), helper.MAX_SYSTEMS
        )
        self.assertTrue(
            all(
                module.calls == 0 for module in fake_blink.modules[helper.MAX_SYSTEMS :]
            )
        )


if __name__ == "__main__":
    unittest.main()
