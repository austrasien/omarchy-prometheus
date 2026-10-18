import QtQuick
import QtQuick.Shapes
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Prometheus in the bar: the timer sits next to the icon while a session
// runs. Hidden while prometheusd is not running.
//
//   left click    panel: session, journal tasks, stats, settings
//   right click   pause / resume (opens the panel when no session runs,
//                 so a session always starts with a name)
//   middle click  today's daily note in Obsidian
//
// Ending a session lives in the panel only: it is the one irreversible
// action, so it never sits on a bare click.
BarWidget {
  id: root
  moduleName: "austraz.prometheus"

  readonly property string fireGlyph: String.fromCodePoint(0xF0238)
  readonly property string pauseGlyph: String.fromCodePoint(0xF03E4)
  readonly property string playGlyph: String.fromCodePoint(0xF040A)
  readonly property string stopGlyph: String.fromCodePoint(0xF04DB)
  readonly property string laterGlyph: String.fromCodePoint(0xF051F)
  readonly property string historyGlyph: String.fromCodePoint(0xF02DA)

  readonly property color accent: Color.accent

  // The theme's green and red (colors.toml), which the shell does not expose.
  property color green: "#9ece6a"
  property color red: Color.urgent
  property color gold: "#e0af68"   // the theme's yellow: task XP laurels
  // Distinct colors for the day timeline, most used app first.
  property var palette: [Color.accent, "#9ece6a", "#e0af68", "#bb9af7", "#7dcfff", "#f7768e"]

  FileView {
    path: Color.currentThemePath + "/colors.toml"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      var found = {}
      var lines = text().split("\n")
      for (var i = 0; i < lines.length; i++) {
        var m = lines[i].match(/^\s*(green|red|yellow|magenta|cyan|color[1-6])\s*=\s*["']?(#[0-9A-Fa-f]{6})/)
        if (m) found[m[1]] = m[2]
      }
      function pick(name, slot) { return found[name] || found[slot] || "" }
      if (pick("green", "color2")) root.green = pick("green", "color2")
      if (pick("red", "color1")) root.red = pick("red", "color1")
      if (pick("yellow", "color3")) root.gold = pick("yellow", "color3")
      var pal = [Color.accent]
      var wanted = [["green", "color2"], ["yellow", "color3"], ["magenta", "color5"], ["cyan", "color6"], ["red", "color1"]]
      for (var j = 0; j < wanted.length; j++) {
        var c = pick(wanted[j][0], wanted[j][1])
        if (c) pal.push(c)
      }
      if (pal.length > 1) root.palette = pal
    }
  }
  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // ---- session names: every name a session was started with, how often
  // and when last, kept inline on this widget's shell.json entry. Feeds the
  // suggestions and the autocompletion under "What are you working on?".
  //
  //   [{ name, count, last (epoch ms) }]
  //
  // Past 20 names, the ones not used for two days go first, least used
  // first; recent names are never dropped, even past the cap.

  readonly property int maxNames: 20
  readonly property double staleAfterMs: 2 * 24 * 3600 * 1000

  readonly property var sessionNames: {
    var list = settings && Array.isArray(settings.sessionNames) ? settings.sessionNames : null
    if (list === null) {
      // Older entries only kept the last names, most recent first.
      var legacy = settings && Array.isArray(settings.recentTasks) ? settings.recentTasks : []
      var now = Date.now()
      list = legacy.map(function(n, i) { return { name: n, count: 1, last: now - i * 60000 } })
    }
    return list.filter(function(e) { return e && typeof e.name === "string" && e.name.length > 0 })
  }

  // Most recent first.
  readonly property var recentNames: sessionNames.slice().sort(function(a, b) { return b.last - a.last })
  readonly property string lastTask: recentNames.length > 0 ? recentNames[0].name : ""

  function writeSetting(name, value) {
    var entry = { id: root.moduleName }
    for (var key in root.settings) if (key !== "id") entry[key] = root.settings[key]
    entry[name] = value
    if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
  }

  function writeSettings(values) {
    var entry = { id: root.moduleName }
    for (var key in root.settings) if (key !== "id") entry[key] = root.settings[key]
    for (var k in values) entry[k] = values[k]
    if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
  }

  function pruneNames(list) {
    if (list.length <= maxNames) return list
    var now = Date.now()
    var stale = list.filter(function(e) { return now - e.last > root.staleAfterMs })
      .sort(function(a, b) { return a.count - b.count || a.last - b.last })
    var drop = {}
    for (var i = 0; i < stale.length && list.length - Object.keys(drop).length > maxNames; i++) drop[stale[i].name] = true
    return list.filter(function(e) { return !drop[e.name] })
  }

  // Once per session, wherever it was started. The id
  // is stored alongside so a shell restart mid-session does not count twice.
  function rememberSession(session) {
    var name = (session.task || "").trim()
    if (name.length === 0 || session.id === (settings ? settings.lastSessionId : "")) return
    var now = Date.now(), found = false
    var next = sessionNames.map(function(e) {
      if (e.name !== name) return e
      found = true
      return { name: e.name, count: (e.count || 0) + 1, last: now }
    })
    if (!found) next.push({ name: name, count: 1, last: now })
    var values = { sessionNames: pruneNames(next), lastSessionId: session.id }
    if (settings && settings.recentTasks !== undefined) values.recentTasks = undefined
    writeSettings(values)
  }

  // Up to `limit` names for what is typed: names starting with it first,
  // then names containing it; within each, most used then most recent.
  // With nothing typed, the most recent ones.
  function suggestNames(query, limit) {
    var q = (query || "").trim().toLowerCase()
    if (q === "") return recentNames.slice(0, limit)
    function score(e) { return e.count * 1e13 + e.last }
    var starts = [], contains = []
    for (var i = 0; i < sessionNames.length; i++) {
      var e = sessionNames[i], n = e.name.toLowerCase()
      if (n === q) continue
      if (n.indexOf(q) === 0) starts.push(e)
      else if (n.indexOf(q) > 0) contains.push(e)
    }
    starts.sort(function(a, b) { return score(b) - score(a) })
    contains.sort(function(a, b) { return score(b) - score(a) })
    return starts.concat(contains).slice(0, limit)
  }

  function shorten(text, max) {
    return text.length > max ? text.slice(0, max - 1) + "…" : text
  }

  // Handed to the tabs, whose own `p` property would shadow the id.
  readonly property var client: p
  readonly property var journal: journalModel

  // Obsidian vault for task suggestions; none when unset.
  readonly property string vaultPath: settings && settings.vaultPath ? String(settings.vaultPath) : ""

  Journal {
    id: journalModel
    vault: root.vaultPath
    bin: root.settings && root.settings.journalBin ? String(root.settings.journalBin)
      : Quickshell.env("HOME") + "/.config/omarchy/plugins/austraz.clock/bin/obsidian-daily-qs-x86_64"
  }

  Prometheus {
    id: p
    socketOverride: root.settings && root.settings.socket ? String(root.settings.socket) : ""
    idleTimeout: root.settings && root.settings.idleTimeout !== undefined ? Number(root.settings.idleTimeout) : 300
    onSessionChanged: {
      if (p.session) root.rememberSession(p.session)
      root.refreshGoal()
      if (panelLoader.item) Qt.callLater(panelLoader.item.focusContent)
    }
    onFailed: function(reason) { root.showToast("error", reason, "") }
    onToast: function(kind, title, text, rarity) { root.showToast(kind, title, text, rarity) }
  }

  function openJournal() {
    Quickshell.execDetached([journalModel.bin, "--vault", journalModel.vault, "open"])
  }

  // ---- hours goal: a hairline under the timer, one toast when reached

  property var goal: null   // hoursGoal:get -> { goal: {hours, period}, progress: {window, workedSeconds} }
  readonly property real goalTarget: goal && goal.goal ? goal.goal.hours * 3600 : 0
  readonly property real goalWorked: goal && goal.progress ? (goal.progress.workedSeconds || 0) + p.elapsed : 0
  readonly property real goalProgress: goalTarget > 0 ? Math.min(1, goalWorked / goalTarget) : 0
  readonly property string goalKey: goal && goal.goal && goal.progress && goal.progress.window
    ? goal.goal.period + ":" + goal.progress.window.fromMs : ""

  function refreshGoal() {
    if (!p.live) return
    p.call("hoursGoal:get", [], function(ok, d) { if (ok && d && d.success) root.goal = d })
  }

  onGoalProgressChanged: {
    if (goalProgress < 1 || goalKey === "" || settings.goalNotifiedFor === goalKey) return
    root.writeSetting("goalNotifiedFor", goalKey)
    var label = goal.goal.period === "day" ? "Daily" : goal.goal.period === "week" ? "Weekly" : "Monthly"
    root.showToast("goal", label + " goal reached", goal.goal.hours + " h of focus")
  }

  Connections {
    target: p
    function onLiveChanged() { if (p.live) root.refreshGoal() }
  }

  // Closed sessions only reach workedSeconds through the daemon; re-read it
  // now and then rather than guess.
  Timer {
    running: p.live
    interval: 5 * 60 * 1000
    repeat: true
    onTriggered: root.refreshGoal()
  }

  // ---- panel contract (bar popout coordinator + KeyboardPanel owner)

  property bool panelOpen: false
  // Panel tab, kept across openings.
  property string tab: "session"

  // XP just earned from an item of the panel (e.g. a task's laurel): the
  // panel flies it up into the XP bar, which then pulses.
  signal xpGained(var source, int xp)
  property bool popoutSwitchClosing: false
  readonly property bool opened: panelOpen

  function open() {
    if (!p.live) return
    panelOpen = true
  }
  function close() { panelOpen = false }
  function togglePanel() { panelOpen ? close() : open() }
  function closeForPopoutSwitch() {
    popoutSwitchClosing = true
    close()
    Qt.callLater(function() { root.popoutSwitchClosing = false })
  }
  function switchPanel(direction) {
    if (bar && typeof bar.switchPanelFrom === "function") return bar.switchPanelFrom(root, direction)
    return false
  }

  // ---- bar face

  visible: p.live
  implicitWidth: button.implicitWidth
    + (presencePill.width > 0 ? presencePill.width + Style.space(2) : 0)
    + (pill.width > 0 ? pill.width + Style.space(2) : 0)
    + (toastPill.width > 0 ? toastPill.width + Style.space(4) : 0)
    + (achPill.visible ? achPill.width + Style.space(4) : 0)
  implicitHeight: button.implicitHeight

  readonly property string checkGlyph: String.fromCodePoint(0xF012C)
  readonly property bool goalReached: goalTarget > 0 && goalProgress >= 1
  readonly property string goalHint: goalTarget <= 0 ? ""
    : goalReached ? " · goal reached"
    : " · " + p.formatShort(goalTarget - goalWorked) + " to goal"

  readonly property string lockGlyph: String.fromCodePoint(0xF033E)

  readonly property string barText: (p.session
    ? fireGlyph + "  " + p.formatDuration(p.elapsed)
    : fireGlyph)
    + (p.challengeActive ? "  " + lockGlyph + " " + Math.ceil((p.challenge.remainingSeconds || 0) / 60) + " min" : "")
    + (goalReached ? "  " + checkGlyph : "")

  readonly property string tooltip: {
    if (!p.session) return "Prometheus · no session · " + p.formatShort(p.todaySeconds) + " today" + goalHint
    var task = p.session.task || "Session"
    return task + (p.paused ? (p.autoPauseLabel ? " (paused: " + p.autoPauseLabel + ")" : " (paused)") : "") + " · " + p.formatShort(p.todaySeconds) + " today" + goalHint
  }

  WidgetButton {
    id: button
    anchors.left: parent.left
    anchors.top: parent.top
    anchors.bottom: parent.bottom
    width: implicitWidth
    bar: root.bar
    text: root.vertical ? root.fireGlyph : root.barText
    foreground: p.running ? root.accent : (root.bar ? root.bar.barForeground : Color.foreground)
    dimmed: p.paused
    useActiveColor: false
    tooltipText: root.panelOpen ? "" : root.tooltip
    horizontalMargin: 8.75
    verticalPadding: 8.75

    onPressed: function(b) {
      if (b === Qt.RightButton) {
        if (p.session) p.toggle()
        else {
          root.tab = "session"
          root.open()
        }
      } else if (b === Qt.MiddleButton) {
        root.openJournal()
      } else {
        root.togglePanel()
      }
    }
  }

  Rectangle {
    visible: root.goalTarget > 0 && !root.vertical
    anchors.left: parent.left
    anchors.leftMargin: Style.space(6)
    anchors.bottom: parent.bottom
    anchors.bottomMargin: Style.space(3)
    height: Math.max(1, Style.space(2))
    width: Math.max(0, (button.width - Style.space(12)) * root.goalProgress)
    radius: height / 2
    color: root.accent
    opacity: root.goalProgress >= 1 ? 1 : 0.7
    Behavior on width { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
  }

  // ---- presence check: "Still there?" unrolls after the timer, in solid
  // amber that breathes and nudges now and then, so it cannot be missed.
  // Hovered it turns green; a click says yes. Unanswered for 3 min it flashes
  // white and green; at 4 min the daemon pauses the session.
  readonly property color presenceAmber: "#ffb020"

  readonly property bool presenceWanted: !!p.presence && !root.vertical
  property real presenceShown: presenceWanted ? 1 : 0
  Behavior on presenceShown { NumberAnimation { duration: 450; easing.type: Easing.OutCubic } }

  // The daemon pushes state every 2 s; the flash starts on time from the clock.
  property bool presenceFlashing: false
  property bool flashOn: false
  Timer {
    interval: 500
    repeat: true
    running: root.presenceWanted
    onTriggered: {
      root.presenceFlashing = !!p.presence && (p.presence.flashing || Date.now() - p.presence.askedAt >= 180000)
      root.flashOn = root.presenceFlashing ? !root.flashOn : false
    }
    onRunningChanged: if (!running) { root.presenceFlashing = false; root.flashOn = false }
  }

  TextMetrics {
    id: presenceMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
    text: "Still there?"
  }

  Item {
    id: presencePill
    anchors.left: button.right
    anchors.leftMargin: Style.space(2)
    anchors.verticalCenter: button.verticalCenter
    readonly property real fullWidth: presenceMetrics.advanceWidth + Style.space(22)
    readonly property bool hovered: presenceArea.containsMouse
    width: Math.round(fullWidth * root.presenceShown)
    height: Math.round(button.height * 0.72)
    visible: width > 0
    clip: true

    Rectangle {
      id: presenceBg
      anchors.fill: parent
      radius: height / 2
      readonly property bool calm: !presencePill.hovered && !root.flashOn && !root.presenceFlashing
      color: presencePill.hovered ? Util.alpha(root.green, 0.35)
        : root.flashOn ? Util.alpha("white", 0.9)
        : root.presenceFlashing ? Util.alpha(root.green, 0.55)
        : root.presenceAmber
      border.width: 1
      border.color: presencePill.hovered || root.presenceFlashing ? root.green : Qt.lighter(root.presenceAmber, 1.3)
      Behavior on color { ColorAnimation { duration: 150 } }

      // Breathing, while it waits for an answer.
      SequentialAnimation on opacity {
        running: root.presenceWanted && presenceBg.calm
        loops: Animation.Infinite
        NumberAnimation { to: 0.6; duration: 650; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1.0; duration: 650; easing.type: Easing.InOutSine }
        onRunningChanged: if (!running) presenceBg.opacity = 1
      }
    }

    Text {
      id: presenceText
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: "Still there?"
      color: presencePill.hovered ? root.green
        : root.flashOn || presenceBg.calm ? "#1a1b26" : root.green
      font: presenceMetrics.font
    }

    // A little shake every few seconds, like a tap on the shoulder.
    SequentialAnimation {
      running: root.presenceWanted && !presencePill.hovered && root.presenceShown >= 1
      loops: Animation.Infinite
      PauseAnimation { duration: 2600 }
      NumberAnimation { target: presenceText; property: "anchors.horizontalCenterOffset"; to: -3; duration: 60 }
      NumberAnimation { target: presenceText; property: "anchors.horizontalCenterOffset"; to: 3; duration: 90 }
      NumberAnimation { target: presenceText; property: "anchors.horizontalCenterOffset"; to: -2; duration: 80 }
      NumberAnimation { target: presenceText; property: "anchors.horizontalCenterOffset"; to: 0; duration: 70 }
    }

    MouseArea {
      id: presenceArea
      anchors.fill: parent
      enabled: root.presenceWanted
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: p.confirmPresence()
    }
  }

  // ---- extension challenge offer: a pill that unrolls after the timer.
  // Hovered, it splits in two: a red cross to decline, a green check to
  // accept. Horizontal bars only.

  readonly property string crossGlyph: String.fromCodePoint(0xF0156)
  readonly property string trophyGlyph: String.fromCodePoint(0xF0538)
  readonly property bool pillWanted: p.challengeOffered && !root.vertical

  // 0 -> 1 as the pill draws itself in, and back when it goes.
  property real pillShown: pillWanted ? 1 : 0
  Behavior on pillShown { NumberAnimation { duration: 450; easing.type: Easing.OutCubic } }

  TextMetrics {
    id: pillMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
    text: pillLabel.text
  }

  Item {
    id: pill
    anchors.left: presencePill.width > 0 ? presencePill.right : button.right
    anchors.leftMargin: Style.space(2)
    anchors.verticalCenter: button.verticalCenter
    readonly property real fullWidth: pillMetrics.advanceWidth + Style.space(22)
    width: Math.round(fullWidth * root.pillShown)
    height: Math.round(button.height * 0.62)
    visible: width > 0
    clip: true

    readonly property bool hovered: pillArea.containsMouse
    readonly property bool onAccept: pillArea.mouseX >= width / 2

    Rectangle {
      anchors.fill: parent
      radius: height / 2
      color: Util.alpha(root.gold, 0.16)
      border.width: 1
      border.color: Util.alpha(root.gold, 0.6)
    }

    // At rest: the question.
    Text {
      id: pillLabel
      anchors.centerIn: parent
      width: pill.fullWidth - Style.space(22)
      horizontalAlignment: Text.AlignHCenter
      opacity: pill.hovered ? 0 : 1
      textFormat: Text.PlainText
      text: !p.challenge ? ""
        : "Challenge " + (p.challenge.index || 1) + "/" + (p.challenge.max || 3) + ": "
          + p.challenge.minutes + " more min, +" + p.challenge.xp + " XP?"
      color: root.gold
      font: pillMetrics.font
      Behavior on opacity { NumberAnimation { duration: 120 } }
    }

    // Hovered: decline on the left, accept on the right.
    Row {
      anchors.fill: parent
      opacity: pill.hovered ? 1 : 0
      Behavior on opacity { NumberAnimation { duration: 120 } }

      Rectangle {
        width: parent.width / 2
        height: parent.height
        radius: height / 2
        color: Util.alpha(root.red, pill.hovered && !pill.onAccept ? 0.35 : 0.14)

        Text {
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: root.crossGlyph
          color: root.red
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
        }
      }

      Rectangle {
        width: parent.width / 2
        height: parent.height
        radius: height / 2
        color: Util.alpha(root.green, pill.hovered && pill.onAccept ? 0.35 : 0.14)

        Text {
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: root.checkGlyph
          color: root.green
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
        }
      }
    }

    MouseArea {
      id: pillArea
      anchors.fill: parent
      enabled: root.pillWanted
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: function(mouse) {
        if (mouse.x >= pill.width / 2) p.acceptChallenge()
        else p.declineChallenge()
      }
    }
  }

  // ---- toasts: short messages that unroll after the timer for a few
  // seconds (session recap, challenge won, goal reached, errors), one at a
  // time. They replace desktop notifications.

  property var toastQueue: []
  property var currentToast: null   // { kind, title, text }

  function showToast(kind, title, text, rarity) {
    toastQueue = toastQueue.concat([{ kind: kind, title: title, text: text, rarity: rarity || "" }])
    if (!currentToast) nextToast()
  }

  function nextToast() {
    if (toastQueue.length === 0) { currentToast = null; return }
    currentToast = toastQueue[0]
    toastQueue = toastQueue.slice(1)
    if (currentToast.kind === "achievement" && !root.vertical) {
      achPill.play()            // its own show, ten seconds, then it closes itself
      return
    }
    toastTimer.interval = 6000
    toastTimer.restart()
  }

  function toastColor(kind, rarity) {
    if (kind === "achievement" && rarity) return root.rarityColor(rarity)
    return kind === "error" || kind === "absent" ? root.red : kind === "ended" ? root.green : root.gold
  }

  // Achievement rarity: normal, common (green), rare (blue), epic (purple),
  // legendary (gold, and it shines).
  readonly property color commonColor: "#5fd068"
  readonly property color rareColor: "#4ea5ff"
  readonly property color epicColor: "#b77cff"
  readonly property color legendaryColor: "#ffc93c"
  function rarityColor(r) {
    return r === "common" ? commonColor : r === "rare" ? rareColor : r === "epic" ? epicColor
      : r === "legendary" ? legendaryColor : root.fg
  }

  Timer {
    id: toastTimer
    interval: 6000
    onTriggered: {
      root.toastShown = 0
      toastGap.restart()
    }
  }
  // Lets the pill roll back up before the next one draws in.
  Timer { id: toastGap; interval: 500; onTriggered: root.nextToast() }

  property real toastShown: 0
  onCurrentToastChanged: toastShown = currentToast && !root.vertical && currentToast.kind !== "achievement" ? 1 : 0
  Behavior on toastShown { NumberAnimation { duration: 450; easing.type: Easing.OutCubic } }

  TextMetrics {
    id: toastMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
    text: toastLabel.text
  }

  Item {
    id: toastPill
    anchors.left: pill.width > 0 ? pill.right : button.right
    anchors.leftMargin: Style.space(4)
    anchors.verticalCenter: button.verticalCenter
    readonly property real fullWidth: toastMetrics.advanceWidth + Style.space(22)
    readonly property color tint: root.currentToast ? root.toastColor(root.currentToast.kind, root.currentToast.rarity) : root.gold
    width: Math.round(fullWidth * root.toastShown)
    height: Math.round(button.height * 0.62)
    visible: width > 0
    clip: true

    Rectangle {
      anchors.fill: parent
      radius: height / 2
      color: Util.alpha(toastPill.tint, 0.16)
      border.width: 1
      border.color: Util.alpha(toastPill.tint, 0.6)
    }

    Text {
      id: toastLabel
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: !root.currentToast ? ""
        : (root.currentToast.kind === "achievement" ? root.trophyGlyph + "  " : "")
          + root.currentToast.title + (root.currentToast.text ? "  ·  " + root.currentToast.text : "")
      color: toastPill.tint
      font: toastMetrics.font
    }

    // A click dismisses it early.
    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: { toastTimer.stop(); toastTimer.triggered() }
    }
  }

  // ---- share: the card is grabbed (in the panel) frame by frame, ffmpeg
  // makes an animated PNG of the frames, then a save dialog asks where it
  // goes, and it is copied there.
  readonly property string shareTemp: Quickshell.env("XDG_RUNTIME_DIR") + "/prometheus-share.png"
  readonly property int shareFrames: 24          // one loop of every shine
  readonly property real shareScale: 1.5         // 900 px wide: sharp, still light
  function shareFrame(k) {
    return Quickshell.env("XDG_RUNTIME_DIR") + "/prometheus-share-" + (k < 10 ? "0" : "") + k + ".png"
  }

  function encodeShare() {
    encodeProc.command = ["ffmpeg", "-loglevel", "error", "-y", "-framerate", "12",
      "-i", Quickshell.env("XDG_RUNTIME_DIR") + "/prometheus-share-%02d.png",
      "-plays", "0", "-f", "apng", root.shareTemp]
    encodeProc.running = true
  }

  Process {
    id: encodeProc
    onExited: function(code) {
      if (code === 0) root.askWhereToSave()
      else root.showToast("error", "Could not make the animated card", "ffmpeg failed", "")
    }
  }
  property string shareTarget: ""

  function askWhereToSave() {
    var day = Qt.formatDate(new Date(), "yyyy-MM-dd")
    saveDialog.command = ["zenity", "--file-selection", "--save", "--confirm-overwrite",
      "--title=Save your Prometheus card", "--file-filter=PNG image | *.png",
      "--filename=" + Quickshell.env("HOME") + "/Pictures/prometheus-" + day + ".png"]
    saveDialog.running = true
  }

  Process {
    id: saveDialog
    stdout: StdioCollector {
      onStreamFinished: {
        var path = text.trim()
        if (path === "") return               // cancelled
        if (!/\.png$/i.test(path)) path += ".png"
        root.shareTarget = path
        copyShare.command = ["cp", "-f", root.shareTemp, path]
        copyShare.running = true
      }
    }
  }

  Process {
    id: copyShare
    onExited: function(code) {
      if (code === 0) root.showToast("ended", "Card saved", root.shareTarget, "")
      else root.showToast("error", "Could not save the card", root.shareTarget, "")
    }
  }

  // ---- achievement unlocked: a capsule of the rarity's color. It snaps open,
  // flashes white to catch the eye, then glows with a light sweeping across it
  // (and a rainbow sheen if legendary) for thirty seconds, then closes up like a
  // pill: down to a round dot, which shrinks away.

  TextMetrics {
    id: achMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
    text: achLabel.text
  }

  Item {
    id: achPill
    readonly property bool active: !!root.currentToast && root.currentToast.kind === "achievement"
    readonly property string rarity: active ? (root.currentToast.rarity || "normal") : "normal"
    readonly property color tint: rarity === "normal" ? root.gold : root.rarityColor(rarity)
    readonly property real fullWidth: achMetrics.advanceWidth + Style.space(30)
    property real openWidth: 0
    property bool flashOn: false
    anchors.left: pill.width > 0 ? pill.right : button.right
    anchors.leftMargin: Style.space(4)
    anchors.verticalCenter: button.verticalCenter
    width: Math.round(openWidth)
    height: Math.round(button.height * 0.78)
    visible: openWidth > 0.5
    transformOrigin: Item.Center

    function play() {
      closeAnim.stop()
      scale = 1
      opacity = 1
      openWidth = 0
      openAnim.restart()
    }
    function close() {
      if (!closeAnim.running && openWidth > 0) { openAnim.stop(); closeAnim.restart() }
    }

    SequentialAnimation {
      id: openAnim
      NumberAnimation { target: achPill; property: "openWidth"; from: 0; to: achPill.fullWidth; duration: 560; easing.type: Easing.OutBack; easing.overshoot: 1.6 }
      // Six quick flashes: look here.
      SequentialAnimation {
        loops: 6
        PropertyAction { target: achPill; property: "flashOn"; value: true }
        PauseAnimation { duration: 90 }
        PropertyAction { target: achPill; property: "flashOn"; value: false }
        PauseAnimation { duration: 90 }
      }
      PauseAnimation { duration: 30000 - 560 - 1080 }
      ScriptAction { script: achPill.close() }
    }

    SequentialAnimation {
      id: closeAnim
      // Closing up like a pill: the ends come together into a round dot...
      NumberAnimation { target: achPill; property: "openWidth"; to: achPill.height; duration: 320; easing.type: Easing.InCubic }
      // ...which pops away.
      ParallelAnimation {
        NumberAnimation { target: achPill; property: "scale"; to: 0; duration: 260; easing.type: Easing.InBack }
        NumberAnimation { target: achPill; property: "opacity"; to: 0; duration: 260 }
      }
      ScriptAction { script: { achPill.openWidth = 0; achPill.scale = 1; achPill.opacity = 1; toastGap.restart() } }
    }

    // The glow around it, breathing.
    Rectangle {
      anchors.centerIn: parent
      width: parent.width + Style.space(6)
      height: parent.height + Style.space(6)
      radius: height / 2
      color: "transparent"
      border.width: 2
      border.color: achPill.tint
      SequentialAnimation on opacity {
        running: achPill.visible
        loops: Animation.Infinite
        NumberAnimation { from: 0.15; to: 0.7; duration: 700; easing.type: Easing.InOutSine }
        NumberAnimation { from: 0.7; to: 0.15; duration: 700; easing.type: Easing.InOutSine }
      }
    }

    Rectangle {
      id: achBody
      anchors.fill: parent
      radius: height / 2
      clip: true
      color: achPill.flashOn ? "white" : achPill.tint
      border.width: 1
      border.color: Qt.lighter(achPill.tint, 1.4)

      // Legendary: a rainbow sheen drifting across the gold.
      Rectangle {
        visible: achPill.rarity === "legendary"
        width: achBody.width * 3
        height: achBody.height
        opacity: 0.28
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0.00; color: "#ff4d4d" }
          GradientStop { position: 0.17; color: "#ffd24d" }
          GradientStop { position: 0.33; color: "#6dff6d" }
          GradientStop { position: 0.50; color: "#4de1ff" }
          GradientStop { position: 0.67; color: "#6d6dff" }
          GradientStop { position: 0.83; color: "#ff6dff" }
          GradientStop { position: 1.00; color: "#ff4d4d" }
        }
        NumberAnimation on x {
          running: achPill.visible && achPill.rarity === "legendary"
          loops: Animation.Infinite
          from: -achBody.width * 2; to: 0; duration: 2600
        }
      }

      // The shine: a bright diagonal band sweeping across, again and again.
      Rectangle {
        width: Math.max(14, achBody.height * 1.3)
        height: achBody.height * 3
        anchors.verticalCenter: parent.verticalCenter
        rotation: 25
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0.0; color: "#00ffffff" }
          GradientStop { position: 0.5; color: "#d0ffffff" }
          GradientStop { position: 1.0; color: "#00ffffff" }
        }
        SequentialAnimation on x {
          running: achPill.visible
          loops: Animation.Infinite
          NumberAnimation { from: -achBody.height * 2; to: achBody.width + achBody.height; duration: 900; easing.type: Easing.InOutQuad }
          PauseAnimation { duration: 900 }
        }
      }
    }

    Text {
      id: achLabel
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: !achPill.active ? ""
        : root.trophyGlyph + "  " + (achPill.rarity !== "normal" ? achPill.rarity.toUpperCase() + "  ·  " : "")
          + root.currentToast.title + (root.currentToast.text ? "  ·  " + root.currentToast.text : "")
      color: achPill.flashOn ? achPill.tint : "#14151f"
      font: achMetrics.font
      opacity: achPill.openWidth >= achPill.fullWidth * 0.6 ? 1 : 0
      Behavior on opacity { NumberAnimation { duration: 120 } }
    }

    // A click closes it early.
    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: achPill.close()
    }
  }

  // ---- panel, built only while open (and through its fade-out)

  Timer {
    id: lingerTimer
    interval: 400
  }

  onPanelOpenChanged: if (!panelOpen) lingerTimer.restart()

  Loader {
    id: panelLoader
    active: root.panelOpen || lingerTimer.running
    sourceComponent: panelComponent
  }

  Component {
    id: panelComponent

    KeyboardPanel {
      id: panel
      anchorItem: button
      owner: root
      bar: root.bar
      // Created already open, the panel would never see `open` change, and
      // that change is what registers it with the bar's popout coordinator.
      // Arm it one tick after creation instead.
      property bool armed: false
      open: armed && root.panelOpen
      centerOnBar: true
      focusTarget: keyCatcher
      // At least as wide as the tab row, so no tab is clipped.
      contentWidth: panel.fittedContentWidth(Math.max(Style.space(380), Math.max(tabRow.implicitWidth, tabRow2.implicitWidth) + panel.padding * 2 + Style.space(16)))
      contentHeight: panel.fittedContentHeight(column.implicitHeight)

      // Two rows: the day's work and the competition on top, records and
      // settings below.
      readonly property var workTabs: [
        { value: "session", label: "Session" },
        { value: "tasks", label: "Tasks", tooltip: p.session ? "" : "Available during a session" },
        { value: "quests", label: "Quests" },
        { value: "leagues", label: "Leagues" },
        { value: "seasons", label: "Seasons" }
      ]
      readonly property var progressTabs: [
        { value: "achievements", label: "Achievements" },
        { value: "stats", label: "Stats" },
        { value: "leaderboard", label: "Leaderboards" },
        { value: "settings", label: "Settings" }
      ]
      readonly property var tabs: workTabs.concat(progressTabs)
      readonly property var current: root.tab === "tasks" ? tasksTab
        : root.tab === "quests" ? questsTab
        : root.tab === "leagues" ? leaguesTab
        : root.tab === "seasons" ? seasonsTab
        : root.tab === "leaderboard" ? leaderboardTab
        : root.tab === "stats" ? statsTab
        : root.tab === "achievements" ? achievementsTab
        : root.tab === "settings" ? settingsTab
        : sessionTab
      readonly property bool editing: sessionTab.editing || tasksTab.editing || questsTab.editing

      Component.onCompleted: Qt.callLater(function() { panel.armed = true })

      onOpenChanged: if (open) Qt.callLater(panel.focusContent)

      function focusContent() {
        if (!panel.open) return
        if (!(panel.current && panel.current.focusEntry())) keyCatcher.forceActiveFocus()
      }

      // The card is captured frame by frame, every shine a step further, then
      // ffmpeg folds the frames into an animated PNG that loops.
      function share() {
        p.call("share:get", [], function(ok, d) {
          if (!ok || !d || !d.success) { root.showToast("error", "Could not build the card", "", ""); return }
          shareCard.info = d
          root.showToast("ended", "Building your card", "a few seconds", "")
          Qt.callLater(function() { panel.grabFrame(0) })
        })
      }

      function grabFrame(k) {
        if (k >= root.shareFrames) { root.encodeShare(); return }
        shareCard.frame = k / root.shareFrames
        Qt.callLater(function() {
          shareCard.grabToImage(function(result) {
            if (!result.saveToFile(root.shareFrame(k))) {
              root.showToast("error", "Could not render the card", "", "")
              return
            }
            panel.grabFrame(k + 1)
          }, Qt.size(Math.round(shareCard.width * root.shareScale), Math.round(shareCard.height * root.shareScale)))
        })
      }

      function cycleTab(step) {
        var i = 0
        for (var k = 0; k < tabs.length; k++) if (tabs[k].value === root.tab) i = k
        root.tab = tabs[(i + step + tabs.length) % tabs.length].value
        Qt.callLater(panel.focusContent)
      }

      PanelKeyCatcher {
        id: keyCatcher
        anchors.fill: parent
        blocked: panel.editing
        onCloseRequested: root.close()
        onTabRequested: function(direction) { panel.cycleTab(direction) }
        onMoveRequested: function(dx, dy) { if (dx !== 0) panel.cycleTab(dx) }
        onActivateRequested: {
          if (root.tab === "session" && p.session) p.toggle()
          else panel.focusContent()
        }

        // A bookmark hangs from the top edge while a quest is active,
        // like a ribbon left in a book.
        Item {
          id: bookmark
          visible: !!p.quest
          // The active quest's own color.
          readonly property color tint: p.quest && p.quest.color ? p.quest.color : root.red
          z: 5
          width: Style.space(14)
          height: Style.space(30)
          anchors.right: parent.right
          anchors.rightMargin: Style.space(6)
          anchors.top: parent.top
          anchors.topMargin: -panel.padding - 2

          Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
              strokeWidth: 0
              fillColor: bookmark.tint
              startX: 0; startY: 0
              PathLine { x: bookmark.width; y: 0 }
              PathLine { x: bookmark.width; y: bookmark.height }
              PathLine { x: bookmark.width / 2; y: bookmark.height - bookmark.width * 0.45 }
              PathLine { x: 0; y: bookmark.height }
              PathLine { x: 0; y: 0 }
            }
          }

          // A darker fold down the middle gives it some depth.
          Rectangle {
            x: bookmark.width * 0.2
            width: 1
            height: bookmark.height - bookmark.width * 0.6
            color: Qt.darker(bookmark.tint, 1.35)
            opacity: 0.6
          }

          // A click puts the quest aside (it stays in the list).
          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: if (p.quest) p.act("quests:deactivate", [p.quest.id], "Quest")
          }
        }

        // The share card, laid out off to the side: only grabbed, never seen.
        ShareCard {
          id: shareCard
          x: -20000
          w: root
        }

        // Flying "+N XP" labels, above the panel content.
        Item {
          id: fxLayer
          anchors.fill: parent
          z: 20
        }

        Component {
          id: xpFlyer

          Text {
            id: flyer
            property real fromX: 0
            property real fromY: 0
            property real toX: 0
            property real toY: 0
            x: fromX
            y: fromY
            textFormat: Text.PlainText
            color: root.gold
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
            style: Text.Outline
            styleColor: Util.alpha("black", 0.5)

            SequentialAnimation {
              running: true
              // A little hop, then an arc up into the bar, shrinking.
              ParallelAnimation {
                NumberAnimation { target: flyer; property: "y"; to: flyer.fromY - Style.space(14); duration: 180; easing.type: Easing.OutQuad }
                NumberAnimation { target: flyer; property: "scale"; from: 0.6; to: 1.35; duration: 180; easing.type: Easing.OutBack }
              }
              ParallelAnimation {
                NumberAnimation { target: flyer; property: "x"; to: flyer.toX; duration: 650; easing.type: Easing.InOutCubic }
                NumberAnimation { target: flyer; property: "y"; to: flyer.toY; duration: 650; easing.type: Easing.InBack }
                NumberAnimation { target: flyer; property: "scale"; to: 0.5; duration: 650; easing.type: Easing.InQuad }
                NumberAnimation { target: flyer; property: "opacity"; to: 0.2; duration: 650; easing.type: Easing.InQuad }
              }
              ScriptAction { script: { xpPulse.restart(); flyer.destroy() } }
            }
          }
        }

        Connections {
          target: root
          function onXpGained(source, xp) {
            if (!source || xp <= 0) return
            var from = source.mapToItem(fxLayer, source.width / 2, source.height / 2)
            var target = xpFill.mapToItem(fxLayer, xpFill.width, xpFill.height / 2)
            var f = xpFlyer.createObject(fxLayer, { text: "+" + xp + " XP" })
            f.fromX = from.x - f.implicitWidth / 2
            f.fromY = from.y - f.implicitHeight / 2
            f.toX = Math.max(0, target.x - f.implicitWidth / 2)
            f.toY = target.y - f.implicitHeight / 2
          }
        }

        Flickable {
          id: scroller
          anchors.fill: parent
          contentWidth: width
          contentHeight: column.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          interactive: contentHeight > height

          Column {
            id: column
            width: scroller.width
            spacing: Style.space(12)

            // ---- header
            Item {
              width: parent.width
              height: title.implicitHeight

              // Share: a PNG of the profile, medals and seasons.
              Text {
                id: shareButton
                anchors.left: title.right
                anchors.leftMargin: Style.space(10)
                anchors.verticalCenter: title.verticalCenter
                textFormat: Text.PlainText
                text: String.fromCodePoint(0xF0497) + "  share"
                color: shareArea.containsMouse ? root.accent : Util.alpha(root.fg, 0.5)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption

                MouseArea {
                  id: shareArea
                  anchors.fill: parent
                  anchors.margins: -Style.space(4)
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: panel.share()
                }
              }

              Text {
                id: title
                anchors.left: parent.left
                textFormat: Text.PlainText
                text: "PROMETHEUS"
                color: p.running ? root.accent : root.fg
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 2
              }

              Text {
                anchors.right: parent.right
                anchors.rightMargin: p.quest ? bookmark.width + Style.space(10) : 0
                anchors.verticalCenter: title.verticalCenter
                textFormat: Text.PlainText
                visible: p.session !== null && root.tab !== "session"
                text: root.fireGlyph + "  " + p.formatDuration(p.elapsed)
                color: p.paused ? Util.alpha(root.fg, 0.5) : root.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
            }

            // ---- the active quest, wrapped when long; a click opens the Quests tab
            Item {
              width: parent.width - (p.quest ? bookmark.width + Style.space(10) : 0)
              height: questLines.implicitHeight
              visible: !!p.quest

              Column {
                id: questLines
                width: parent.width
                spacing: Style.space(1)

                Text {
                  width: parent.width
                  wrapMode: Text.Wrap
                  textFormat: Text.PlainText
                  text: p.quest ? p.quest.title : ""
                  // The quest's own color; dimmed once done for the day.
                  color: !p.quest ? root.fg : p.quest.doneToday ? Util.alpha(p.quest.color, 0.5) : p.quest.color
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.strikeout: !!p.quest && !!p.quest.doneToday
                }

                Text {
                  width: parent.width
                  wrapMode: Text.Wrap
                  textFormat: Text.PlainText
                  text: !p.quest ? ""
                    : p.quest.kind === "daily"
                      ? "Daily quest" + (p.quest.doneToday ? "  ·  done today" : p.quest.streak > 0 ? "  ·  " + p.quest.streak + " in a row" : "")
                      : (p.quest.kind === "long" ? "Long quest" : "Short quest") + "  ·  day " + Math.max(1, p.quest.daysWorked)
                        + "  ·  " + p.quest.xp + " XP"
                  color: Util.alpha(root.red, 0.85)
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.tab = "quests"
              }
            }

            // ---- level: XP total and progress to the next level
            Column {
              width: parent.width
              spacing: Style.space(4)
              visible: !!p.profile

              Item {
                width: parent.width
                height: levelText.implicitHeight

                Text {
                  id: levelText
                  anchors.left: parent.left
                  textFormat: Text.PlainText
                  text: p.profile ? "Level " + p.profile.level : ""
                  color: root.gold
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                }

                Text {
                  anchors.right: parent.right
                  anchors.verticalCenter: levelText.verticalCenter
                  textFormat: Text.PlainText
                  text: p.profile ? p.profile.levelXp + " / " + p.profile.levelCost + " XP  ·  " + p.profile.xp + " total" : ""
                  color: Util.alpha(root.fg, 0.6)
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              Rectangle {
                id: xpBar
                width: parent.width
                height: Style.space(5)
                radius: height / 2
                color: Util.alpha(root.fg, 0.12)

                Rectangle {
                  id: xpFill
                  height: parent.height
                  radius: parent.radius
                  width: p.profile ? parent.width * Math.min(1, p.profile.levelXp / Math.max(1, p.profile.levelCost)) : 0
                  color: root.gold
                  Behavior on width { NumberAnimation { duration: 700; easing.type: Easing.OutBack } }
                }

                // The pulse: a glow over the bar, flashing twice.
                Rectangle {
                  id: xpGlow
                  anchors.centerIn: parent
                  width: parent.width + Style.space(6)
                  height: parent.height + Style.space(6)
                  radius: height / 2
                  color: "transparent"
                  border.width: Style.space(2)
                  border.color: root.gold
                  opacity: 0
                }

                SequentialAnimation {
                  id: xpPulse
                  loops: 2
                  ParallelAnimation {
                    NumberAnimation { target: xpGlow; property: "opacity"; to: 0.9; duration: 120; easing.type: Easing.OutQuad }
                    ColorAnimation { target: xpFill; property: "color"; to: "white"; duration: 120 }
                  }
                  ParallelAnimation {
                    NumberAnimation { target: xpGlow; property: "opacity"; to: 0; duration: 380; easing.type: Easing.InQuad }
                    ColorAnimation { target: xpFill; property: "color"; to: root.gold; duration: 380 }
                  }
                }
              }
            }

            // ---- medals: the ribbon placard, like on an officer's jacket.
            // Rows of up to 6, centered; the line under it describes the
            // ribbon under the mouse.
            Column {
              id: placard
              width: parent.width
              spacing: Style.space(3)
              visible: all.length > 0
              property string hovered: ""
              // Season medals first, on their own row: permanent, and shining.
              readonly property var all: p.seasonMedals.concat(p.medals)

              readonly property int perRow: 6

              function legendFor(m) {
                if (m.period === "season") return m.name + " · " + m.desc + " · kept for good"
                return m.name + (m.count > 1 ? " ×" + m.count : "") + " · " + m.desc
                  + (m.current ? " · won " + (m.period === "day" ? "today" : m.period === "week" ? "this week" : "this month") : "")
              }

              // The legend's reserved height: the tallest of all possible
              // legends, wrapped at the panel width. Measured off-screen.
              property real legendHeight: 0
              function measureLegends() {
                var h = 0
                for (var i = 0; i < legendProbe.count; i++) {
                  var it = legendProbe.itemAt(i)
                  if (it) h = Math.max(h, it.implicitHeight)
                }
                legendHeight = h
              }
              // Monthly, weekly then daily medals (the daemon's order), each
              // group on its own rows; a small gap opens between groups.
              readonly property var rows: {
                var out = [], list = placard.all, groups = ["season", "month", "week", "day"]
                for (var g = 0; g < groups.length; g++) {
                  var items = list.filter(function(m) { return m.period === groups[g] })
                  for (var i = 0; i < items.length; i += perRow)
                    out.push({ items: items.slice(i, i + perRow), newGroup: i === 0 && out.length > 0 })
                }
                return out
              }

              Repeater {
                model: placard.rows

                Item {
                  id: placardRow
                  required property var modelData
                  width: placard.width
                  height: ribbonRow.implicitHeight + (modelData.newGroup ? Style.space(5) : 0)

                Row {
                  id: ribbonRow
                  anchors.horizontalCenter: parent.horizontalCenter
                  anchors.bottom: parent.bottom
                  spacing: Style.space(2)

                  Repeater {
                    model: placardRow.modelData.items

                    Item {
                      id: medal
                      required property var modelData
                      readonly property bool season: modelData.period === "season"
                      implicitWidth: season ? seasonBars.implicitWidth : plain.implicitWidth
                      implicitHeight: season ? seasonBars.implicitHeight : plain.implicitHeight

                      Ribbon {
                        id: plain
                        visible: !medal.season
                        size: 1.15
                        color: medal.modelData.color
                        dot: medal.modelData.dot
                        dots: medal.modelData.dots || 1
                        edges: medal.modelData.edges || "none"
                        opacity: medal.modelData.current ? 1 : 0.75
                      }

                      // An edge bar on the left for the season goal, on
                      // both sides for the hard one.
                      HoloRibbon {
                        id: seasonBars
                        visible: medal.season
                        size: 1.15
                        color: medal.season ? medal.modelData.color : "#555"
                        dot: medal.season ? medal.modelData.dot : "white"
                        edge: medal.season ? medal.modelData.edge : "#999"
                        edges: medal.season && medal.modelData.bars === 2 ? "both" : "left"
                      }

                      MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        onEntered: placard.hovered = placard.legendFor(medal.modelData)
                        onExited: placard.hovered = ""
                      }
                    }
                  }
                }
                }
              }

              // Hidden probes, one per legend, to size the reserved space.
              Item {
                width: parent.width
                height: 0
                visible: false

                Repeater {
                  id: legendProbe
                  model: placard.all

                  Text {
                    required property var modelData
                    width: placard.width
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    textFormat: Text.PlainText
                    text: placard.legendFor(modelData)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    onImplicitHeightChanged: Qt.callLater(placard.measureLegends)
                  }
                }
              }

              // Always laid out, as tall as the longest legend: the space
              // stays reserved, so the panel does not jump on hover.
              Text {
                width: parent.width
                height: Math.max(implicitHeight, placard.legendHeight)
                wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignTop
                horizontalAlignment: Text.AlignHCenter
                textFormat: Text.PlainText
                text: placard.hovered !== "" ? placard.hovered : " "
                color: Util.alpha(root.fg, 0.6)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }

            Column {
              anchors.horizontalCenter: parent.horizontalCenter
              spacing: Style.space(6)

              ButtonGroup {
                id: tabRow
                anchors.horizontalCenter: parent.horizontalCenter
                options: panel.workTabs
                value: root.tab
                foreground: root.fg
                accent: root.accent
                fontFamily: root.fontFamily
                fontSize: Style.font.caption
                focusable: false
                onChanged: function(v) {
                  root.tab = v
                  Qt.callLater(panel.focusContent)
                }
              }

              ButtonGroup {
                id: tabRow2
                anchors.horizontalCenter: parent.horizontalCenter
                options: panel.progressTabs
                value: root.tab
                foreground: root.fg
                accent: root.accent
                fontFamily: root.fontFamily
                fontSize: Style.font.caption
                focusable: false
                onChanged: function(v) {
                  root.tab = v
                  Qt.callLater(panel.focusContent)
                }
              }
            }

            PanelSeparator { width: parent.width; foreground: root.fg }

            SessionTab { id: sessionTab; width: parent.width; w: root; p: root.client; visible: root.tab === "session" }
            TasksTab { id: tasksTab; width: parent.width; w: root; p: root.client; o: root.journal; visible: root.tab === "tasks" }
            QuestsTab { id: questsTab; width: parent.width; w: root; p: root.client; visible: root.tab === "quests" }
            StatsTab { id: statsTab; width: parent.width; w: root; p: root.client; visible: root.tab === "stats" }
            AchievementsTab { id: achievementsTab; width: parent.width; w: root; p: root.client; visible: root.tab === "achievements" }
            LeaguesTab { id: leaguesTab; width: parent.width; w: root; p: root.client; visible: root.tab === "leagues" }
            SeasonsTab { id: seasonsTab; width: parent.width; w: root; p: root.client; visible: root.tab === "seasons" }
            LeaderboardTab { id: leaderboardTab; width: parent.width; w: root; p: root.client; visible: root.tab === "leaderboard" }
            SettingsTab { id: settingsTab; width: parent.width; w: root; p: root.client; visible: root.tab === "settings" }

            PanelSeparator { width: parent.width; foreground: root.fg }

            // ---- footer
            Item {
              width: parent.width
              height: journalButton.implicitHeight

              Text {
                anchors.left: parent.left
                anchors.right: journalButton.left
                anchors.rightMargin: Style.space(8)
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: p.idle ? "Idle: time is not counted" : p.window ? "Tracking: " + (p.window.app || "?") : ""
                color: Util.alpha(root.fg, 0.5)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
              }

              Button {
                id: journalButton
                anchors.right: parent.right
                text: "Daily note"
                foreground: root.fg
                accent: root.accent
                onClicked: {
                  root.openJournal()
                  root.close()
                }
              }
            }
          }
        }
      }
    }
  }
}
