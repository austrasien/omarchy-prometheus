import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prometheus import server
from prometheus.apps import AppNames
from prometheus.store import Store


class ServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sock = Path(self.tmp.name) / "p" / "control.sock"
        self.daemon = server.Daemon(Store(":memory:"), names=AppNames({"foot": "Foot"}))
        # No Hyprland in tests: the follower just waits.
        self.follow = mock.patch.object(server.hypr, "follow", new=lambda cb: asyncio.sleep(3600))
        self.follow.start()
        self.lock = mock.patch.object(server.Daemon, "_lock_watcher", new=lambda self: asyncio.sleep(3600))
        self.lock.start()
        self.task = asyncio.create_task(self.daemon.serve(self.sock))
        for _ in range(50):
            if self.sock.exists():
                break
            await asyncio.sleep(0.02)

    async def asyncTearDown(self):
        self.task.cancel()
        try:
            await self.task
        except (asyncio.CancelledError, Exception):
            pass
        self.follow.stop()
        self.lock.stop()
        self.tmp.cleanup()

    async def connect(self):
        reader, writer = await asyncio.open_unix_connection(str(self.sock))
        first = json.loads(await reader.readline())
        return reader, writer, first

    async def call(self, reader, writer, rid, channel, args=None):
        writer.write((json.dumps({"id": rid, "channel": channel, "args": args or []}) + "\n").encode())
        await writer.drain()
        while True:
            msg = json.loads(await asyncio.wait_for(reader.readline(), 2))
            if msg.get("id") == rid:
                return msg

    async def test_socket_mode_and_push_on_connect(self):
        self.assertEqual(os.stat(self.sock).st_mode & 0o777, 0o600)
        reader, writer, first = await self.connect()
        self.assertEqual(first["event"], "state")
        self.assertTrue(first["state"]["authenticated"])
        self.assertIsNone(first["state"]["session"])
        writer.close()

    async def test_session_round_trip(self):
        reader, writer, _ = await self.connect()
        reply = await self.call(reader, writer, 1, "session:start", ["Écrire"])
        self.assertEqual(reply, {"id": 1, "ok": True, "data": {"success": True}})
        # A state push follows the call.
        push = json.loads(await asyncio.wait_for(reader.readline(), 2))
        self.assertEqual(push["state"]["session"]["task"], "Écrire")
        again = await self.call(reader, writer, 2, "session:start", ["x"])
        self.assertEqual(again["data"]["success"], False)
        writer.write((json.dumps({"id": 3, "channel": "session:end"}) + "\n").encode())
        await writer.drain()
        toast = end = None
        while end is None:
            msg = json.loads(await asyncio.wait_for(reader.readline(), 2))
            if msg.get("event") == "toast":
                toast = msg
            elif msg.get("id") == 3:
                end = msg
        self.assertEqual(end["data"]["recap"]["task"], "Écrire")
        self.assertEqual(toast["title"], "Session ended")
        await self.call(reader, writer, 4, "session:start", ["Plus tard"])
        later = await self.call(reader, writer, 5, "session:end", ["procrastinated"])
        self.assertEqual(later["data"]["recap"]["reason"], "procrastinated")
        row = self.daemon.core.store.get_session(later["data"]["recap"]["id"])
        self.assertEqual(row["end_reason"], "procrastinated")
        writer.close()

    async def test_errors(self):
        reader, writer, _ = await self.connect()
        bad = await self.call(reader, writer, 1, "nope")
        self.assertEqual(bad, {"id": 1, "ok": False, "error": "unknown channel: nope"})
        chans = await self.call(reader, writer, 2, "channels")
        self.assertIn("session:start", chans["data"])
        writer.write(b"not json\n")
        await writer.drain()
        while True:  # skip state pushes
            msg = json.loads(await asyncio.wait_for(reader.readline(), 2))
            if "event" not in msg:
                break
        self.assertFalse(msg["ok"])
        writer.close()

    async def test_refuses_to_steal_a_live_socket(self):
        other = server.Daemon(Store(":memory:"))
        with self.assertRaises(server.AlreadyRunning):
            await other.serve(self.sock)
        self.assertTrue(self.sock.exists())

    def test_window_mapping(self):
        self.daemon.on_window({"class": "foot", "title": "~", "pid": None})
        self.assertEqual(self.daemon.core.window.app, "Foot")
        self.daemon.on_window({"class": "org.example.thing-app", "title": "t"})
        self.assertEqual(self.daemon.core.window.app, "Org Example Thing App")
        self.daemon.on_window(None)
        self.assertIsNone(self.daemon.core.window)
        self.daemon.on_window({"class": "org.omarchy.screensaver", "title": "ss", "pid": 1})
        self.assertIsNone(self.daemon.core.window)


if __name__ == "__main__":
    unittest.main()
