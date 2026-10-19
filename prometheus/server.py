"""The control socket and the daemon's main loop.

Same contract as promethee-linux/docs/protocol.md: one JSON object per line
in both directions; requests {id, channel, args}; replies {id, ok, data} or
{id, ok: false, error}; {"event": "state"} pushed on connect, every two
seconds and after every call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
from pathlib import Path

from . import agents, hypr, procfs, stats_extra
from .apps import AppNames
from .core import Core, Refused, Window
from .store import Store
from . import timeutil as T
from .timeutil import now_ms

log = logging.getLogger("prometheus")

MAX_LINE = 64 * 1024
PUSH_INTERVAL = 2.0
CHECKPOINT_INTERVAL = 30.0
LOCK_POLL_INTERVAL = 10.0

# Windows that never count: the screensaver is time away from the machine.
IGNORED_CLASSES = {"org.omarchy.screensaver"}


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or os.path.join(
        os.environ.get("TMPDIR", "/tmp"), f"run-{os.getuid()}"
    )
    return Path(runtime) / "prometheus" / "control.sock"


def format_short(seconds: int) -> str:
    h, m = divmod(max(0, seconds) // 60, 60)
    return f"{h} h {m:02d}" if h else f"{m} min"


class AlreadyRunning(RuntimeError):
    pass


class Daemon:
    def __init__(self, store: Store, names: AppNames | None = None, clock=now_ms):
        self.core = Core(store)
        self.names = names or AppNames()
        self.clock = clock
        self.clients: set[asyncio.StreamWriter] = set()
        self.last_win: dict | None = None
        self.channels = {
            "state": lambda a: self.core.state(self.clock()),
            "session:start": lambda a: self.core.start(a[0] if a else None, self.clock()),
            "session:pause": lambda a: self.core.pause(self.clock()),
            "session:resume": lambda a: self.core.resume(self.clock()),
            "session:end": self._end,
            "activity:idle": self._idle,
            "hoursGoal:get": lambda a: self.core.goal_get(self.clock()),
            "hoursGoal:set": lambda a: self.core.goal_set(a[0] if a else None),
            "stats:summary": lambda a: self.core.summary(a[0] if a else None, self.clock()),
            "apps:getHidden": lambda a: {"success": True, "hiddenApps": self.core.hidden_apps},
            "apps:setHidden": lambda a: self.core.set_hidden_apps(a[0] if a else [], self.clock()),
            "apps:getAliases": lambda a: {"success": True, "aliases": self.core.aliases},
            "apps:setAliases": lambda a: self.core.set_aliases(a[0] if a else {}, self.clock()),
            "apps:known": lambda a: self.core.known_apps(a[0] if a else 30, self.clock()),
            "stats:days": lambda a: self.core.days(a[0] if a else 0, self.clock()),
            "stats:insights": lambda a: self.core.insights(self.clock()),
            "apps:getHiddenWords": lambda a: {"success": True, "hiddenTitleWords": self.core.hidden_words},
            "apps:setHiddenWords": lambda a: self.core.set_hidden_words(a[0] if a else [], self.clock()),
            "stats:timeline": lambda a: self.core.timeline(a[0] if a else None, self.clock()),
            "settings:getDayStart": lambda a: {"success": True, "dayStartHour": T.day_start_hour()},
            "settings:setDayStart": lambda a: self.core.set_day_start(a[0] if a else None, self.clock()),
            "challenge:accept": lambda a: self.core.challenge_accept(a[0] if a else None, self.clock()),
            "challenge:decline": lambda a: self.core.challenge_decline(a[0] if a else None, self.clock()),
            "challenge:abandon": self._abandon,
            "presence:confirm": lambda a: self.core.presence_confirm(self.clock()),
            "settings:getHandle": lambda a: {"success": True, "handle": self.core.handle()},
            "settings:setHandle": lambda a: self.core.set_handle(a[0] if a else None),
            "share:get": lambda a: self.core.share(self.clock()),
            "sessions:names": lambda a: self.core.session_names(self.clock()),
            "settings:getBedtime": lambda a: {"success": True, "bedtimeHour": self.core.coffee.bedtime_hour()},
            "settings:setBedtime": lambda a: self.core.coffee.set_bedtime(a[0] if a else None),
            "break:take": lambda a: self.core.break_take(self.clock()),
            "break:later": lambda a: self.core.break_later(self.clock()),
            "settings:getBreakEvery": lambda a: {"success": True, "minutes": self.core.break_every_minutes()},
            "settings:setBreakEvery": lambda a: self.core.set_break_every(a[0] if a else None),
            "coffee:add": lambda a: self.core.coffee.add(self.clock()),
            "coffee:undo": lambda a: self.core.coffee.undo(self.clock()),
            "coffee:day": lambda a: self.core.coffee.day(a[0] if a else None, self.clock()),
            "stats:coffee": lambda a: self.core.coffee.stats(self.clock()),
            "stats:agents": lambda a: self.core.agents_stats(self.clock()),
            "stats:extra": lambda a: stats_extra.extra(self.core.store, self.clock()),
            "ui:event": lambda a: self.core.ui_event(a[0] if a else None),
            "settings:getShareFormat": lambda a: {"success": True, "format": self.core.share_format()},
            "settings:setShareFormat": lambda a: self.core.set_share_format(a[0] if a else None),
            "settings:getPresenceEvery": lambda a: {"success": True, "minutes": self.core.presence_every_minutes()},
            "settings:setPresenceEvery": lambda a: self.core.set_presence_every(a[0] if a else None),
            "achievements:list": lambda a: self.core.achievements_list(self.clock()),
            "medals:list": lambda a: self.core.medals_list(self.clock()),
            "tasks:list": lambda a: self.core.tasks_list(self.clock()),
            "tasks:add": lambda a: self.core.task_add(a[0] if a else "", a[1] if len(a) > 1 else "manual", self.clock()),
            "tasks:complete": lambda a: self.core.task_complete(a[0] if a else None, self.clock()),
            "tasks:reopen": lambda a: self.core.task_reopen(a[0] if a else None),
            "tasks:delete": lambda a: self.core.task_delete(a[0] if a else None),
            "toast:preview": self._toast_preview,
            "leagues:get": lambda a: self.core.leagues(self.clock()),
            "seasons:get": lambda a: self.core.seasons(self.clock()),
            "leaderboard:get": lambda a: self.core.leaderboard(a[0] if a else "days", self.clock()),
            "leaderboard:removeQuest": lambda a: self.core.leaderboard_remove_quest(a[0] if a else None, self.clock()),
            "quests:list": lambda a: self.core.quests_list(self.clock()),
            "quests:add": lambda a: self.core.quest_add(a[0] if a else "", a[1] if len(a) > 1 else "", self.clock()),
            "quests:activate": lambda a: self.core.quest_activate(a[0] if a else None, self.clock()),
            "quests:deactivate": lambda a: self.core.quest_deactivate(a[0] if a else None, self.clock()),
            "quests:complete": self._quest_complete,
            "quests:uncomplete": lambda a: self.core.quest_uncomplete(a[0] if a else None, self.clock()),
            "quests:delete": lambda a: self.core.quest_delete(a[0] if a else None, self.clock()),
        }
        self.channels["channels"] = lambda a: sorted(self.channels)

    # ------------------------------------------------------------ channels

    END_REASONS = {"manual": "Session ended", "procrastinated": "Session put off"}

    def _end(self, args) -> dict:
        reason = args[0] if args and args[0] in self.END_REASONS else "manual"
        reply = self.core.end(self.clock(), reason)
        reply["recap"]["reason"] = reason
        r = reply["recap"]
        text = f"{r.get('task') or 'Session'} · {format_short(r['durationSeconds'])}"
        burnt = (r.get("agents") or {}).get("tokens", 0)
        if burnt:                       # agents at work meanwhile
            text += f" · {agents.short(burnt)} tokens · ${r['agents']['cost']:.2f}"
        self.toast("ended", self.END_REASONS[reason], text)
        return reply

    def _abandon(self, args) -> dict:
        reply = self.core.challenge_abandon(self.clock())
        self.toast("absent", "Challenge abandoned", f"-{reply['penalty']} XP")
        return reply

    def _toast_preview(self, args) -> dict:
        """Show a sample achievement toast of a rarity (to see what one looks like)."""
        rarity = args[0] if args and args[0] in ("normal", "common", "rare", "epic", "legendary") else "legendary"
        self.toast("achievement", "Preview Achievement", "+42 XP · This is what winning feels like.", rarity)
        return {"success": True}

    QUEST_DONE = {"daily": "Daily quest done", "short": "Quest complete", "long": "Long quest complete"}

    def _quest_complete(self, args) -> dict:
        reply = self.core.quest_complete(args[0] if args else None, self.clock())
        self.toast("quest", self.QUEST_DONE[reply["kind"]], f"{reply['title']} · +{reply['xp']} XP")
        return reply

    def _idle(self, args) -> dict:
        idle = bool(args[0]) if args else False
        seconds = int(args[1]) if len(args) > 1 and isinstance(args[1], (int, float)) else 0
        self.core.set_idle(idle, self.clock(), seconds)
        return {"success": True, "idle": self.core.idle}

    @staticmethod
    def read_only(channel) -> bool:
        if not isinstance(channel, str):
            return True
        if channel in ("state", "channels") or channel.startswith("stats:"):
            return True
        if channel == "share:get":           # records the card, for an achievement
            return False
        _, _, verb = channel.partition(":")
        return verb.startswith(("get", "list", "known"))

    def dispatch(self, request: dict) -> dict:
        rid = request.get("id")
        channel = request.get("channel")
        args = request.get("args") or []
        if not isinstance(args, list):
            args = [args]
        handler = self.channels.get(channel)
        if handler is None:
            return {"id": rid, "ok": False, "error": f"unknown channel: {channel}"}
        try:
            return {"id": rid, "ok": True, "data": handler(args)}
        except Refused as e:
            return {"id": rid, "ok": True, "data": {"success": False, "error": str(e)}}
        except Exception as e:  # a bad call must not take the daemon down
            log.exception("channel %s failed", channel)
            return {"id": rid, "ok": False, "error": f"{type(e).__name__}: {e}"}

    # -------------------------------------------------------------- window

    def resolve(self, win: dict | None) -> Window | None:
        if not win:
            return None
        cls = win.get("initialClass") or win.get("class")
        if cls in IGNORED_CLASSES:
            return None
        pid = win.get("pid")
        app = None
        if procfs.is_terminal(cls) and isinstance(pid, int) and pid > 0:
            inner = procfs.foreground(pid)  # nvim, btop, ssh rather than "Foot"
            if inner:
                app = self.names.name(inner)
        if not app:
            app = self.names.name(cls, hypr.exe_of(pid))
        return Window(app=app, title=win.get("title") or None, wm_class=cls) if app else None

    def on_window(self, win: dict | None) -> None:
        self.last_win = win
        self.core.on_window(self.resolve(win), self.clock())

    # --------------------------------------------------------------- wire

    @staticmethod
    def _line(obj) -> bytes:
        return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode()

    async def _send(self, writer: asyncio.StreamWriter, obj) -> None:
        try:
            writer.write(self._line(obj))
            await writer.drain()
        except (ConnectionError, OSError):
            self.clients.discard(writer)

    async def push(self) -> None:
        if not self.clients:
            return
        line = self._line({"event": "state", "state": self.core.state(self.clock())})
        for w in list(self.clients):
            try:
                w.write(line)
                await w.drain()
            except (ConnectionError, OSError):
                self.clients.discard(w)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.clients.add(writer)
        await self._send(writer, {"event": "state", "state": self.core.state(self.clock())})
        try:
            while True:
                try:
                    line = await reader.readuntil(b"\n")
                except asyncio.IncompleteReadError:
                    break
                except asyncio.LimitOverrunError:
                    break  # a line over 64 KiB closes the connection
                text = line.decode(errors="replace").strip()
                if not text:
                    continue
                try:
                    request = json.loads(text)
                    if not isinstance(request, dict):
                        raise ValueError("not an object")
                except ValueError as e:
                    await self._send(writer, {"ok": False, "error": f"bad request: {e}"})
                    continue
                await self._send(writer, self.dispatch(request))
                # A read changes nothing: no achievement to check, no state to push.
                if not self.read_only(request.get("channel")):
                    self.check_achievements()
                    await self.push()
        except (ConnectionError, OSError):
            pass
        finally:
            self.clients.discard(writer)
            writer.close()

    # --------------------------------------------------------------- loops

    def check_achievements(self) -> None:
        """Unlock and announce. The first run only catches up on the history:
        one toast for the lot instead of a burst."""
        try:
            seeded = self.core.store.get_setting("achievementsSeeded", False)
            new = self.core.check_achievements(self.clock())
        except Exception:
            log.exception("achievement check failed")
            return
        if not seeded:
            self.core.store.set_setting("achievementsSeeded", True)
            if new:
                xp = sum(a["xp"] for a in new)
                self.toast("achievement", f"{len(new)} achievements from your history", f"+{xp} XP")
            self.check_medals()
            return
        if len(new) > 3:
            # A burst (a new kind of history read at once): one toast, at
            # the rarest one's rarity, naming the rarest.
            order = ["normal", "common", "rare", "epic", "legendary"]
            ranked = sorted(new, key=lambda a: -order.index(a.get("rarity") or "normal"))
            xp = sum(a["xp"] for a in new)
            names = ", ".join(a["name"] for a in ranked[:2])
            self.toast("achievement", f"{len(new)} achievements unlocked",
                       f"+{xp} XP · {names}…", ranked[0].get("rarity"))
        else:
            for a in new:
                self.toast("achievement", a["name"], f"+{a['xp']} XP · {a['quip']}", a.get("rarity"))
        self.check_medals()

    def check_medals(self) -> None:
        """Award medals for the running periods. The first run awards the
        whole history at once, with a single toast."""
        try:
            seeded = self.core.store.get_setting("medalsSeeded", False)
            new = self.core.check_medals(self.clock(), history=not seeded)
        except Exception:
            log.exception("medal check failed")
            return
        if not seeded:
            self.core.store.set_setting("medalsSeeded", True)
            if new:
                self.toast("medal", f"{len(new)} medals from your history", f"+{sum(m['xp'] for m in new)} XP")
            return
        for m in new:
            self.toast("medal", m["name"], f"+{m['xp']} XP · {m['quip']}")

    async def _pusher(self) -> None:
        ticks = 0
        while True:
            await asyncio.sleep(PUSH_INTERVAL)
            ticks += 1
            if ticks % 30 == 1:          # about once a minute, and at start
                self.check_achievements()
            # Agent tokens: every 30 s, every tick while the first import runs.
            if ticks % 15 == 1 or self.core.agents.backlog:
                try:
                    self.core.agents.poll()
                except Exception:
                    log.exception("agent usage poll failed")
            try:
                now = self.clock()
                for kind, info in (self.core.update_challenge(now) + self.core.update_presence(now)
                                   + self.core.update_breaks(now)):
                    self.announce(kind, info)
            except Exception:
                log.exception("challenge update failed")
            await self.push()

    # ----------------------------------------------------------- challenges

    def announce(self, kind: str, info: dict) -> None:
        # Offers are answered from the bar's pill (state.challenge); a won
        # challenge is told in the bar too.
        if kind == "won":
            self.toast("won", "Challenge won", f"+{info['xp']} XP")
        elif kind == "absent":
            self.toast("absent", "Session paused", "no answer to \"Still there?\"")

    # ---------------------------------------------------------------- toasts
    # Short messages for the bar plugin to show next to the timer; no
    # desktop notifications. Lost if no bar is connected, which is fine:
    # they only echo what the state already holds.

    def toast(self, kind: str, title: str, text: str = "", rarity: str | None = None) -> None:
        payload = {"event": "toast", "kind": kind, "title": title, "text": text}
        if rarity:
            payload["rarity"] = rarity
        line = self._line(payload)
        for w in list(self.clients):
            try:
                w.write(line)
            except (ConnectionError, OSError):
                self.clients.discard(w)

    async def _checkpointer(self) -> None:
        while True:
            self.core.tick(self.clock())
            # What runs in a focused terminal changes without a focus event.
            win = self.last_win
            if win and procfs.is_terminal(win.get("initialClass") or win.get("class")):
                self.on_window(win)
            await asyncio.sleep(CHECKPOINT_INTERVAL)

    async def _lock_watcher(self) -> None:
        """Poll the shell's lock state; a plugin cannot read the lock service itself."""
        exe = shutil.which("omarchy-shell") or "/usr/share/omarchy/bin/omarchy-shell"
        if not os.path.exists(exe):
            log.warning("omarchy-shell not found: lock state not followed")
            return
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    exe, "lock", "isLocked",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                )
                out, _ = await asyncio.wait_for(proc.communicate(), 3)
                value = out.decode().strip().lower()
                if value in ("true", "false"):
                    locked = value == "true"
                    if locked != self.core.locked:
                        log.info("screen %s", "locked" if locked else "unlocked")
                        self.core.set_locked(locked, self.clock())
                        await self.push()
            except (OSError, asyncio.TimeoutError) as e:
                log.debug("lock poll failed: %s", e)
            await asyncio.sleep(LOCK_POLL_INTERVAL)

    async def serve(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.exists() or path.is_socket():
            # Never steal the socket from a live daemon: only a refused node is stale.
            try:
                _, w = await asyncio.wait_for(asyncio.open_unix_connection(str(path)), 1)
                w.close()
                raise AlreadyRunning(f"prometheusd already running on {path}")
            except (OSError, asyncio.TimeoutError):
                path.unlink()  # stale node left by a crash
        old = os.umask(0o177)
        try:
            server = await asyncio.start_unix_server(self.handle, path=str(path), limit=MAX_LINE)
        finally:
            os.umask(old)
        os.chmod(path, 0o600)
        log.info("listening on %s", path)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        tasks = [
            asyncio.create_task(hypr.follow(self.on_window)),
            asyncio.create_task(self._pusher()),
            asyncio.create_task(self._checkpointer()),
            asyncio.create_task(self._lock_watcher()),
        ]
        try:
            await stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            # wait_closed() waits for every client, and a bar never hangs up on
            # its own: close them first, and bound the wait anyway.
            server.close()
            for w in list(self.clients):
                w.close()
            self.clients.clear()
            try:
                await asyncio.wait_for(asyncio.shield(server.wait_closed()), 2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self.core.tick(self.clock())  # last checkpoint before exit
            try:
                path.unlink()
            except OSError:
                pass


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("PROMETHEUS_LOG", "INFO"),
        format="%(levelname)s %(name)s: %(message)s",
    )
    db = os.environ.get("PROMETHEUS_DB")
    sock = os.environ.get("PROMETHEUS_SOCKET")
    daemon = Daemon(Store(db) if db else Store())
    try:
        asyncio.run(daemon.serve(Path(sock) if sock else socket_path()))
    except AlreadyRunning as e:
        raise SystemExit(str(e))
