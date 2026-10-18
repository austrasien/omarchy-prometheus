import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// Client for the prometheusd control socket (~/src/prometheus). Same wire
// protocol as promethee-linux: one JSON object per line, {id, channel, args}
// requests, a {"event": "state"} push on connect, every two seconds and
// after every call.
//
// It also reports idleness: the daemon cannot see Wayland idle, so the
// shell's IdleMonitor tells it, and idle time is not attributed to apps.
Item {
  id: root

  property string socketOverride: ""
  property int idleTimeout: 300   // seconds without input before time stops counting

  readonly property string socketPath: {
    if (socketOverride.length > 0) return socketOverride
    var runtime = Quickshell.env("XDG_RUNTIME_DIR") || ("/run/user/" + Quickshell.env("UID"))
    return runtime + "/prometheus/control.sock"
  }

  // True from the first line the server sends until the socket drops.
  // `socket.connected` stays true after a refused attempt, so it cannot tell
  // a live daemon from a dead one.
  property bool live: false
  property var session: null      // { id, task, startedAt, pausedMs, pauseStartedAt }
  property var today: ({ sessions: 0, seconds: 0 })
  property var window: null       // { app, title }
  property bool idle: false
  property var profile: null      // { xp, level, levelXp, levelCost, focusXp, taskXp, challengeXp }
  property var challenge: null    // { id, state: offered | active, minutes, xp, remainingSeconds }
  property var presence: null     // { askedAt, flashing, pauseAt } while "still there?" is asked
  property var medals: []         // the placard: [{ id, name, desc, period, color, dots, dot, edges, count, current }]
  property var history: []        // seven { date, minutes }, oldest first
  property var apps: []           // today's top five { app, seconds }
  property int trackedSeconds: 0
  // The daemon's day: it starts at dayStartHour (5 h by default), so
  // between midnight and then, "today" is still the calendar day before.
  property string todayDate: Qt.formatDate(new Date(), "yyyy-MM-dd")
  property int dayStartHour: 5

  readonly property bool running: session !== null && !session.pauseStartedAt
  // Why the session paused by itself ("" if it did not): away, locked.
  readonly property string autoPauseLabel: {
    var r = session && session.autoPaused ? session.autoPaused : []
    if (r.indexOf("locked") >= 0) return "screen locked"
    if (r.indexOf("idle") >= 0) return "idle"
    return ""
  }
  readonly property bool paused: session !== null && !!session.pauseStartedAt

  // Seconds in the open session, pauses deducted. Recomputed from the
  // server's timestamps on each tick so it cannot drift after a suspend.
  property int elapsed: 0
  readonly property int todaySeconds: (today ? today.seconds || 0 : 0) + elapsed

  // XP of the open session: 1 per full 10 min of focus, ticking live with
  // `elapsed`, plus what the daemon counts besides (tasks, won challenges).
  readonly property int secondsPerXp: session && session.secondsPerXp ? session.secondsPerXp : 600
  readonly property int sessionXp: session ? Math.floor(elapsed / secondsPerXp) + (session.bonusXp || 0) : 0
  readonly property int nextXpIn: secondsPerXp - (elapsed % secondsPerXp)

  signal failed(string reason)
  signal ended(var recap)
  // A short message from the daemon, for the bar (no desktop notifications).
  signal toast(string kind, string title, string text)

  // ------------------------------------------------------------- formatting

  function pad(n) { return String(n).padStart(2, "0") }

  // "4:12", "1:04:12"
  function formatDuration(seconds) {
    var t = Math.max(0, Math.floor(seconds))
    var h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60
    return h > 0 ? h + ":" + pad(m) + ":" + pad(s) : m + ":" + pad(s)
  }

  // "45 min", "2 h 05"
  function formatShort(seconds) {
    var t = Math.max(0, Math.floor(seconds))
    var h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60)
    return h > 0 ? h + " h " + pad(m) : m + " min"
  }

  function recomputeElapsed() {
    if (!session || !session.startedAt) { elapsed = 0; return }
    var until = session.pauseStartedAt || Date.now()
    elapsed = Math.max(0, Math.floor((until - session.startedAt - (session.pausedMs || 0)) / 1000))
  }

  // ------------------------------------------------------------------- wire

  property var pending: ({})
  property int nextId: 1

  function call(channel, args, callback) {
    if (!live || !socketLoader.item) {
      if (callback) callback(false, null)
      return
    }
    var id = nextId++
    if (callback) pending[id] = callback
    socketLoader.item.write(JSON.stringify({ id: id, channel: channel, args: args || [] }) + "\n")
    socketLoader.item.flush()
  }

  // Calls an action and reports failure, including `{ success: false }`
  // replies, which arrive with ok: true.
  function act(channel, args, label, then) {
    call(channel, args, function(ok, data) {
      if (ok && data && data.success === false) {
        failed(label + " : " + (data.error || "refused"))
        return
      }
      if (ok && then) then(data)
    })
  }

  function ingest(line) {
    var trimmed = line.trim()
    if (trimmed.length === 0) return
    var payload
    try { payload = JSON.parse(trimmed) } catch (e) { return }
    var wasLive = live
    live = true
    if (!wasLive) sendIdle()

    if (payload.event === "state") { apply(payload.state); return }
    if (payload.event === "toast") { toast(payload.kind || "", payload.title || "", payload.text || ""); return }

    var callback = pending[payload.id]
    if (callback) {
      delete pending[payload.id]
      callback(payload.ok === true, payload.data === undefined ? null : payload.data)
    }
    if (payload.ok === false && payload.error) failed(payload.error)
  }

  // The server pushes the whole state every two seconds. Assigning a fresh
  // object re-evaluates every binding and rebuilds every Repeater delegate,
  // so only fields whose content actually changed are written.
  property var signatures: ({})

  function assign(name, value) {
    var sig = JSON.stringify(value)
    if (signatures[name] === sig) return
    signatures[name] = sig
    root[name] = value
  }

  function apply(state) {
    if (!state) return
    assign("session", state.session || null)
    assign("today", state.today || { sessions: 0, seconds: 0 })
    assign("window", state.window || null)
    assign("idle", !!state.idle)
    assign("profile", state.profile || null)
    assign("challenge", state.challenge || null)
    assign("presence", state.presence || null)
    assign("medals", state.medals || [])
    assign("history", state.history || [])
    assign("apps", state.apps || [])
    assign("trackedSeconds", state.trackedSeconds || 0)
    if (state.todayDate) assign("todayDate", state.todayDate)
    if (state.dayStartHour !== undefined) assign("dayStartHour", state.dayStartHour)
    recomputeElapsed()
  }

  function reset() {
    live = false
    signatures = {}
    session = null
    today = { sessions: 0, seconds: 0 }
    window = null
    idle = false
    profile = null
    challenge = null
    presence = null
    medals = []
    history = []
    apps = []
    trackedSeconds = 0
    elapsed = 0
    pending = {}
  }

  // ---------------------------------------------------------------- actions

  function start(task) {
    var name = (task || "").trim()
    act("session:start", [name.length > 0 ? name : null], "Start")
  }

  function pause() { act("session:pause", [], "Pause") }
  function resume() { act("session:resume", [], "Resume") }

  // Never ends a session: ending is irreversible, pausing is not.
  function toggle() {
    if (!session) start("")
    else if (paused) resume()
    else pause()
  }

  // The daemon writes the session and sends the recap as a notification.
  function stop() {
    act("session:end", [], "End session", function(d) { if (d && d.recap) root.ended(d.recap) })
  }

  // Ends the session too (its time stays counted), filed as put off rather
  // than done; `then` gets the recap, e.g. to send the task back to the list.
  function procrastinate(then) {
    act("session:end", ["procrastinated"], "Procrastinate", function(d) {
      if (d && d.recap) {
        root.ended(d.recap)
        if (then) then(d.recap)
      }
    })
  }

  // ------------------------------------------------------------ challenge

  readonly property bool challengeOffered: !!challenge && challenge.state === "offered"
  readonly property bool challengeActive: !!challenge && challenge.state === "active"

  function acceptChallenge() { if (challenge) act("challenge:accept", [challenge.id], "Challenge") }
  function declineChallenge() { if (challenge) act("challenge:decline", [challenge.id], "Challenge") }
  function abandonChallenge() { act("challenge:abandon", [], "Challenge") }

  function confirmPresence() { act("presence:confirm", [], "Presence") }

  // ------------------------------------------------------------------ idle

  IdleMonitor {
    id: idleMonitor
    enabled: root.idleTimeout > 0
    timeout: Math.max(1, root.idleTimeout)
    respectInhibitors: true   // a playing video keeps the time counted
    onIsIdleChanged: root.sendIdle()
  }

  function sendIdle() {
    if (!live) return
    call("activity:idle", [idleMonitor.isIdle, idleMonitor.isIdle ? root.idleTimeout : 0])
  }

  // ------------------------------------------------------------- connection
  //
  // A Socket that failed once never retries, so reconnecting means building
  // a new one. Rather than retrying on a timer while the daemon is down,
  // wait for the kernel to say the socket node was created (IN_CREATE in its
  // directory). The watcher's -t timeout is only a safety net.

  function reconnect() {
    socketLoader.active = false
    socketLoader.active = true
    attemptTimer.restart()
  }

  Loader {
    id: socketLoader
    active: true
    sourceComponent: Component {
      Socket {
        path: root.socketPath
        connected: true
        parser: SplitParser {
          splitMarker: "\n"
          onRead: data => root.ingest(data)
        }
        onConnectionStateChanged: {
          if (!connected) {
            root.reset()
            attemptTimer.restart()
          }
        }
      }
    }
  }

  // The server pushes state the moment a client connects; no line within
  // this window means the attempt failed.
  Timer {
    id: attemptTimer
    interval: 1500
    running: true
    onTriggered: if (!root.live && !watcher.running) watcher.running = true
  }

  Process {
    id: watcher
    // $1 socket. Absent: wait until it exists (creating its directory counts
    // too). Present but refused: stale, wait for the daemon to replace it.
    command: ["bash", "-c",
      'sock=$1; dir=${sock%/*}\n' +
      'if [ -S "$sock" ]; then /usr/bin/inotifywait -qq -t 60 -e create -e moved_to "$dir"; exit 0; fi\n' +
      'while [ ! -S "$sock" ]; do\n' +
      '  if [ -d "$dir" ]; then w=$dir; else w=${dir%/*}; fi\n' +
      '  /usr/bin/inotifywait -qq -t 300 -e create -e moved_to "$w" || [ $? -eq 2 ] || sleep 30\n' +
      'done',
      "prometheus-watch", root.socketPath]
    onExited: root.reconnect()
  }

  onSocketPathChanged: {
    reset()
    watcher.running = false
    reconnect()
  }

  Timer {
    running: root.running
    interval: 1000
    repeat: true
    onTriggered: root.recomputeElapsed()
  }
}
