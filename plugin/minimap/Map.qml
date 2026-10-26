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
    onToast: function(kind, title, text, rarity) {
      view.enqueue({ type: "toast", kind: kind, title: title, text: text, rarity: rarity })
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
  // Toasts and questions wait their turn; each asks the minimap to show
  // this map for as long as it lasts. A question still unanswered comes
  // back every two minutes.

  readonly property int toastMs: 5000
  readonly property int questionMs: 10000
  property var queue: []
  property var current: null

  function enqueue(item) {
    if (item.type === "question") {
      if (current && current.type === "question" && current.question === item.question) return
      for (var i = 0; i < queue.length; i++)
        if (queue[i].type === "question" && queue[i].question === item.question) return
    }
    queue = queue.concat([item])
    if (!current) showNext()
  }

  function showNext() {
    ringText.stop()
    if (!queue.length) { current = null; return }
    current = queue[0]
    queue = queue.slice(1)
    ringText.text = itemText(current)
    // As long as its text takes to go round (a question at least 10 s, to
    // leave time to answer).
    var ms = ringText.runMs + 700
    if (current.type === "question") ms = Math.max(questionMs, ms)
    shownFor.interval = ms
    shownFor.restart()
    minimap.notify(view, ms)
    if (onScreen) ringText.start()
  }

  readonly property bool onScreen: minimap.shownMap === "prometheus"
  onOnScreenChanged: if (onScreen && current) ringText.start()

  function itemText(item) {
    if (item.type === "question") return questionText(item.question)
    return item.title + (item.text ? "  ·  " + item.text : "")
  }

  Timer {
    id: shownFor
    onTriggered: {
      if (!view.sticky) { view.showNext(); return }
      // Paused: the notification stays, its text going round again, until
      // the session resumes; others waiting pass first, then it comes back.
      if (view.queue.length) { view.queue = view.queue.concat([view.current]); view.showNext(); return }
      shownFor.restart()
      view.minimap.notify(view, shownFor.interval)
      if (view.onScreen) ringText.start()
    }
  }

  // "Session paused" stays up while the session is paused: a click resumes.
  readonly property bool sticky: !!current && current.type === "toast" && current.kind === "absent"
    && !current.demo && p.paused
  onStickyChanged: if (!sticky && current && current.kind === "absent" && !current.demo && !p.paused) showNext()

  // The questions, most urgent first, as the bar orders them.
  readonly property var pendingQuestions: {
    var out = []
    if (p.presence) out.push("presence")
    if (p.challengeOffered) out.push("challenge")
    if (p.breakNudge) out.push("break")
    if (p.coffeeNudge) out.push("coffee")
    return out
  }
  onPendingQuestionsChanged: {
    for (var i = 0; i < pendingQuestions.length; i++) ask(pendingQuestions[i])
    // Answered elsewhere (or expired): stop showing it.
    if (current && current.type === "question" && !current.demo
        && pendingQuestions.indexOf(current.question) === -1) showNext()
  }
  function ask(q) { enqueue({ type: "question", question: q }) }

  Timer {
    interval: 120000
    repeat: true
    running: view.pendingQuestions.length > 0
    onTriggered: { for (var i = 0; i < view.pendingQuestions.length; i++) view.ask(view.pendingQuestions[i]) }
  }

  function answer(ok) {
    var q = current ? current.question : ""
    var demo = current && current.demo
    if (!demo) {
      if (q === "presence") p.confirmPresence()
      else if (q === "challenge") { if (ok) p.acceptChallenge(); else p.declineChallenge() }
      else if (q === "break") { if (ok) p.takeBreak(); else p.breakLater() }
      else if (q === "coffee") { if (ok) p.coffeeOk(); else p.coffeeNo() }
    }
    shownFor.stop()
    showNext()
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
      enqueue({ type: "question", question: a, demo: true })
    else if (a === "level") announceLevel(Math.max(2, level + 1))
    else if (a === "medal" && p.medals && p.medals.length) {
      var m = p.medals[Math.floor(Math.random() * p.medals.length)]
      p.call("toast:echo", ["medal", m.name, "+20 XP · " + (m.desc || "")])
    } else p.call("toast:preview", [a || "legendary"])
  }

  // ------------------------------------------------------------- faces

  readonly property real w: width

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
        strokeWidth: 5
        fillColor: "transparent"
        PathAngleArc { centerX: view.w / 2; centerY: view.w / 2; radiusX: view.w / 2 - 4; radiusY: radiusX; startAngle: 0; sweepAngle: 360 }
      }
      ShapePath {
        strokeColor: p.challengeActive ? view.red : view.gold
        strokeWidth: 5
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        PathAngleArc {
          centerX: view.w / 2; centerY: view.w / 2
          radiusX: view.w / 2 - 4; radiusY: radiusX
          startAngle: -90
          sweepAngle: 360 * status.ring
        }
      }
    }

    Column {
      anchors.centerIn: parent
      width: view.w * 0.72
      spacing: 2

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

    // Click: pause or resume the running session; with none, the bar's
    // Prometheus menu, to name and start one.
    MouseArea {
      anchors.fill: parent
      enabled: p.live
      cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: {
        if (p.session) p.toggle()
        else Quickshell.execDetached(["omarchy-shell", "shell", "summon", "austraz.prometheus", "{}"])
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
    readonly property var t: view.current && view.current.type === "toast" ? view.current : null
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
      border.width: 2
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
      enabled: view.sticky
      cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: p.resume()
    }

    Column {
      anchors.centerIn: parent
      width: view.w * 0.8
      spacing: 2

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: !toastFace.medal && !toastFace.levelUp
        text: toastFace.t ? view.toastGlyph(toastFace.t.kind) : ""
        color: toastFace.ink
        font.family: Style.fontFamily
        font.pixelSize: view.w * 0.26
      }
      // A medal: its own ribbon, as on the bar's placard.
      Ribbon {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: !!toastFace.medal
        size: view.w / 60
        color: toastFace.medal ? toastFace.medal.color : "#555"
        dot: toastFace.medal ? toastFace.medal.dot : "white"
        dots: toastFace.medal ? (toastFace.medal.dots || 1) : 1
        edges: toastFace.medal ? (toastFace.medal.edges || "none") : "none"
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
      border.width: 3
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
    visible: view.current !== null
    color: !view.current ? Color.foreground
      : view.current.type === "question" ? view.questionColor(view.current.question)
      : toastFace.ink
  }
}
