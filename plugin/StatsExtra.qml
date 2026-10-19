import QtQuick
import qs.Commons
import qs.Ui

// The extra stats views (stats:extra): where the week's XP comes from, tasks,
// focus quality, a week-by-hour heatmap, challenges, presence checks and the
// context of sessions. `view` picks one.
Column {
  id: root

  property var w: null
  property var info: null          // stats:extra
  property string view: "xp"

  spacing: Style.space(8)

  readonly property var sourceKeys: ["focus", "tasks", "challenges", "quests", "medals", "achievements"]
  readonly property var sourceNames: ({ focus: "Focus", tasks: "Tasks", challenges: "Challenges",
                                        quests: "Quests", medals: "Medals", achievements: "Achievements" })
  function sourceColor(k) {
    return k === "focus" ? w.accent : k === "tasks" ? w.gold : k === "challenges" ? w.green
      : k === "quests" ? w.red : k === "medals" ? w.epicColor : "#7dcfff"
  }
  function letter(iso) { return ["S", "M", "T", "W", "T", "F", "S"][new Date(iso + "T12:00:00").getDay()] }
  function pct(v) { return v === null || v === undefined ? "—" : v + " %" }
  function num(v, unit) { return v === null || v === undefined ? "—" : v + (unit || "") }

  component Header: PanelSectionHeader { foreground: root.w.fg; fontFamily: root.w.fontFamily }
  component Row2: StatRow { w: root.w }
  component Note: Text {
    width: root.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    color: Util.alpha(root.w.fg, 0.45)
    font.family: root.w.fontFamily
    font.pixelSize: Style.font.caption
  }

  // ---- where the week's XP comes from: stacked bars, Sunday to Saturday
  Column {
    width: parent.width
    spacing: Style.space(6)
    visible: root.view === "xp" && !!root.info

    Header { text: "XP THIS WEEK, BY SOURCE" }

    Item {
      id: xpChart
      width: parent.width
      height: Style.space(110)
      readonly property var days: root.info ? root.info.xpSources : []
      readonly property real scaleMax: {
        var m = 1
        for (var i = 0; i < days.length; i++) {
          var t = 0
          for (var k = 0; k < root.sourceKeys.length; k++) t += Math.max(0, days[i][root.sourceKeys[k]])
          m = Math.max(m, t)
        }
        return m
      }

      Row {
        anchors.fill: parent
        spacing: Style.space(6)
        Repeater {
          model: xpChart.days
          Item {
            id: dayCol
            required property var modelData
            width: (xpChart.width - 6 * Style.space(6)) / 7
            height: xpChart.height
            readonly property real total: {
              var t = 0
              for (var k = 0; k < root.sourceKeys.length; k++) t += Math.max(0, modelData[root.sourceKeys[k]])
              return t
            }
            Text {
              anchors.bottom: dayLetter.top
              anchors.bottomMargin: Style.space(2) + stack.height
              anchors.horizontalCenter: parent.horizontalCenter
              visible: dayCol.total > 0
              textFormat: Text.PlainText
              text: Math.round(dayCol.total)
              color: Util.alpha(root.w.fg, 0.6)
              font.family: root.w.fontFamily
              font.pixelSize: Style.font.caption - 1
            }
            Column {
              id: stack
              anchors.bottom: dayLetter.top
              anchors.bottomMargin: Style.space(2)
              width: parent.width
              Repeater {
                model: root.sourceKeys.slice().reverse()
                Rectangle {
                  required property string modelData
                  width: stack.width
                  height: Math.max(0, dayCol.modelData[modelData]) / xpChart.scaleMax * (xpChart.height - Style.space(30))
                  color: root.sourceColor(modelData)
                }
              }
            }
            Text {
              id: dayLetter
              anchors.bottom: parent.bottom
              anchors.horizontalCenter: parent.horizontalCenter
              textFormat: Text.PlainText
              text: root.letter(dayCol.modelData.date)
              color: Util.alpha(root.w.fg, 0.6)
              font.family: root.w.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }
      }
    }

    Flow {
      width: parent.width
      spacing: Style.space(10)
      Repeater {
        model: root.sourceKeys
        Row {
          required property string modelData
          spacing: Style.space(4)
          Rectangle { width: Style.space(8); height: width; radius: 2; color: root.sourceColor(modelData); anchors.verticalCenter: parent.verticalCenter }
          Text {
            textFormat: Text.PlainText
            text: {
              var t = 0, days = root.info ? root.info.xpSources : []
              for (var i = 0; i < days.length; i++) t += days[i][modelData]
              return root.sourceNames[modelData] + " " + t
            }
            color: Util.alpha(root.w.fg, 0.75)
            font.family: root.w.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }

  // ---- tasks
  Column {
    width: parent.width
    spacing: Style.space(6)
    visible: root.view === "tasks" && !!root.info

    Header { text: "TASKS DONE, LAST 14 DAYS" }
    Item {
      id: doneChart
      width: parent.width
      height: Style.space(60)
      readonly property var days: root.info ? root.info.tasks.donePerDay : []
      readonly property real scaleMax: Math.max(1, Math.max.apply(null, days.map(function(d) { return d.done }).concat([0])))
      Row {
        anchors.fill: parent
        spacing: 2
        Repeater {
          model: doneChart.days
          Item {
            required property var modelData
            width: (doneChart.width - 13 * 2) / 14
            height: doneChart.height
            Rectangle {
              anchors.bottom: parent.bottom
              width: parent.width
              height: Math.max(modelData.done > 0 ? 2 : 1, modelData.done / doneChart.scaleMax * (doneChart.height - Style.space(12)))
              radius: 1
              color: modelData.done > 0 ? root.w.gold : Util.alpha(root.w.fg, 0.1)
            }
            Text {
              anchors.horizontalCenter: parent.horizontalCenter
              y: 0
              visible: modelData.done > 0
              textFormat: Text.PlainText
              text: modelData.done
              color: Util.alpha(root.w.fg, 0.55)
              font.family: root.w.fontFamily
              font.pixelSize: Style.font.caption - 2
            }
          }
        }
      }
    }

    Header { text: "TO-DO LIST SIZE, LAST 30 DAYS" }
    Item {
      id: backlogChart
      width: parent.width
      height: Style.space(40)
      readonly property var days: root.info ? root.info.tasks.backlog : []
      readonly property real scaleMax: Math.max(1, Math.max.apply(null, days.map(function(d) { return d.open }).concat([0])))
      Row {
        anchors.fill: parent
        spacing: 1
        Repeater {
          model: backlogChart.days
          Rectangle {
            required property var modelData
            anchors.bottom: parent.bottom
            width: (backlogChart.width - 29) / 30
            height: Math.max(1, modelData.open / backlogChart.scaleMax * backlogChart.height)
            color: Util.alpha(root.w.accent, 0.7)
          }
        }
      }
    }

    Row2 { label: "Open now"; value: root.info ? String(root.info.tasks.open) : "" }
    Row2 { label: "Done, all time"; value: root.info ? String(root.info.tasks.done) : "" }
    Row2 { label: "Age when checked, last 30 days"; value: root.info ? root.num(root.info.tasks.avgAgeDays30, " days") : "" }
    Row2 { label: "Age when checked, all time"; value: root.info ? root.num(root.info.tasks.avgAgeDays, " days") : "" }
    Note { text: "Age when checked: how long a task waited on the list, on average. The procrastination index." }
  }

  // ---- focus quality
  Column {
    width: parent.width
    spacing: Style.space(6)
    visible: root.view === "focus" && !!root.info

    Header { text: "FOCUS QUALITY, LAST 30 DAYS" }
    Row2 { label: "Sessions"; value: root.info ? String(root.info.focus.sessions) : "" }
    Row2 { label: "Mean length"; value: root.info ? root.num(root.info.focus.meanMinutes, " min") : "" }
    Row2 { label: "Median length"; value: root.info ? root.num(root.info.focus.medianMinutes, " min") : "" }
    Row2 { label: "Longest"; value: root.info ? root.num(root.info.focus.longestMinutes, " min") : "" }
    Row2 { label: "App switches per hour"; value: root.info ? root.num(root.info.focus.switchesPerHour) : "" }
    Row2 { label: "Time in the main app"; value: root.info ? root.pct(root.info.focus.topAppShare) : "" }
    Note { text: "Time in the main app: the share of a session spent in its most used app, on average. Higher is more single-minded." }
  }

  // ---- heatmap: weekday by hour
  Column {
    width: parent.width
    spacing: Style.space(4)
    visible: root.view === "heatmap" && !!root.info

    Header { text: "WHEN YOU FOCUS, LAST " + (root.info ? root.info.heatmap.weeks : 8) + " WEEKS" }
    Item {
      id: heat
      width: parent.width
      height: 7 * (cell + 2) + Style.space(14)
      readonly property real cell: Math.floor((width - Style.space(16)) / 24) - 2
      readonly property var grid: root.info ? root.info.heatmap.minutes : []
      readonly property real scaleMax: {
        var m = 1
        for (var d = 0; d < grid.length; d++) for (var h = 0; h < 24; h++) m = Math.max(m, grid[d][h])
        return m
      }
      Column {
        spacing: 2
        Repeater {
          model: heat.grid
          Row {
            required property var modelData
            required property int index
            spacing: 2
            Text {
              width: Style.space(14)
              textFormat: Text.PlainText
              text: ["S", "M", "T", "W", "T", "F", "S"][index]
              color: Util.alpha(root.w.fg, 0.55)
              font.family: root.w.fontFamily
              font.pixelSize: Style.font.caption - 1
            }
            Repeater {
              model: modelData
              Rectangle {
                required property int modelData
                width: heat.cell
                height: heat.cell
                radius: 2
                color: modelData > 0 ? Util.alpha(root.w.accent, 0.15 + 0.85 * modelData / heat.scaleMax) : Util.alpha(root.w.fg, 0.05)
              }
            }
          }
        }
        Row {
          spacing: 0
          Item { width: Style.space(14) + 2; height: 1 }
          Repeater {
            model: 24
            Text {
              required property int index
              width: heat.cell + 2
              textFormat: Text.PlainText
              text: index % 6 === 0 ? String(index) : ""
              color: Util.alpha(root.w.fg, 0.45)
              font.family: root.w.fontFamily
              font.pixelSize: Style.font.caption - 2
            }
          }
        }
      }
    }
    Note { text: "Each cell: the focus minutes of that hour of that weekday, brighter for more." }
  }

  // ---- challenges
  Column {
    width: parent.width
    spacing: Style.space(6)
    visible: root.view === "challenges" && !!root.info

    Header { text: "EXTENSION CHALLENGES" }
    Row2 { label: "Offered"; value: root.info ? String(root.info.challenges.offered) : "" }
    Row2 { label: "Accepted"; value: root.info ? root.info.challenges.accepted + "  (" + root.pct(root.info.challenges.acceptRate) + ")" : "" }
    Row2 { label: "Won"; value: root.info ? root.info.challenges.won + "  (" + root.pct(root.info.challenges.winRate) + " of those settled)" : "" }
    Row2 { label: "Abandoned"; value: root.info ? String(root.info.challenges.abandoned) : "" }
    Row2 { label: "Declined / expired"; value: root.info ? root.info.challenges.declined + " / " + root.info.challenges.expired : "" }
    Row2 { label: "XP won"; value: root.info ? "+" + root.info.challenges.xpWon : ""; strong: true }
    Row2 { label: "XP lost to abandons"; value: root.info ? "-" + root.info.challenges.xpLost : "" }
  }

  // ---- presence checks
  Column {
    width: parent.width
    spacing: Style.space(6)
    visible: root.view === "presence" && !!root.info

    Header { text: "\"STILL THERE?\" AND PAUSES" }
    Row2 { label: "Asked"; value: root.info ? String(root.info.presence.asked) : "" }
    Row2 { label: "Answered"; value: root.info ? root.info.presence.answered + "  (" + root.pct(root.info.presence.answerRate) + ")" : "" }
    Row2 { label: "Mean reaction time"; value: root.info ? root.num(root.info.presence.avgReactionSeconds, " s") : "" }
    Row2 { label: "Answered in under 10 s"; value: root.info ? String(root.info.presence.reflexes) : "" }
    Row2 { label: "Paused for no answer"; value: root.info ? String(root.info.presence.absences) : "" }
    Row2 { label: "Auto-pauses (idle, lock, sleep)"; value: root.info ? String(root.info.presence.autoPauses) : "" }
    Note { text: "Questions and answers are counted from October 19, 2026 on." }
  }

  // ---- context: power and weather
  Column {
    width: parent.width
    spacing: Style.space(6)
    visible: root.view === "context" && !!root.info

    Header { text: "ON BATTERY OR PLUGGED IN" }
    Repeater {
      model: root.info ? root.info.context.power : []
      Row2 {
        required property var modelData
        label: modelData.key === "battery" ? "On battery" : modelData.key === "plugged" ? "Plugged in" : "Not recorded"
        value: modelData.hours + " h  ·  " + modelData.sessions + " sessions"
      }
    }

    Header { text: "BY WEATHER" }
    Repeater {
      model: root.info ? root.info.context.weather : []
      Row2 {
        required property var modelData
        label: modelData.key === "unknown" ? "Not recorded" : modelData.key.charAt(0).toUpperCase() + modelData.key.slice(1)
        value: modelData.hours + " h  ·  " + modelData.sessions + " sessions"
      }
    }
    Note { text: "Weather comes from the weather plugin's last reading when a session ends." }
  }
}
