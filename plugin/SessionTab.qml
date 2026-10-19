import QtQuick
import qs.Commons
import qs.Ui

// Session tab: start with a task name (or a recent one), or drive the
// running session; today's total and the week underneath.
Column {
  id: tab

  property var w: null   // the bar widget: colors, fonts, glyphs, recent tasks
  property var p: null   // the Prometheus client

  readonly property bool editing: taskField.activeFocus

  // Every session name from the daemon's history (sessions:names): the 3
  // last used, the 4 with the most focus time, and all of them for typing.
  property var history: null
  function loadHistory() {
    p.call("sessions:names", [], function(ok, d) { if (ok && d && d.success) tab.history = d })
  }
  onVisibleChanged: if (visible && !p.session) loadHistory()
  Component.onCompleted: if (visible) loadHistory()
  Connections {
    target: tab.p
    function onSessionChanged() { if (!tab.p.session) tab.loadHistory() }
  }
  readonly property string lastName: {
    var all = history ? history.all : []
    var best = null
    for (var i = 0; i < all.length; i++) if (!best || all[i].last > best.last) best = all[i]
    return best ? best.name : w.lastTask
  }

  // Typing: names starting with the text, then containing it, most worked on
  // first; from the history plus the names remembered by the bar.
  function matchNames(query, limit) {
    var q = query.trim().toLowerCase()
    var pool = {}, list = []
    var all = history ? history.all : []
    for (var i = 0; i < all.length; i++) { pool[all[i].name] = true; list.push(all[i]) }
    var kept = w.sessionNames
    for (var j = 0; j < kept.length; j++) if (!pool[kept[j].name]) list.push({ name: kept[j].name, count: kept[j].count, last: kept[j].last, seconds: 0 })
    var starts = [], contains = []
    for (var k = 0; k < list.length; k++) {
      var n = list[k].name.toLowerCase()
      if (n === q) continue
      if (n.indexOf(q) === 0) starts.push(list[k])
      else if (n.indexOf(q) > 0) contains.push(list[k])
    }
    function order(a, b) { return (b.seconds || 0) - (a.seconds || 0) || (b.count || 0) - (a.count || 0) || b.last - a.last }
    return starts.sort(order).concat(contains.sort(order)).slice(0, limit)
  }
  spacing: Style.space(12)

  function focusEntry() {
    if (!p.session) {
      taskField.text = ""
      tab.selIndex = -1
      taskField.forceActiveFocus()
      return true
    }
    return false
  }

  // ---- no session: task entry, with past session names
  //
  // Nothing typed: the 3 most recent names, then the 4 most used. Typing: names starting with it,
  // then containing it, most used first; the best prefix match is shown
  // greyed after the cursor and Tab takes it. Up / Down pick from the list,
  // Enter starts the picked name, else what is typed, else the last name.
  property int selIndex: -1
  readonly property var suggestions: {
    if (taskField.text.trim().length > 0) return history ? matchNames(taskField.text, 7) : w.suggestNames(taskField.text, 7)
    if (!history) return w.suggestNames("", 7)
    function tag(list, group) { return list.map(function(e) { return { name: e.name, seconds: e.seconds, count: e.count, last: e.last, group: group } }) }
    return tag(history.recent, "recent").concat(tag(history.mostWorked, "most"))
  }
  onSuggestionsChanged: if (selIndex >= suggestions.length) selIndex = suggestions.length - 1

  readonly property string completion: {
    var t = taskField.text
    if (t.length === 0 || suggestions.length === 0) return ""
    var n = suggestions[0].name
    return n.toLowerCase().indexOf(t.toLowerCase()) === 0 ? n.slice(t.length) : ""
  }

  function chosenName() {
    if (selIndex >= 0 && selIndex < suggestions.length) return suggestions[selIndex].name
    var t = taskField.text.trim()
    if (t.length > 0) return t
    return tab.lastName
  }

  function startChosen() {
    p.start(chosenName())
    selIndex = -1
  }

  Column {
    width: parent.width
    spacing: Style.space(8)
    visible: !p.session

    Row {
      width: parent.width
      spacing: Style.space(6)

      TextField {
        id: taskField
        width: parent.width - startButton.width - parent.spacing
        placeholderText: tab.lastName ? tab.lastName : "What are you working on?"
        foreground: w.fg
        accent: w.accent
        font.family: w.fontFamily
        onAccepted: tab.startChosen()
        onTextChanged: tab.selIndex = -1
        Keys.onDownPressed: if (tab.suggestions.length > 0) tab.selIndex = Math.min(tab.suggestions.length - 1, tab.selIndex + 1)
        Keys.onUpPressed: tab.selIndex = Math.max(-1, tab.selIndex - 1)
        Keys.onTabPressed: function(event) {
          if (tab.completion.length > 0) {
            taskField.text = taskField.text + tab.completion
            taskField.cursorPosition = taskField.text.length
          }
          event.accepted = true
        }
        Keys.onEscapePressed: {
          if (tab.selIndex >= 0) tab.selIndex = -1
          else w.close()
        }

        // Inline completion, drawn right after the typed text.
        Text {
          visible: taskField.activeFocus && tab.completion.length > 0 && taskField.cursorPosition === taskField.text.length
          x: taskField.leftPadding + taskField.contentWidth
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: tab.completion
          color: Util.alpha(w.fg, 0.35)
          font: taskField.font
        }
      }

      Button {
        id: startButton
        anchors.verticalCenter: taskField.verticalCenter
        iconText: w.playGlyph
        text: "Start"
        foreground: w.fg
        accent: w.accent
        bordered: true
        onClicked: tab.startChosen()
      }
    }

    Column {
      width: parent.width
      spacing: Style.space(2)
      visible: tab.suggestions.length > 0

      Repeater {
        model: tab.suggestions

        Column {
          id: suggRow
          required property var modelData
          required property int index
          width: parent.width
          // A heading above the first name of each group.
          readonly property bool heading: !!modelData.group
            && (index === 0 || tab.suggestions[index - 1].group !== modelData.group)

          Text {
            visible: suggRow.heading
            topPadding: suggRow.index > 0 ? Style.space(6) : 0
            bottomPadding: Style.space(2)
            leftPadding: Style.space(6)
            textFormat: Text.PlainText
            text: suggRow.modelData.group === "most" ? "MOST WORKED ON" : "RECENT"
            color: Util.alpha(w.fg, 0.45)
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption - 1
            font.bold: true
            font.letterSpacing: 0.5
          }

        Rectangle {
          id: sugg
          readonly property var modelData: suggRow.modelData
          readonly property int index: suggRow.index
          readonly property bool selected: index === tab.selIndex
          width: parent.width
          height: suggName.implicitHeight + Style.space(8)
          radius: Style.space(4)
          color: selected ? Util.alpha(w.accent, 0.18) : (suggArea.containsMouse ? Util.alpha(w.fg, 0.06) : "transparent")

          Text {
            id: suggIcon
            anchors.left: parent.left
            anchors.leftMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: w.historyGlyph
            color: Util.alpha(w.fg, 0.4)
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            id: suggName
            anchors.left: suggIcon.right
            anchors.leftMargin: Style.space(8)
            anchors.right: suggCount.left
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: sugg.modelData.name
            color: sugg.selected ? w.accent : Util.alpha(w.fg, 0.85)
            font.family: w.fontFamily
            font.pixelSize: Style.font.body
            elide: Text.ElideRight
          }

          Text {
            id: suggCount
            anchors.right: parent.right
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            // Focus time when known, else the number of sessions.
            text: sugg.modelData.seconds >= 60 ? tab.p.formatShort(sugg.modelData.seconds)
              : sugg.modelData.seconds > 0 ? "<1m" : "×" + (sugg.modelData.count || 1)
            color: Util.alpha(w.fg, 0.4)
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption
          }

          MouseArea {
            id: suggArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              tab.selIndex = sugg.index
              tab.startChosen()
            }
          }
        }
        }
      }
    }

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: "↑↓ pick · Tab complete · Enter start · Esc close"
      color: Util.alpha(w.fg, 0.45)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  // ---- running session
  Column {
    width: parent.width
    spacing: Style.space(8)
    visible: p.session !== null

    Text {
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      textFormat: Text.PlainText
      text: p.session ? (p.session.task || "Untitled session") : ""
      color: Util.alpha(w.fg, 0.75)
      font.family: w.fontFamily
      font.pixelSize: Style.font.body
      elide: Text.ElideRight
    }

    // The timer, with the session's XP in its laurels beside it.
    Row {
      anchors.horizontalCenter: parent.horizontalCenter
      spacing: Style.space(14)

      Text {
        id: bigTimer
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: p.formatDuration(p.elapsed)
        color: p.paused ? Util.alpha(w.fg, 0.5) : (p.running ? w.accent : w.fg)
        font.family: w.fontFamily
        font.pixelSize: Math.round(Style.font.displayLarge * 1.7)
        font.bold: true
      }

      Laurel {
        anchors.verticalCenter: parent.verticalCenter
        size: Math.round(bigTimer.implicitHeight * 0.95)
        text: String(p.sessionXp)
        color: w.gold
        fontFamily: w.fontFamily
        opacity: p.paused ? 0.5 : 1
      }
    }

    Text {
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      textFormat: Text.PlainText
      text: p.paused
        ? (p.autoPauseLabel ? "Auto-paused (" + p.autoPauseLabel + ") · resumes when you're back" : "Paused · next XP in " + p.formatDuration(p.nextXpIn) + " of focus")
        : "Next XP in " + p.formatDuration(p.nextXpIn)
      color: Util.alpha(w.gold, p.paused ? 0.5 : 0.85)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }

    // When "Break?" is due (the setting, 5 minutes paused reset it).
    Text {
      readonly property var at: p.breakNextAt
      width: parent.width
      visible: !!at && !!p.session && !p.paused
      horizontalAlignment: Text.AlignHCenter
      textFormat: Text.PlainText
      text: {
        if (!at) return ""
        var left = Math.round((at - Date.now() + 0 * p.elapsed) / 60000)   // p.elapsed ticks it every second
        return left > 0 ? "Next break in " + (left >= 60 ? Math.floor(left / 60) + " h " + String(left % 60).padStart(2, "0") : left + " min")
                        : "Break due"
      }
      color: Util.alpha("#2ac3de", 0.85)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }

    // Agents at work during the session (every machine).
    Text {
      readonly property real burnt: p.session ? p.session.agentTokens || 0 : 0
      width: parent.width
      visible: burnt > 0
      horizontalAlignment: Text.AlignHCenter
      textFormat: Text.PlainText
      text: "Agents: " + (burnt >= 1e9 ? (burnt / 1e9).toFixed(1) + "B" : burnt >= 1e6 ? (burnt / 1e6).toFixed(1) + "M"
        : Math.round(burnt / 1e3) + "k") + " tokens this session"
      color: Util.alpha("#ff9e64", 0.85)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }

    // ---- extension challenge: offered, then running
    Rectangle {
      width: parent.width
      visible: p.challengeOffered || p.challengeActive
      height: challengeCol.implicitHeight + Style.space(16)
      radius: Style.space(6)
      color: Util.alpha(w.gold, 0.1)
      border.width: 1
      border.color: Util.alpha(w.gold, 0.45)

      Column {
        id: challengeCol
        anchors.centerIn: parent
        width: parent.width - Style.space(16)
        spacing: Style.space(8)

        Text {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.WordWrap
          textFormat: Text.PlainText
          text: !p.challenge ? ""
            : p.challengeOffered
              ? "Challenge " + (p.challenge.index || 1) + "/" + (p.challenge.max || 3) + ": hold " + p.challenge.minutes + " more min without ending the session, for +" + p.challenge.xp + " XP."
              : "Challenge running: " + Math.ceil((p.challenge.remainingSeconds || 0) / 60) + " more min before you can end. +" + p.challenge.xp + " XP on the line."
          color: w.fg
          font.family: w.fontFamily
          font.pixelSize: Style.font.body
        }

        // Progress of the running challenge.
        Rectangle {
          visible: p.challengeActive
          width: parent.width
          height: Style.space(5)
          radius: height / 2
          color: Util.alpha(w.fg, 0.12)

          Rectangle {
            height: parent.height
            radius: parent.radius
            color: w.gold
            width: p.challengeActive
              ? parent.width * Math.max(0, Math.min(1, 1 - (p.challenge.remainingSeconds || 0) / (p.challenge.minutes * 60)))
              : 0
          }
        }

        Row {
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(6)

          Button {
            visible: p.challengeOffered
            text: "Take the challenge"
            foreground: w.gold
            accent: w.gold
            bordered: true
            onClicked: p.acceptChallenge()
          }

          Button {
            visible: p.challengeOffered
            text: "No thanks"
            foreground: w.fg
            accent: w.accent
            bordered: true
            onClicked: p.declineChallenge()
          }

          Button {
            visible: p.challengeActive
            text: "Abandon challenge (-3 XP)"
            tooltipText: "Costs 3 XP; the session can then be ended"
            foreground: Util.alpha(w.fg, 0.7)
            accent: w.accent
            bordered: true
            onClicked: p.abandonChallenge()
          }
        }
      }
    }

    Row {
      anchors.horizontalCenter: parent.horizontalCenter
      spacing: Style.space(6)

      Button {
        iconText: p.paused ? w.playGlyph : w.pauseGlyph
        text: p.paused ? "Resume" : "Pause"
        foreground: w.fg
        accent: w.accent
        bordered: true
        selected: p.running
        onClicked: p.toggle()
      }

      // While a challenge runs, End and Procrastinate are hidden: abandon the
      // challenge first.
      Button {
        visible: !p.challengeActive
        iconText: w.stopGlyph
        text: "End"
        tooltipText: "Saves the session and shows the recap"
        foreground: w.green
        accent: w.green
        bordered: true
        onClicked: {
          p.stop()
          w.close()
        }
      }

      Button {
        visible: p.paused && !!(p.session && p.session.task) && !p.challengeActive
        iconText: w.laterGlyph
        text: "Procrastinate"
        tooltipText: "Saves the time spent and puts the task back on the to-do list, not done"
        foreground: w.red
        accent: w.red
        bordered: true
        onClicked: {
          p.procrastinate(function(recap) { if (recap.task) p.call("tasks:add", [recap.task, "procrastinated"]) })
          w.close()
        }
      }
    }
  }

  PanelSeparator { width: parent.width; foreground: w.fg }

  Item {
    width: parent.width
    height: Math.max(coffeeButton.implicitHeight, coffeeText.implicitHeight)

    PanelSectionHeader {
      id: hoursHeader
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      text: "HOUR BY HOUR"
      foreground: w.fg
      fontFamily: w.fontFamily
    }

    Row {
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(6)

      Button {
        visible: !!p.coffee && p.coffee.canUndo
        anchors.verticalCenter: parent.verticalCenter
        text: "Undo"
        foreground: w.fg
        accent: w.accent
        fontSize: Style.font.caption
        tooltipText: "Take back the last coffee (3 minutes at most)"
        onClicked: tab.uncoffee()
      }
      Button {
        id: coffeeButton
        anchors.verticalCenter: parent.verticalCenter
        iconText: String.fromCodePoint(0xF0176)
        text: "Coffee"
        foreground: "#c08552"
        accent: "#c08552"
        bordered: true
        tooltipText: "Log a coffee (one standard cup, 95 mg)"
        onClicked: tab.coffee()
      }
    }
  }

  Text {
    id: coffeeText
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    readonly property var c: p.coffee
    text: {
      if (!c) return ""
      var parts = [c.cupsToday + (c.cupsToday === 1 ? " cup" : " cups") + " today",
                   c.inBody + " mg in the body (" + c.mgPerL + " mg/L)"]
      var ideal = c.ideal
      if (ideal && ideal.at) {
        var soon = ideal.at - Date.now() <= 60000
        parts.push(soon ? "a coffee now is a good idea" : "best time for a coffee: " + Qt.formatTime(new Date(ideal.at), "HH:mm"))
      } else if (ideal) {
        parts.push(ideal.reason.charAt(0).toLowerCase() + ideal.reason.slice(1))
      }
      return parts.join("  ·  ")
    }
    color: Util.alpha("#c08552", 0.95)
    font.family: w.fontFamily
    font.pixelSize: Style.font.caption
  }

  DayHours {
    width: parent.width
    w: tab.w
    info: tab.dayHours
    breakAt: p.breakNextAt
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    readonly property var a: p.agentsToday
    text: {
      var d = tab.dayHours
      if (!d) return ""
      var focus = 0, tasks = 0
      for (var i = 0; i < d.hours.length; i++) { focus += d.hours[i].focus; tasks += d.hours[i].tasks }
      var parts = ["in session " + Math.floor(focus / 60) + " h " + String(focus % 60).padStart(2, "0"),
                   d.sessions.length + (d.sessions.length === 1 ? " session" : " sessions"),
                   tasks + (tasks === 1 ? " task" : " tasks")]
      if (d.quests.length) parts.push(d.quests.length + (d.quests.length === 1 ? " quest" : " quests"))
      if (a && a.tokens) parts.push((a.tokens >= 1e9 ? (a.tokens / 1e9).toFixed(1) + "B" : Math.round(a.tokens / 1e6) + "M") + " tokens")
      return parts.join("  ·  ")
    }
    color: Util.alpha(w.fg, 0.55)
    font.family: w.fontFamily
    font.pixelSize: Style.font.caption
  }

  PanelSeparator { width: parent.width; foreground: w.fg }

  // ---- today + week
  Item {
    width: parent.width
    height: todayHeader.implicitHeight

    PanelSectionHeader {
      id: todayHeader
      anchors.left: parent.left
      text: "TODAY"
      foreground: w.fg
      fontFamily: w.fontFamily
    }

    Text {
      anchors.right: parent.right
      anchors.verticalCenter: todayHeader.verticalCenter
      textFormat: Text.PlainText
      text: p.formatShort(p.todaySeconds) + " · " + (p.today ? p.today.sessions || 0 : 0)
        + ((p.today && p.today.sessions === 1) ? " session" : " sessions")
      color: w.fg
      font.family: w.fontFamily
      font.pixelSize: Style.font.body
      font.bold: true
    }
  }

  Row {
    id: week
    width: parent.width
    height: Style.space(64)
    spacing: Style.space(6)
    visible: p.history.length > 0

    // History only counts closed sessions; today's bar also carries the
    // one running now, like the total above.
    readonly property int liveMinutes: Math.floor(p.elapsed / 60)

    function minutesAt(i) {
      var day = p.history[i]
      var m = day ? day.minutes || 0 : 0
      return i === p.history.length - 1 ? m + liveMinutes : m
    }

    readonly property int maxMinutes: {
      var m = 1
      for (var i = 0; i < p.history.length; i++) m = Math.max(m, week.minutesAt(i))
      return m
    }
    readonly property real barWidth: (width - spacing * Math.max(0, p.history.length - 1)) / Math.max(1, p.history.length)
    readonly property real maxTokens: {
      var m = 1
      for (var i = 0; i < p.history.length; i++) m = Math.max(m, p.history[i].tokens || 0)
      return m
    }

    Repeater {
      model: p.history

      Column {
        id: dayColumn
        required property var modelData
        required property int index
        readonly property bool isToday: index === p.history.length - 1
        readonly property int minutes: isToday ? (modelData.minutes || 0) + week.liveMinutes : (modelData.minutes || 0)
        width: week.barWidth
        height: week.height
        spacing: Style.space(4)

        Item {
          width: parent.width
          height: parent.height - dayLabel.implicitHeight - parent.spacing

          Rectangle {
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(parent.width, Style.space(22))
            height: Math.max(Style.space(2), parent.height * dayColumn.minutes / week.maxMinutes)
            radius: Style.space(3)
            color: dayColumn.isToday ? w.accent : Util.alpha(w.fg, dayColumn.minutes > 0 ? 0.45 : 0.12)
          }

          // Agent tokens: a thin orange bar on the right, on their own scale.
          Rectangle {
            anchors.bottom: parent.bottom
            x: parent.width / 2 + Math.min(parent.width, Style.space(22)) / 2 + Style.space(2)
            width: Style.space(4)
            visible: (dayColumn.modelData.tokens || 0) > 0
            height: Math.max(Style.space(2), parent.height * (dayColumn.modelData.tokens || 0) / week.maxTokens)
            radius: Style.space(2)
            color: Util.alpha("#ff9e64", dayColumn.isToday ? 1 : 0.6)
          }
        }

        Text {
          id: dayLabel
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          textFormat: Text.PlainText
          text: ["S", "M", "T", "W", "T", "F", "S"][new Date(modelData.date + "T12:00:00").getDay()] || ""
          color: dayColumn.isToday ? w.accent : Util.alpha(w.fg, 0.5)
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: dayColumn.isToday
        }
      }
    }
  }

  // ---- the day hour by hour and coffee (shown above Today)
  property var dayHours: null          // coffee:day
  function loadDay() {
    p.call("coffee:day", [], function(ok, d) { if (ok && d && d.success) tab.dayHours = d })
  }
  Timer {
    interval: 60 * 1000
    repeat: true
    running: tab.visible
    triggeredOnStart: true
    onTriggered: tab.loadDay()
  }
  function coffee() { p.act("coffee:add", [], "Coffee", tab.loadDay) }
  function uncoffee() { p.act("coffee:undo", [], "Undo coffee", tab.loadDay) }
}
