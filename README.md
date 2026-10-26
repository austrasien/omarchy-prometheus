# Prometheus

Local focus sessions, window tracking and a bit of XP for
[Omarchy](https://omarchy.org) on Hyprland. No account, no cloud: a small
Python daemon keeps everything in one SQLite file, and a bar plugin shows it.

Started as a local replacement for [Promethee](https://promethee.io), keeping
only what was actually used.

- **Sessions**: start one with a task name, pause, resume, end. Under the
  name field: the 3 last used names and the 4 with the most focus time,
  from the whole history; click one, or arrows and Enter. The timer
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
- **Presence check**: every 20 min of running session (a setting, 5 to 120 min), a pill asks "Still
  there?". A click keeps going; unanswered, it flashes from the 3rd minute and
  the session pauses at the 4th, backdated to the question (a playing video
  keeps idle away, so idle alone cannot tell).
- **Breaks**: after 90 min in session without a break (a pause of 5 min or
  more, by hand or not, resets it; a setting, 30 to 180 min or off), a
  "Break?" pill unrolls in the bar: OK pauses the session, No asks again
  in 20 min. The Session tab shows when it is due ("Next break in 35 min")
  and marks it on the hour by hour view. During a session, when the best
  time for a coffee has come, "Coffee?": OK logs a cup, No (or no answer in 15 min)
  stays quiet for an hour. Questions show one at a time, the most urgent first: "Still
  there?", the challenge offer, "Break?", "Coffee?".
- **Privacy**: apps that are never recorded, and words that keep a window
  out of the records when its title contains them (a bank, say).
- **Aliases**: rename or merge apps; applied when reading, so they rewrite
  the past too and can be undone.
- **Coffee**: a Coffee button on the Session tab logs a cup (95 mg, one
  standard cup; Undo for 3 minutes). Caffeine in the blood follows a
  one-compartment model for a 90 kg man (absorbed in about 45 minutes,
  half-life 5 h); the best time for the next cup is when it falls under
  60 mg and stays there, before the daily 400 mg and 8 h before bedtime (23:00 by
  default, in Settings). The Session tab shows the day hour by hour: time in session,
  agent tokens, cups, tasks and quests, the caffeine curve, now and the
  best time. Stats has a Coffee view: cups by day and week, per cup, coffee
  days against the others, and correlations with focus, tasks, tokens, XP.
- **Agent tokens**: tokens burned by coding agents count as a sign of work.
  This machine: Claude Code's transcripts (`~/.claude/projects`), read as
  they grow, per minute, conversation, project and model, with the input /
  output / cache split and a cost at API prices (only counts are read,
  never what was said). Other machines: the snapshots the agents panel
  (`austraz.agents`, `remoteHosts`) pulls every 10 minutes, compared one to
  the next; when the laptop slept, the gap is spread evenly and marked
  estimated (the pull service's journal fills in what came before). Every
  token counts (input, output, cache). 1 XP per 75,000 tokens, 10 a day at
  most. Shown next to the week's focus bars, above the day timeline (per
  quarter hour), during a session and in its recap, in a Stats view
  (30 days, machines, models, projects, heatmap, cache share, tokens per
  prompt, parallel conversations, share outside focus sessions), in the
  leaderboards (token days, token sessions), on seasons and on the ID card.
- **Stats**: today and the week, each day's apps, a timeline of the day
  colored by app, the week history paged back up to 52 weeks, an hours goal.
  Other views, one button each: XP this week by source (stacked bars), tasks
  (done per day, to-do list size, age when checked), focus quality (session
  length, app switches per hour, time in the main app), a weekday × hour
  heatmap, challenges (accepted, won, XP lost to abandons), "Still there?"
  (answer rate, reaction time, pauses), and sessions on battery or by weather.
  A day starts at 5 h by default (configurable), so a late night stays with
  its evening.
- **Tasks**: Prometheus' own list, checked off during a session. A task is
  worth 1 XP, plus 1 for every full 24 h since it was created; the value
  freezes when it is checked. Optionally, the todos of an Obsidian daily note
  (`## Tasks`) are offered as suggestions when adding one; nothing is ever
  written back to the note.
- **Quests**: goals that take more than one sitting. A quest is daily (back
  every day, each day's completion kept), short (a few days) or long (more than
  a week). One quest at a time is active: a red bookmark hangs on the panel and
  the quest shows under the title. Each day a session runs while it is active
  counts as a day worked. Rewards: daily 5 XP, +1 per day in a row before it (up
  to 10); short 10 XP + 5 per day worked (up to 40); long 30 XP + 5 per day
  worked (up to 150). Deleting a quest keeps the XP it already earned. Seven quest completions a day at most, daily ones included.
  Each open quest has its own color among the ten vivid hues of the medals:
  the first one, and any new one while no open quest is red, is red; the others
  draw a color left, so no two open quests share one (ten at most). The active
  quest's title is shown in its color.
  The active quest sits in a capsule of its color in the list; the bookmark puts
  it aside. Each quest tracks what happened in sessions while it was active:
  focus time, sessions, focus per hour of the day, tasks checked and XP earned.
- **XP and levels**: 1 XP per 10 min of session (pauses excluded), plus done
  tasks, plus won challenges. Level 2 costs 100 XP, each next level 50 more.
- **Leagues**: ten, Bronze, Silver, Gold, Sapphire, Ruby, Emerald, Amethyst,
  Pearl, Obsidian, Diamond, drawn as a circle, a triangle, a square, a
  pentagon, a hexagon, then stars of four to eight points. The tab draws your
  league path, round by round, as a staircase. Each two-week round (Sunday to the second Saturday) you play nine rivals, scientists and pioneers drawn by lot each
  season from a pool of 104 (never two with the same first name; a click on a name shows a one-line bio), drawn from a Gaussian fitted to your last two rounds (5 % stronger
  each league up; if that is under 87 % of the league's minimum, the floor is
  used instead) and seeded by week and
  league, so a week always replays the same. They earn their XP as the week
  goes. Top 3 go up a league if they reach the league's minimum (300 XP a week in
  Bronze, then 340, 385, 435, 490, 580, 690, 820, 980: Obsidian is twice Ruby;
  prorated as the round goes for the live zone), bottom 3 go down one; the rivals
  are never weaker than 87 % of that minimum, an empty week always goes
  down. The tab shows the ten players with the promotion, stagnation and
  relegation zones, green chevrons streaming up or red ones streaming down.
  League XP is XP from the work: focus, tasks, challenges, quests;
  achievements and medals are left out.
- **Seasons** (the running one charts your cumulative XP against the steady
  pace of the goal and of the hard goal; medal colors are drawn from the season's name, so every
  player gets the same medal for the same season): the weather's: winter from December 1st, spring from March 1st,
  summer from June 1st, autumn from September 1st, named "Autumn 2026" and so
  on. Two goals, as weekly paces over the season's length (from your first day,
  the first season): your good weeks (the better half of the 26 weeks before)
  for the goal, 250 XP a week at least; 30 % above for the hard goal, 350 XP a
  week at least. A full season: 3250 and 4550 XP at least. The goal wins a
  season medal (75 XP), the hard goal its second edge bar (200 XP in all).
  Season medals are permanent, on their own row at the top of the placard, under a
  holographic shine and a star: an edge bar on the left for the goal, on both
  sides for the hard goal. Colors are contrasted (a deep ribbon, a near-white
  star, vivid edge bars) and kept away from the ten medal hues; they are drawn as the season starts, so the medal to
  win shows grey above each goal and comes alive under the mouse. A finished
  season gets a grade (S 20 % beyond the hard goal, A hard goal, B goal, C
  80 %, D 60 %, F below) and a recap.
