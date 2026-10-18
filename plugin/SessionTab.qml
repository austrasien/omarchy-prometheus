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
  // Nothing typed: the 6 most recent names. Typing: names starting with it,
  // then containing it, most used first; the best prefix match is shown
  // greyed after the cursor and Tab takes it. Up / Down pick from the list,
  // Enter starts the picked name, else what is typed, else the last name.
  property int selIndex: -1
  readonly property var suggestions: w.suggestNames(taskField.text, 6)
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
    return w.lastTask
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
        placeholderText: w.lastTask ? w.lastTask : "What are you working on?"
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

        Rectangle {
          id: sugg
          required property var modelData
          required property int index
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
            text: "×" + (sugg.modelData.count || 1)
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
}
