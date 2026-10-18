# Prometheus

Local focus sessions, window tracking and a bit of XP for
[Omarchy](https://omarchy.org) on Hyprland. No account, no cloud: a small
Python daemon keeps everything in one SQLite file, and a bar plugin shows it.

Started as a local replacement for [Promethee](https://promethee.io), keeping
only what was actually used.

- **Sessions**: start one with a task name, pause, resume, end. The timer
  sits next to the bar icon; the recap shows up in the bar.
- **Window tracking**: the focused Hyprland window, followed through the
  event socket rather than polled, stored as one interval per stretch in an
  app. A focused terminal counts as what runs in its foreground (`nvim`,
  `btop`, `ssh`); a bare shell counts as the terminal. Chromium web apps take
  the name of their launcher entry.
- **Away from the machine**: idle (from the bar's `IdleMonitor`, backdated to
  when it began), a locked screen (`omarchy-shell lock isLocked`, polled
  every 10 s), the screensaver window and suspend (a gap between checkpoints)
  are never attributed to an app. They also pause the running session by
  themselves; such a pause resumes by itself when you are back, while a
  pause you make by hand never does.
- **Presence check**: every 20 min of running session (a setting, 5 to 120 min), a pill asks "Toujours
  là ?". A click keeps going; unanswered, it flashes from the 3rd minute and
  the session pauses at the 4th, backdated to the question (a playing video
  keeps idle away, so idle alone cannot tell).
- **Privacy**: apps that are never recorded, and words that keep a window
  out of the records when its title contains them (a bank, say).
- **Aliases**: rename or merge apps; applied when reading, so they rewrite
  the past too and can be undone.
- **Stats**: today and the week, each day's apps, a timeline of the day
  colored by app, the week history paged back up to 52 weeks, an hours goal.
  A day starts at 5 h by default (configurable), so a late night stays with
  its evening.
- **Tasks**: Prometheus' own list, checked off during a session. A task is
  worth 1 XP, plus 1 for every full 24 h since it was created; the value
  freezes when it is checked. Optionally, the todos of an Obsidian daily note
  (`## Tasks`) are offered as suggestions when adding one; nothing is ever
  written back to the note.
- **XP and levels**: 1 XP per 10 min of session (pauses excluded), plus done
  tasks, plus won challenges. Level 2 costs 100 XP, each next level 50 more.
- **Achievements**: 39 families, 318 tiers, computed from Prometheus' own
  records: sessions, tasks, cumulative hours (100 h to 10,000 h), levels,
  endurance, intensity, 3-day and weekly hours, streaks, early and late
  sessions, challenges, task archaeology, single-app stretches, calendar,
  sessions on battery and sessions by weather (read from the file the Omarchy
  weather plugin writes, `~/.local/state/omarchy/weather-current.json`), and a
  few secrets. Each has a name, a description, a line when it unlocks, and an
  XP reward: 5 XP per tier, capped at 50; 10 for a single achievement, 25 for
  a secret one. Sessions under 10 min count for nothing.
- **Extension challenge**: after 1 h of focus, a pill in the bar offers 20
  min more. Hovered, it splits into decline and accept. Accepted, the session
  cannot be ended before those 20 min of focus are done, unless the challenge
  is abandoned. Bonuses grow when chained: +2, +3, then +5 XP, three per
  session at most.

## Layout

| Path | |
| --- | --- |
| `prometheus/` | The daemon: storage, tracking, the control socket |
| `plugin/` | The Omarchy bar plugin (`austraz.prometheus`), QML |
| `bin/` | `prometheusd`, `prometheus-ctl`, `prometheus-import` |
| `systemd/` | The user service |
| `tests/` | Unit tests for the daemon |

Python 3 standard library only. Data lives in
`~/.local/share/prometheus/prometheus.db`.

## Install

```bash
git clone https://github.com/austrasien/omarchy-prometheus ~/src/prometheus

# daemon
ln -sf ~/src/prometheus/systemd/prometheus.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now prometheus

# bar plugin
ln -s ~/src/prometheus/plugin ~/.config/omarchy/plugins/austraz.prometheus
omarchy bar put austraz.prometheus --section center
```

The service file expects the checkout at `~/src/prometheus`; edit
`ExecStart` otherwise. `PROMETHEUS_DB`, `PROMETHEUS_SOCKET` and
`PROMETHEUS_LOG` override the defaults. Starting a second daemon fails
instead of taking the socket over.

Obsidian suggestions need the widget's `vaultPath` setting and the
`obsidian-daily-qs` helper (`journalBin`); without them, the tasks tab works
without suggestions.

## Protocol

`$XDG_RUNTIME_DIR/prometheus/control.sock`, mode 0600. One JSON object per
line in both directions: `{"id", "channel", "args"}` requests,
`{"id", "ok", "data" | "error"}` replies. `{"event": "state", "state": …}` is
pushed on connect, every two seconds and after every call;
`{"event": "toast", "kind", "title", "text"}` carries short messages for the
bar (session ended, challenge won).

| Channel | Args | |
| --- | --- | --- |
| `state` | | The pushed state, as a reply |
| `channels` | | Every channel |
| `session:start` | `[task \| null]` | Refused while a session is open |
| `session:pause`, `session:resume` | | |
| `session:end` | `[reason]` | `manual` or `procrastinated`; returns `{recap}`. Refused during a challenge |
| `activity:idle` | `[bool, idleSeconds]` | Idle since `idleSeconds` ago |
| `challenge:accept`, `challenge:decline` | `[id]` | Answer the extension challenge offer |
| `challenge:abandon` | | Give up a running challenge (no bonus) |
| `presence:confirm` | | Answer "Toujours là ?" |
| `settings:getPresenceEvery`, `settings:setPresenceEvery` | `[minutes]` | How often to ask, 5 to 120, default 20 |
| `achievements:list` | | Every family, its tiers, what is unlocked and the progress |
| `tasks:list` | | Open tasks with their XP, and the ones done today |
| `tasks:add` | `[text, source]` | `source`: manual, obsidian, procrastinated; an open duplicate is not added |
| `tasks:complete` | `[id]` | Only during a session |
| `tasks:reopen` | `[id]` | Back to the list, during a session |
| `tasks:delete` | `[id]` | Drop an open task without its XP |
| `hoursGoal:get`, `hoursGoal:set` | `[{hours, period} \| "off"]` | `period`: day, week, month |
| `settings:getDayStart`, `settings:setDayStart` | `[hour]` | 0–12, default 5 |
| `stats:summary` | `[{fromMs, toMs}]` | Focus, sessions, 2 h+ sessions, switches/h, apps |
| `stats:days` | `[weekOffset]` | Mon–Sun focus and tracked seconds |
| `stats:timeline` | `[{fromMs, toMs}]` | The day as merged app stretches, plus sessions |
| `stats:insights` | | Today vs yesterday at the same time, top app, busiest day |
| `apps:getHidden`, `apps:setHidden` | `[[names]]` | Never recorded (raw name or alias) |
| `apps:getHiddenWords`, `apps:setHiddenWords` | `[[words]]` | A title containing one (any case) is never recorded |
| `apps:getAliases`, `apps:setAliases` | `[{raw: shown}]` | Rename or merge |
| `apps:known` | `[days]` | Raw names seen lately, with their alias |

The state holds `session` (with `autoPaused` and the session's `bonusXp`),
`today`, `window`, `idle`, `locked`, `history` (seven days), `apps` (today's
top five), `trackedSeconds`, `profile` (XP and level), `challenge`,
`todayDate` and `dayStartHour`.

```bash
bin/prometheus-ctl state
bin/prometheus-ctl call session:start '"Write the docs"'
bin/prometheus-ctl watch
```

## Importing Promethee's history

```bash
bin/prometheus-import    # reads ~/.config/Promethee/promethee.db read-only
```

Sessions keep their ids, so running it twice adds nothing. Window samples
(every 10 s) are merged into intervals.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

## Credits

The control protocol follows the one of
[promethee-linux](https://github.com/Akayashuu/promethee-linux). Terminal
resolution and lock handling borrow ideas from
[agx.screen-time](https://github.com/ax1g/quickshell-screentime-plugin); the
day start and the task value from [Habitica](https://github.com/HabitRPG/habitica).

## License

MIT