- **Leaderboard**: your best days and weeks (XP), sessions (focus) and quests
  (XP while active), top 10, with the current one highlighted. A quest can be
  taken off the board (an open one is deleted); its XP stays.
- **Share**: the "share" button by the panel's title renders a service ID card
  as an animated GIF by default, or an animated PNG (a setting; open it in a
  browser) (18 frames, a hologram and a glint on the ribbons
  looping, 256 colors; under 1 MB at 900 px; the first frame is mid-shine, for
  viewers that show only it):
  @handle (set in Settings), service number, rank, XP, league, enlistment
  date, service record (every season's grade), decorations (every medal) and
  legendary achievements, a stamp per shining league with at least one
  round finished in it, rarest first, with the count, with a holographic seal. It asks where to save it
  (zenity) and needs ffmpeg.
- **Achievements** (a family not started yet shows only dots; tiers after the next one too; each tier has a rarity by the XP it is worth: normal under 30, common green, rare blue from 60, epic purple from 140, legendary gold and shining from 360; secrets are epic): 224 families with 1398 tiers, five at least each (forty tie two features together, crossings.py; agent tokens, quests, leagues, seasons, leaderboards, and exploring the tool: settings changed, cards generated, tabs opened, bios read, rarity set by hand), plus a calendar of 126
  dated achievements (one per date: Roman festivals, geek days, scientists
  and writers, SpaceX and Tesla milestones, each unlocked by finishing a
  session that day, 10 XP), so 1524 in all, computed from Prometheus' own
  records: sessions, tasks (same-day, inbox zero, redemptions), cumulative
  hours (100 h to 10,000 h), levels, endurance, intensity, 3-day and weekly
  hours, streaks, active days and months, early and late sessions, midnight
  crossings, challenges, task archaeology, calm and single-app sessions,
  "Still there?" reflexes, holidays, sessions on battery or on its last 10 %, goals reached per day, week or
  month, personal-best weeks, XP in a day, clockwork starts, dawn streaks,
  sessions without automatic pauses, comebacks, geek dates, hours on a single
  task, named sessions, backlog clean-ups, speedruns, best month and year,
  perfect weeks, years of use, focus purity, locked-in sessions, challenge
  acceptance runs, start hours around the clock,
  and sessions by weather (read from the file the Omarchy
  weather plugin writes, `~/.local/state/omarchy/weather-current.json`), and a
  few secrets. Each has a name, a description, a line when it unlocks, and an
  XP reward: 5 XP per tier up to the 10th, then 2 more per tier; 10 for a
  single achievement; times the family's weight (x1, x2 or x3, by
  difficulty). Secret ones are worth 25 XP. Sessions under 10 min count for nothing.
