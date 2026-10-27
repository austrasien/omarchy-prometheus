import QtQuick
import QtQuick.Shapes
import Quickshell
import qs.Commons
import ".."

// Prometheus as a map of the minimap (austraz.minimap): installed by
// linking this folder as the minimap's maps/prometheus. Chosen in the
// minimap's list it shows the session like the bar: timer, task, a ring
// to the next XP (or the challenge's countdown). Whatever the minimap
// shows, Prometheus' toasts (achievements, medals, quests, challenges,
// session ends, the hours goal…) and its questions ("Still there?", the
// challenge offer, "Break?", "Coffee?") come up here as minimap
// notifications; the bar then leaves them to it (see BarWidget's
// minimapShows).
Item {
  id: view
  required property var minimap

  // A reader of the daemon like the bar, minus idle reporting (the bar
  // already does it; two would double the flips).
  Prometheus {
    id: p
    idleTimeout: 0
    onToast: function(kind, title, text, rarity, extra) {
      view.enqueue({ type: "toast", kind: kind, title: title, text: text, rarity: rarity,
                     recap: extra && extra.recap ? extra.recap : null,
                     // The pause after an unanswered "Still there?" waits for a resume.
                     persistent: kind === "absent" && title === "Session paused" && p.paused })
    }
  }

  // Level up: the daemon does not announce it; the profile tells.
  property int lastLevel: 0
  readonly property int level: p.profile ? (p.profile.level || 0) : 0
  onLevelChanged: {
    if (lastLevel > 0 && level > lastLevel) announceLevel(level)
    if (level > 0) lastLevel = level
  }
  function announceLevel(n) {
    var left = p.profile ? Math.max(0, (p.profile.levelCost || 0) - (p.profile.levelXp || 0)) : 0
    enqueue({ type: "toast", kind: "level", title: "Level " + n, text: left ? left + " XP to the next" : "" })
  }

  // ----------------------------------------------------------- style
  // The bar's colours and glyphs, so a toast looks the same here.

  readonly property color gold: "#e0af68"
  readonly property color green: "#9ece6a"
  readonly property color red: Color.urgent
  readonly property color presenceAmber: "#ffb020"
  readonly property color breakTeal: "#2ac3de"
  readonly property color coffeeBrown: "#c08552"
  function rarityColor(r) {
    return r === "common" ? "#5fd068" : r === "rare" ? "#4ea5ff" : r === "epic" ? "#b77cff"
      : r === "legendary" ? "#ffc93c" : Color.foreground
  }
  function toastColor(kind, rarity) {
    if (kind === "achievement" && rarity) return rarityColor(rarity)
    return kind === "error" || kind === "absent" ? red : kind === "ended" || kind === "level" ? green : gold
  }
  function glyph(code) { return String.fromCodePoint(code) }
  function toastGlyph(kind) {
    switch (kind) {
    case "achievement": return glyph(0xF0538)   // trophy
    case "medal": return glyph(0xF0987)         // medal
    case "quest": return glyph(0xF023B)         // flag
    case "won": return glyph(0xF0538)
    case "goal": return glyph(0xF012C)          // check
    case "ended": return glyph(0xF0238)         // fire
    case "absent": return glyph(0xF03E4)        // pause
    case "error": return glyph(0xF0026)         // alert
    default: return glyph(0xF0238)
    }
  }

  // ---------------------------------------------------- notifications
  //
  // Toasts, questions and announcements wait their turn; each asks the
  // minimap to show this map for as long as its text takes to go round.
  // What waits for the user stays until it is settled (the minimap's
  // persistent notifications): a question until answered, "Session
  // paused" until the session resumes, a league or season end until
  // clicked. Something new passes in front, then it comes back.

  readonly property int questionMs: 10000
  property var temps: []      // toasts, in turn
  property var stack: []      // what waits for the user, the latest last
  property var current: null

  function sameItem(a, b) {
    if (!a || !b || a.type !== b.type) return false
    if (a.type === "question") return a.question === b.question && !!a.demo === !!b.demo
    if (a.type === "announcement") return a.data.id === b.data.id
    if (a.type === "toast") return a === b
    return false
  }

  function enqueue(item) {
    if (item.persistent) {
      for (var i = 0; i < stack.length; i++) if (sameItem(stack[i], item)) return
      stack = stack.concat([item])
      minimap.notify(view, 0, true)
    } else {
      temps = temps.concat([item])
    }
    refresh()
  }

  // What shows: the first toast in turn, else the latest of what waits.
  function refresh() {
    var next = temps.length ? temps[0] : (stack.length ? stack[stack.length - 1] : null)
    if (next === current) return
    current = next
    ringText.stop()
    shownFor.stop()
    if (!current) { minimap.release(view); return }
    ringText.text = itemText(current)
    var ms = ringText.runMs + 700
    if (current.type === "question") ms = Math.max(questionMs, ms)
    shownFor.interval = ms
    shownFor.restart()
    if (!current.persistent) minimap.notify(view, ms)
    if (onScreen) ringText.start()
  }

  // Settled (answered, resumed, seen, or gone elsewhere): drop it; when
  // nothing waits any more, let the minimap go back.
  function settle(test) {
    temps = temps.filter(function(it) { return !test(it) })
    stack = stack.filter(function(it) { return !test(it) })
    if (!stack.length) minimap.release(view)
    if (current && test(current)) current = null
    refresh()
  }

  readonly property bool onScreen: minimap.shownMap === "prometheus"
  onOnScreenChanged: if (onScreen && current) ringText.start()

  function itemText(item) {
    if (item.type === "question") return questionText(item.question)
    if (item.type === "announcement") return announcementText(item.data)
    if (item.recap) return recapText(item)
    return item.title + (item.text ? "  ·  " + item.text : "")
  }

  Timer {
    id: shownFor
    onTriggered: {
      if (!view.current) return
      if (!view.current.persistent) {
        view.temps = view.temps.slice(1)
        view.current = null
        view.refresh()
        return
      }
      // Waiting for the user: its text goes round again.
      shownFor.restart()
      if (view.onScreen) ringText.start()
    }
  }

  // ---- questions, most urgent first, as the bar orders them
  readonly property var pendingQuestions: {
    var out = []
    if (p.presence) out.push("presence")
    if (p.challengeOffered) out.push("challenge")
    if (p.breakNudge) out.push("break")
    if (p.coffeeNudge) out.push("coffee")
    return out
  }
  onPendingQuestionsChanged: {
    for (var i = 0; i < pendingQuestions.length; i++)
      enqueue({ type: "question", question: pendingQuestions[i], persistent: true })
    settle(function(it) {
      return it.type === "question" && !it.demo && view.pendingQuestions.indexOf(it.question) === -1
    })
  }

  function answer(ok) {
    var q = current ? current.question : ""
    if (!current.demo) {
      if (q === "presence") p.confirmPresence()
      else if (q === "challenge") { if (ok) p.acceptChallenge(); else p.declineChallenge() }
      else if (q === "break") { if (ok) p.takeBreak(); else p.breakLater() }
      else if (q === "coffee") { if (ok) p.coffeeOk(); else p.coffeeNo() }
    }
    var answered = current
    settle(function(it) { return it === answered })
  }

  // ---- "Session paused" (no answer to "Still there?") stays until resumed
  readonly property bool paused: p.paused
  onPausedChanged: if (!paused) settle(function(it) { return it.type === "toast" && it.kind === "absent" && it.persistent })

  // ---- league and season ends, until clicked
  onAnnouncementsChanged: {
    for (var i = 0; i < announcements.length; i++)
      enqueue({ type: "announcement", data: announcements[i], persistent: true })
    settle(function(it) {
      if (it.type !== "announcement") return false
      for (var j = 0; j < view.announcements.length; j++) if (view.announcements[j].id === it.data.id) return false
      return true
    })
  }
  readonly property var announcements: p.announcements
  function acknowledge() {
    var seen = current
    p.call("announce:seen", [seen.data.id])
    settle(function(it) { return it === seen })
  }

  function minutes(sec) { return p.formatShort(sec) }
  function recapText(item) {
    var r = item.recap
    var parts = [item.title, r.task || "Session", "+" + (r.xp || 0) + " XP"]
    for (var i = 0; i < (r.apps || []).length; i++) parts.push(r.apps[i].app + " " + minutes(r.apps[i].seconds))
    if (r.agents && r.agents.tokens) {
      var k = r.agents.tokens >= 1000 ? Math.round(r.agents.tokens / 1000) + "k" : String(r.agents.tokens)
      parts.push(k + " tokens  ·  $" + Number(r.agents.cost || 0).toFixed(2))
    }
    return parts.join("  ·  ")
  }

  function announcementText(a) {
    if (a.kind === "league") {
      var move = a.outcome === "up" ? "promoted to " + a.after.name
        : a.outcome === "down" ? "relegated to " + a.after.name : "staying in " + a.after.name
      return "League round over  ·  " + move + "  ·  rank " + a.rank + "  ·  " + a.xp + " XP"
    }
    var medal = a.bars === 2 ? "two-bar medal: the hard goal, cleared"
      : a.bars === 1 ? "season medal: goal reached" : "no medal this time"
    return a.label + " is over  ·  grade " + (a.grade || "–") + "  ·  " + a.xp + " XP  ·  " + medal
  }

  function questionText(q) {
    if (q === "presence") return "Still there?"
    if (q === "challenge") {
      var c = p.challenge || { minutes: 15, xp: 15 }
      return "Challenge: " + c.minutes + " more min, +" + c.xp + " XP?"
    }
    if (q === "break") return "Break? " + (p.breakNudge ? p.breakNudge.reason : "you have been at it a while")
    if (q === "coffee") return "Coffee? " + (p.coffeeNudge ? p.coffeeNudge.reason : "now is a good time")
    return ""
  }
  function questionColor(q) {
    return q === "presence" ? presenceAmber : q === "challenge" ? gold : q === "break" ? breakTeal : coffeeBrown
  }
  function questionGlyph(q) {
    return q === "presence" ? glyph(0xF02D7)     // help circle
      : q === "challenge" ? glyph(0xF033E)       // lock
      : q === "break" ? glyph(0xF0176)           // cup
      : glyph(0xF0176)
  }

  // Demo: `omarchy-shell austraz.minimap demo prometheus <kind>`. Toast
  // kinds go through the daemon (toast:preview); questions are shown with
  // answers that do nothing.
  function demo(arg) {
    var a = String(arg || "")
    if (["presence", "challenge", "break", "coffee"].indexOf(a) !== -1)
      enqueue({ type: "question", question: a, demo: true, persistent: true })
    else if (a === "level") announceLevel(Math.max(2, level + 1))
    else if (["promoted", "relegated", "stayed"].indexOf(a) !== -1)
      p.call("announce:preview", ["league", a === "promoted" ? "up" : a === "relegated" ? "down" : "stay"])
    else if (["season0", "season1", "season2"].indexOf(a) !== -1) p.call("announce:preview", ["season", a.slice(6)])
    else if (a === "ended") enqueue({ type: "toast", kind: "ended", title: "Session ended", text: "",
      recap: { task: "Writing the report", durationSeconds: 5100, xp: 8,
               apps: [{ app: "Firefox", seconds: 2400 }, { app: "Code", seconds: 1800 }, { app: "Foot", seconds: 900 }],
               agents: { tokens: 12400, cost: 0.4 } } })
    else if (a === "medal" && p.medals && p.medals.length) {
      var m = p.medals[Math.floor(Math.random() * p.medals.length)]
      p.call("toast:echo", ["medal", m.name, "+20 XP · " + (m.desc || "")])
    } else p.call("toast:preview", [a || "legendary"])
  }

  // ------------------------------------------------------------- faces

  readonly property real w: width
  readonly property real k: minimap.uiScale || 1   // fixed sizes are for a 210 px minimap

  Rectangle {
    anchors.fill: parent
    color: Qt.darker(Color.background, 1.15)
  }

  // ---- status, when nothing is being announced
  Item {
    id: status
    anchors.fill: parent
    visible: view.current === null

    readonly property real ring: p.challengeActive
      ? (p.challenge.remainingSeconds || 0) / Math.max(1, (p.challenge.minutes || 15) * 60)
      : (p.session ? 1 - p.nextXpIn / Math.max(1, p.secondsPerXp) : 0)

    Shape {
      anchors.fill: parent
      visible: p.session !== null
      preferredRendererType: Shape.CurveRenderer
      ShapePath {
        strokeColor: Qt.alpha(Color.foreground, 0.08)
        strokeWidth: 5 * view.k
        fillColor: "transparent"
        PathAngleArc { centerX: view.w / 2; centerY: view.w / 2; radiusX: view.w / 2 - 4 * view.k; radiusY: radiusX; startAngle: 0; sweepAngle: 360 }
      }
      ShapePath {
        strokeColor: p.challengeActive ? view.red : view.gold
        strokeWidth: 5 * view.k
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        PathAngleArc {
          centerX: view.w / 2; centerY: view.w / 2
          radiusX: view.w / 2 - 4 * view.k; radiusY: radiusX
          startAngle: -90
          sweepAngle: 360 * status.ring
        }
      }
    }

    Column {
      anchors.centerIn: parent
      width: view.w * 0.72
      spacing: 2 * view.k

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: !p.live ? view.glyph(0xF0238) : p.paused ? view.glyph(0xF03E4) : view.glyph(0xF0238)
        color: !p.live ? Qt.alpha(Color.foreground, 0.3) : p.session && !p.paused ? view.gold : Qt.alpha(Color.foreground, 0.55)
        font.family: Style.fontFamily
        font.pixelSize: view.w * 0.14
      }
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: !p.live ? "offline" : p.session ? p.formatDuration(p.elapsed) : p.formatShort(p.todaySeconds)
        color: p.paused ? Qt.alpha(Color.foreground, 0.55) : Color.foreground
        font.family: Style.fontFamily
        font.pixelSize: view.w * (p.session ? 0.15 : 0.13)
        font.bold: true
      }
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        text: !p.live ? "prometheusd"
          : !p.session ? "today"
          : p.paused ? (p.autoPauseLabel ? "paused · " + p.autoPauseLabel : "paused")
          : (p.session.task || "Session")
        color: Qt.alpha(Color.foreground, 0.7)
        font.family: Style.fontFamily
        font.pixelSize: view.w * 0.07
      }
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: p.challengeActive || (p.session !== null && !p.paused)
        text: p.challengeActive
          ? view.glyph(0xF033E) + " " + Math.ceil((p.challenge.remainingSeconds || 0) / 60) + " min"
          : "+" + p.sessionXp + " XP"
        color: p.challengeActive ? view.red : view.gold
        font.family: Style.fontFamily
        font.pixelSize: view.w * 0.065
        font.bold: true
      }
    }

    // Click: pause the running session. With none running (none yet, or
    // paused) the halves below take the clicks instead.
    MouseArea {
      anchors.fill: parent
      enabled: p.live && !status.offering
      cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: {
        if (p.session) p.toggle()
        else Quickshell.execDetached(["omarchy-shell", "shell", "summon", "austraz.prometheus", "{}"])
      }
    }

    // Hovered with no session running (none yet, or paused), the disc
    // splits like a question: a coffee on the left, start or resume on the
    // right (a new session opens the bar's panel to be named first). The
    // halves slide in from their sides and light up under the
    // pointer; a coffee taken bounces its cup with "+1".
    readonly property bool offering: p.live && (!p.session || p.paused)
    readonly property bool hovered: offering && (coffeeArea.containsMouse || goArea.containsMouse)
    property real reveal: hovered ? 1 : 0
    Behavior on reveal { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    property bool poured: false
    Timer { id: pourTimer; interval: 1100; onTriggered: status.poured = false }

    Item {
      anchors.fill: parent
      visible: status.reveal > 0

      Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: Qt.darker(Color.background, 1.15)
        opacity: status.reveal
      }

      // Left: coffee.
      Item {
        x: -view.w / 2 * (1 - status.reveal)
        width: view.w / 2; height: view.w
        opacity: status.reveal
        Rectangle {
          anchors.fill: parent
          color: Qt.alpha(view.coffeeBrown, coffeeArea.containsMouse ? 0.3 : 0.1)
          Behavior on color { ColorAnimation { duration: 120 } }
        }
        Column {
          anchors.right: parent.right
          anchors.rightMargin: view.w * 0.07
          anchors.verticalCenter: parent.verticalCenter
          spacing: view.w * 0.015
          Text {
            id: cup
            anchors.horizontalCenter: parent.horizontalCenter
            text: view.glyph(0xF0176)
            color: coffeeArea.containsMouse || status.poured ? view.coffeeBrown : Qt.alpha(Color.foreground, 0.75)
            font.family: Style.fontFamily
            font.pixelSize: view.w * 0.15
            SequentialAnimation {
              id: pourBounce
              NumberAnimation { target: cup; property: "scale"; to: 1.35; duration: 90; easing.type: Easing.OutQuad }
              NumberAnimation { target: cup; property: "scale"; to: 1; duration: 380; easing.type: Easing.OutBack; easing.overshoot: 3 }
            }
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: status.poured ? "+1" : "Coffee"
            color: coffeeArea.containsMouse || status.poured ? view.coffeeBrown : Qt.alpha(Color.foreground, 0.75)
            font.family: Style.fontFamily
            font.pixelSize: Math.round(view.w * 0.075)
            font.bold: true
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: !!p.coffee && p.coffee.cupsToday > 0
            text: p.coffee ? p.coffee.cupsToday + " today" : ""
            color: Qt.alpha(Color.foreground, 0.5)
            font.family: Style.fontFamily
            font.pixelSize: Math.round(view.w * 0.055)
          }
        }
      }

      // Right: start a session, or resume the paused one.
      Item {
        x: view.w / 2 + view.w / 2 * (1 - status.reveal)
        width: view.w / 2; height: view.w
        opacity: status.reveal
        Rectangle {
          anchors.fill: parent
          color: Qt.alpha(view.green, goArea.containsMouse ? 0.3 : 0.1)
          Behavior on color { ColorAnimation { duration: 120 } }
        }
        Column {
          anchors.left: parent.left
          anchors.leftMargin: view.w * 0.07
          anchors.verticalCenter: parent.verticalCenter
          spacing: view.w * 0.015
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: view.glyph(0xF040A)
            color: goArea.containsMouse ? view.green : Qt.alpha(Color.foreground, 0.75)
            font.family: Style.fontFamily
            font.pixelSize: view.w * 0.15
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: p.session ? "Resume" : "Start"
            color: goArea.containsMouse ? view.green : Qt.alpha(Color.foreground, 0.75)
            font.family: Style.fontFamily
            font.pixelSize: Math.round(view.w * 0.075)
            font.bold: true
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: !!p.session
            text: p.session ? p.formatShort(p.elapsed) : ""
            color: Qt.alpha(Color.foreground, 0.5)
            font.family: Style.fontFamily
            font.pixelSize: Math.round(view.w * 0.055)
          }
        }
      }

      Rectangle {
        x: view.w / 2 - 0.5; y: view.w * 0.3; width: 1; height: view.w * 0.4
        color: Qt.alpha(Color.foreground, 0.25)
        opacity: status.reveal
      }
    }

    MouseArea {
      id: coffeeArea
      x: 0; width: view.w / 2; height: view.w
      enabled: status.offering
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: {
        p.addCoffee()
        status.poured = true
        pourTimer.restart()
        pourBounce.restart()
      }
    }
    MouseArea {
      id: goArea
      x: view.w / 2; width: view.w / 2; height: view.w
      enabled: status.offering
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      // A new session is named first: the bar's panel opens on its name
      // field. A paused one just resumes.
      onClicked: {
        if (p.session) p.resume()
        else Quickshell.execDetached(["omarchy-shell", "austraz.prometheus", "startSession"])
      }
    }
  }

  // ---- a toast, as in the bar: its kind's colour, glyph, title and text.
  // An achievement is the bar's achievement pill made round: solid in its
  // rarity's colour with dark text, a white flash as it lands, a pulsing
  // halo, a shine sweeping across, and a rainbow sheen when legendary.
  Item {
    id: toastFace
    anchors.fill: parent
    readonly property var t: view.current && view.current.type === "toast" && !view.current.recap ? view.current : null
    readonly property bool achievement: !!t && t.kind === "achievement"
    readonly property string rarity: achievement ? (t.rarity || "normal") : ""
    readonly property color tint: !t ? view.gold
      : achievement ? (rarity === "normal" ? view.gold : view.rarityColor(rarity))
      : view.toastColor(t.kind, t.rarity)
    readonly property color ink: achievement ? (flashOn ? tint : "#14151f") : tint
    readonly property bool levelUp: !!t && t.kind === "level"
    // The medal's look, found by name in the placard.
    readonly property var medal: {
      if (!t || t.kind !== "medal" || !p.medals) return null
      for (var i = 0; i < p.medals.length; i++) if (p.medals[i].name === t.title) return p.medals[i]
      return null
    }
    property bool flashOn: false
    visible: t !== null

    onTChanged: if (achievement) landing.restart()
    SequentialAnimation {
      id: landing
      PropertyAction { target: toastFace; property: "flashOn"; value: true }
      PauseAnimation { duration: 110 }
      PropertyAction { target: toastFace; property: "flashOn"; value: false }
      PauseAnimation { duration: 90 }
      PropertyAction { target: toastFace; property: "flashOn"; value: true }
      PauseAnimation { duration: 110 }
      PropertyAction { target: toastFace; property: "flashOn"; value: false }
    }

    // The face: tinted glass for most toasts, solid for an achievement.
    Rectangle {
      id: face
      anchors.fill: parent
      radius: width / 2
      clip: true
      color: !toastFace.achievement ? Qt.alpha(toastFace.tint, 0.14)
        : toastFace.flashOn ? "white" : toastFace.tint
      border.width: toastFace.achievement ? 0 : 3
      border.color: Qt.alpha(toastFace.tint, 0.7)

      // Legendary: a rainbow sheen drifting across the gold.
      Rectangle {
        visible: toastFace.rarity === "legendary"
        width: face.width * 3
        height: face.height
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
          running: toastFace.visible && toastFace.rarity === "legendary"
          loops: Animation.Infinite
          from: -face.width * 2; to: 0; duration: 2600
        }
      }

      // The shine: a bright diagonal band sweeping across, again and again.
      Rectangle {
        visible: toastFace.achievement
        width: face.width * 0.32
        height: face.height * 1.8
        y: -face.height * 0.4
        rotation: 25
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0.0; color: "#00ffffff" }
          GradientStop { position: 0.5; color: "#b0ffffff" }
          GradientStop { position: 1.0; color: "#00ffffff" }
        }
        SequentialAnimation on x {
          running: toastFace.visible && toastFace.achievement
          loops: Animation.Infinite
          NumberAnimation { from: -face.width * 0.6; to: face.width * 1.2; duration: 1100; easing.type: Easing.InOutQuad }
          PauseAnimation { duration: 900 }
        }
      }
    }

    // The halo, pulsing on the edge.
    Rectangle {
      visible: toastFace.achievement
      anchors.fill: parent
      anchors.margins: 3
      radius: width / 2
      color: "transparent"
      border.width: 2 * view.k
      border.color: Qt.lighter(toastFace.tint, 1.5)
      SequentialAnimation on opacity {
        running: toastFace.visible && toastFace.achievement
        loops: Animation.Infinite
        NumberAnimation { from: 0.15; to: 0.8; duration: 700; easing.type: Easing.InOutSine }
        NumberAnimation { from: 0.8; to: 0.15; duration: 700; easing.type: Easing.InOutSine }
      }
    }

    MouseArea {
      anchors.fill: parent
      enabled: !!toastFace.t && toastFace.t.persistent
      cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: p.resume()
    }

    // A medal: its own ribbon, as on the bar's placard, in the middle.
    Ribbon {
      anchors.centerIn: parent
      visible: !!toastFace.medal
      size: view.w / 60
      color: toastFace.medal ? toastFace.medal.color : "#555"
      dot: toastFace.medal ? toastFace.medal.dot : "white"
      dots: toastFace.medal ? (toastFace.medal.dots || 1) : 1
      edges: toastFace.medal ? (toastFace.medal.edges || "none") : "none"
    }

    Column {
      anchors.centerIn: parent
      width: view.w * 0.8
      spacing: 2 * view.k

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: !toastFace.medal && !toastFace.levelUp
        text: toastFace.t ? view.toastGlyph(toastFace.t.kind) : ""
        color: toastFace.ink
        font.family: Style.fontFamily
        font.pixelSize: view.w * 0.26
      }
      // Level up: green chevrons streaming up.
      Chevrons {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: toastFace.levelUp
        up: true
        color: view.green
        glyphSize: view.w * 0.22
      }
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: toastFace.levelUp
        text: toastFace.t ? toastFace.t.title.replace("Level ", "") : ""
        color: view.green
        font.family: Style.fontFamily
        font.pixelSize: view.w * 0.13
        font.bold: true
      }
      // RARE, EPIC… as the bar spells it.
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: toastFace.achievement && toastFace.rarity !== "normal"
        text: toastFace.rarity.toUpperCase()
        color: toastFace.ink
        opacity: 0.75
        font.family: Style.fontFamily
        font.pixelSize: Math.round(view.w * 0.06)
        font.bold: true
        font.letterSpacing: 2
      }
    }
  }

  // ---- a session end: the duration and the task in the middle, the apps
  // as arcs of the edge in proportion to their time, drawn one after the
  // other; grey when the session was put off.
  Item {
    id: recapFace
    anchors.fill: parent
    readonly property var t: view.current && view.current.recap ? view.current : null
    readonly property var r: t ? t.recap : null
    readonly property bool putOff: !!t && t.title === "Session put off"
    readonly property color tint: putOff ? Qt.alpha(Color.foreground, 0.5) : view.green
    readonly property var palette: ["#7aa2f7", "#e0af68", "#bb9af7", "#9ece6a", "#f7768e"]
    readonly property real total: {
      var n = 0
      if (r && r.apps) for (var i = 0; i < r.apps.length; i++) n += r.apps[i].seconds
      return Math.max(1, r ? Math.max(n, r.durationSeconds || 0) : 1)
    }
    property real drawn: 0
    visible: t !== null
    onTChanged: if (t) { drawn = 0; draw.restart() }
    NumberAnimation { id: draw; target: recapFace; property: "drawn"; from: 0; to: 1; duration: 1400; easing.type: Easing.OutCubic }

    Rectangle {
      anchors.fill: parent
      radius: width / 2
      color: Qt.alpha(recapFace.tint, 0.12)
    }

    // One arc per app, end to end from noon, revealed as `drawn` grows.
    Repeater {
      model: recapFace.r && recapFace.r.apps ? recapFace.r.apps : []
      delegate: Shape {
        required property var modelData
        required property int index
        readonly property real before: {
          var n = 0
          for (var i = 0; i < index; i++) n += recapFace.r.apps[i].seconds
          return 360 * n / recapFace.total
        }
        readonly property real sweep: 360 * modelData.seconds / recapFace.total
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
          strokeColor: recapFace.putOff ? Qt.alpha(Color.foreground, 0.35) : recapFace.palette[index % recapFace.palette.length]
          strokeWidth: 5 * view.k
          fillColor: "transparent"
          capStyle: ShapePath.FlatCap
          PathAngleArc {
            centerX: view.w / 2; centerY: view.w / 2
            radiusX: view.w / 2 - 3 * view.k; radiusY: radiusX
            startAngle: -90 + before
            sweepAngle: Math.max(0, Math.min(sweep - 1.5, 360 * recapFace.drawn - before))
          }
        }
      }
    }

    Column {
      anchors.centerIn: parent
      width: view.w * 0.62
      spacing: 1 * view.k
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: recapFace.r ? p.formatShort(recapFace.r.durationSeconds || 0) : ""
        color: recapFace.putOff ? Qt.alpha(Color.foreground, 0.6) : Color.foreground
        font.family: Style.fontFamily
        font.pixelSize: Math.round(view.w * 0.13)
        font.bold: true
      }
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        text: recapFace.putOff ? "put off" : (recapFace.r ? (recapFace.r.task || "Session") : "")
        color: recapFace.tint
        font.family: Style.fontFamily
        font.pixelSize: Math.round(view.w * 0.065)
      }
    }
  }

  // ---- a league round or a season over: chevrons for the league (green
  // up, red down, grey crossing when staying), the season's medal (one or
  // two bars, dull when not won). Clicked, it is marked as seen.
  Item {
    id: endFace
    anchors.fill: parent
    readonly property var a: view.current && view.current.type === "announcement" ? view.current.data : null
    readonly property bool league: !!a && a.kind === "league"
    readonly property color tint: !a ? view.gold
      : league ? (a.outcome === "up" ? view.green : a.outcome === "down" ? view.red : Qt.alpha(Color.foreground, 0.6))
      : (a.bars > 0 ? view.gold : Qt.alpha(Color.foreground, 0.6))
    visible: a !== null

    Rectangle {
      anchors.fill: parent
      radius: width / 2
      color: Qt.alpha(endFace.league && endFace.a ? endFace.a.after.color : endFace.tint, 0.12)
      border.width: 3 * view.k
      border.color: Qt.alpha(endFace.tint, 0.7)
    }

    Column {
      anchors.centerIn: parent
      spacing: 4 * view.k

      // League: promoted, relegated…
      Chevrons {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: endFace.league && endFace.a.outcome !== "stay"
        up: !!endFace.a && endFace.a.outcome === "up"
        color: endFace.tint
        glyphSize: view.w * 0.2
      }
      // … or staying: grey chevrons crossing, one stream from each side.
      Item {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: endFace.league && endFace.a.outcome === "stay"
        width: view.w * 0.5
        height: view.w * 0.2
        Chevrons {
          anchors.centerIn: parent
          rotation: 90
          up: true
          color: Qt.alpha(Color.foreground, 0.55)
          glyphSize: view.w * 0.13
        }
        Chevrons {
          anchors.centerIn: parent
          rotation: -90
          up: true
          color: Qt.alpha(Color.foreground, 0.55)
          glyphSize: view.w * 0.13
        }
      }
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: endFace.league
        text: !endFace.a ? "" : endFace.a.after.name
        color: endFace.league && endFace.a ? endFace.a.after.color : endFace.tint
        font.family: Style.fontFamily
        font.pixelSize: Math.round(view.w * 0.09)
        font.bold: true
      }
    }

    // Season: its medal in the middle, the grade large under it.
    SeasonMedal {
      id: seasonMedal
      anchors.centerIn: parent
      visible: !!endFace.a && !endFace.league
      bars: endFace.a && endFace.a.bars > 0 ? endFace.a.bars : 1
      won: !!endFace.a && endFace.a.bars > 0
      colors: endFace.a ? endFace.a.colors : null
      size: view.w / 40
    }
    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.top: seasonMedal.bottom
      anchors.topMargin: view.w * 0.02
      visible: seasonMedal.visible
      text: endFace.a ? (endFace.a.grade || "") : ""
      color: endFace.tint
      font.family: Style.fontFamily
      font.pixelSize: Math.round(view.w * 0.2)
      font.bold: true
    }

    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: view.acknowledge()
    }
  }

  // ---- a question: the disc splits in two, No on the left, OK on the
  // right ("Still there?" only has OK)
  Item {
    id: questionFace
    anchors.fill: parent
    readonly property var q: view.current && view.current.type === "question" ? view.current : null
    readonly property color tint: q ? view.questionColor(q.question) : view.gold
    readonly property bool single: !!q && q.question === "presence"
    visible: q !== null

    Rectangle {
      anchors.fill: parent
      radius: width / 2
      color: Qt.alpha(questionFace.tint, 0.12)
      border.width: 3 * view.k
      border.color: Qt.alpha(questionFace.tint, 0.75)
    }

    // The two halves, lit under the pointer.
    Rectangle {
      visible: !questionFace.single
      x: 0; width: view.w / 2; height: view.w
      color: noArea.containsMouse ? Qt.alpha(view.red, 0.22) : "transparent"
    }
    Rectangle {
      x: questionFace.single ? 0 : view.w / 2
      width: questionFace.single ? view.w : view.w / 2; height: view.w
      color: okArea.containsMouse ? Qt.alpha(view.green, 0.22) : "transparent"
    }
    Rectangle {
      visible: !questionFace.single
      x: view.w / 2 - 0.5; y: view.w * 0.54; width: 1; height: view.w * 0.2
      color: Qt.alpha(Color.foreground, 0.25)
    }

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      y: view.w * 0.2
      // "Still there?": the sign blinks gently, asking for a click.
      property real blink: 1
      opacity: questionFace.single ? blink : 1
      SequentialAnimation on blink {
        running: questionFace.single && questionFace.visible
        loops: Animation.Infinite
        NumberAnimation { from: 1; to: 0.25; duration: 650; easing.type: Easing.InOutSine }
        NumberAnimation { from: 0.25; to: 1; duration: 650; easing.type: Easing.InOutSine }
      }
      text: questionFace.q ? view.questionGlyph(questionFace.q.question) : ""
      color: questionFace.tint
      font.family: Style.fontFamily
      font.pixelSize: view.w * 0.2
    }

    Text {
      visible: !questionFace.single
      x: view.w / 2 - view.w * 0.06 - width; y: view.w * 0.6
      text: "No " + view.glyph(0xF0156)
      color: noArea.containsMouse ? view.red : Qt.alpha(Color.foreground, 0.75)
      font.family: Style.fontFamily
      font.pixelSize: Math.round(view.w * 0.075)
      font.bold: true
    }
    Text {
      x: questionFace.single ? (view.w - width) / 2 : view.w / 2 + view.w * 0.06; y: view.w * 0.6
      text: view.glyph(0xF012C) + (questionFace.single ? " Yes" : " Ok")
      color: okArea.containsMouse ? view.green : Qt.alpha(Color.foreground, 0.75)
      font.family: Style.fontFamily
      font.pixelSize: Math.round(view.w * 0.075)
      font.bold: true
    }

    MouseArea {
      id: noArea
      visible: !questionFace.single
      x: 0; width: view.w / 2; height: view.w
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: view.answer(false)
    }
    MouseArea {
      id: okArea
      x: questionFace.single ? 0 : view.w / 2
      width: questionFace.single ? view.w : view.w / 2; height: view.w
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: view.answer(true)
    }
  }

  // The announcement's text, running round the edge.
  RingText {
    id: ringText
    anchors.fill: parent
    pixelSize: Math.round(13 * view.k)
    inset: 12 * view.k
    visible: view.current !== null
    color: !view.current ? Color.foreground
      : view.current.type === "question" ? view.questionColor(view.current.question)
      : view.current.type === "announcement" ? endFace.tint
      : view.current.recap ? recapFace.tint
      : toastFace.ink
  }
}