- **Medals**: 24 recurring decorations, put back in play every day, week or
  month: won as soon as the condition holds in the running period, and again
  the next period (2 h / 4 h / 6 h days, 5 tasks, early and late sessions,
  challenges, daily goal, pure focus; 7-for-7 weeks, 30 h and 50 h weeks, 25
  tasks, record week, weekend; 20-day months, 100 h, 80 tasks, record month,
  14-day streak, three kinds of weather...). Each is a military ribbon: dots
  for the period (1 daily, 2 weekly, 3 monthly), edge stripes for the
  difficulty, a color per theme from a pool of 10 vivid hues. Rewards 5 / 20 / 60 XP by period, x1.5 or x2
  with stripes. The panel shows the ribbons won under the level bar, with how
  many times each was won.
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

### With the minimap

With [omarchy-minimap](https://github.com/austrasien/omarchy-minimap)
installed, link the Prometheus map into it:

```bash
ln -s ~/.config/omarchy/plugins/austraz.prometheus/minimap \
  ~/.config/omarchy/plugins/austraz.minimap/maps/prometheus
omarchy-restart-shell
```

Chosen in the minimap's list, the map shows the session like the bar:
timer, task, a ring to the next XP or the challenge's countdown; a click
pauses or resumes. Whatever the minimap shows, toasts (achievements with
their rarity shine, medals, quests, challenges, session ends, the hours
goal, errors) and questions ("Still there?", the challenge offer,
"Break?", "Coffee?", answered by clicking a half of the disc) come up
there as minimap notifications, their text running round the edge. While
the map is installed and the minimap shown, the bar leaves toasts and
questions to it and keeps the timer; without the minimap it shows them as
before. `omarchy-shell austraz.minimap demo prometheus <kind>` shows one:
an achievement rarity, `medal`, `quest`, `won`, `goal`, `ended`, `absent`,
`error`, `level`, `presence`, `challenge`, `break` or `coffee`. A level up
shows green chevrons; a medal shows its ribbon; "Session paused" stays up
while the session is paused (a click resumes); with no session, a click on
the map opens the bar's Prometheus menu to start one.

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
| `presence:confirm` | | Answer "Still there?" |
| `settings:getPresenceEvery`, `settings:setPresenceEvery` | `[minutes]` | How often to ask, 5 to 120, default 20 |
| `achievements:list` | | Every family, its tiers, what is unlocked and the progress |
| `medals:list` | | Every medal, its ribbon, how many times won, won this period or not |
| `tasks:list` | | Open tasks with their XP, and the ones done today |
| `tasks:add` | `[text, source]` | `source`: manual, obsidian, procrastinated; an open duplicate is not added |
| `tasks:complete` | `[id]` | Only during a session |
| `tasks:reopen` | `[id]` | Back to the list, during a session |
| `tasks:delete` | `[id]` | Drop an open task without its XP |
| `toast:preview` | `[rarity\|kind]` | Show a sample toast: an achievement of a rarity, or `ended`, `absent`, `quest`, `medal`, `won`, `goal`, `error` |
| `toast:echo` | `[kind, title, text?, rarity?]` | Send a toast made by a client (the bar's hours goal, a share card) back to every client |
| `share:get` | | What the share card shows |
| `sessions:names` | | Session names: the 3 last used, the 4 most worked on, and all with focus time |
| `break:take` / `break:later` | | Answer "Break?": pause the session, or ask again in 20 min |
| `settings:getBreakEvery` / `settings:setBreakEvery` | `[minutes]` | Minutes of work before "Break?" (0 = off) |
| `coffee:nudgeOk` / `coffee:nudgeNo` | | Answer "Coffee?": log a cup, or quiet for an hour |
| `coffee:add` / `coffee:undo` | | Log a cup / take the last one back (3 min) |
| `settings:getBedtime` / `settings:setBedtime` | `[hour]` | Bedtime, for the best time for a coffee |
| `coffee:day` | `[fromMs]` | The day hour by hour, caffeine every 10 minutes, the best time for a cup |
| `stats:coffee` | | Cups by day and week, per cup, correlations |
| `stats:agents` | | Agent tokens: today, 30 days, machines, models, projects, heatmap, how |
| `stats:extra` | | XP by source this week, tasks, focus quality, weekday × hour heatmap, challenges, presence checks, power and weather |
| `ui:event` | `[tab:<name>\|bio]` | A tab opened (once each) or a rival bio read, for achievements |
| `settings:getHandle` / `settings:setHandle` | `[handle]` | The player's @handle, shown by the panel title |
| `settings:getShareFormat` / `settings:setShareFormat` | `[gif\|apng]` | Share export format |
| `leagues:get` | | League ladder, settled weeks, the current week's zone |
| `seasons:get` | | Every season (goals, grade, recap) and the season medals |
| `leaderboard:get` | `[board]` | Top 10 of `days`, `weeks`, `sessions` or `quests` |
| `leaderboard:removeQuest` | `[id]` | Take a quest off the board (an open one is deleted); XP stays |
| `quests:list` | | Open quests, the last completed ones, quest XP |
| `quests:add` | `[title, kind]` | New quest; kind is `daily`, `short` or `long` |
| `quests:activate` | `[id]` | Make it the active quest (only one at a time) |
| `quests:deactivate` | `[id?]` | Put the active quest aside |
| `quests:complete` | `[id]` | Done: for today if daily, for good otherwise |
| `quests:uncomplete` | `[id]` | Undo a completion (today's, if daily) |
| `quests:delete` | `[id]` | Hide a quest; the XP it earned stays |
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
