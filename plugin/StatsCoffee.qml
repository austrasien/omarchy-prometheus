import QtQuick
import qs.Commons
import qs.Ui

// The Coffee view of Stats (stats:coffee): cups by day and week, and how
// coffee days go next to focus, tasks, agent tokens and XP.
Column {
  id: root

  property var w: null
  property var info: null          // stats:coffee
  property color ink: "#c08552"
  property var tokensText: function(n) { return String(n) }

  spacing: Style.space(8)

  readonly property var names: ({ focus: "Focus (h)", tasks: "Tasks", tokens: "Agent tokens", xp: "XP" })
  function strength(r) {
    if (r === null || r === undefined) return "not enough days yet"
    var a = Math.abs(r)
    var word = a < 0.1 ? "none" : a < 0.3 ? "weak" : a < 0.5 ? "moderate" : "strong"
    return (r >= 0 ? "+" : "") + r.toFixed(2) + "  (" + word + (a >= 0.1 ? (r > 0 ? ", more coffee goes with more" : ", more coffee goes with less") : "") + ")"
  }
  function value(name, v) {
    if (v === null || v === undefined) return "—"
    return name === "tokens" ? root.tokensText(v) : String(v)
  }

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

  Column {
    width: parent.width
    spacing: Style.space(6)
    visible: !!root.info

    Header { text: "COFFEE" }
    Row2 { label: "Today"; value: root.info ? root.info.today + " cups  ·  " + root.info.now.inBody + " mg in the body" : ""; strong: true }
    Row2 { label: "A day, on coffee days"; value: root.info && root.info.average !== null ? root.info.average + " cups" : "—" }
    Row2 { label: "Last 30 days"; value: root.info ? root.info.last30 + " cups" : "" }
    Row2 { label: "All time"; value: root.info ? root.info.total + " cups" : "" }

    Header { text: "LAST 30 DAYS" }
    Item {
      id: chart
      width: parent.width
      height: Style.space(48)
      readonly property var days: root.info ? root.info.days : []
      readonly property real scaleMax: Math.max(4, Math.max.apply(null, days.map(function(d) { return d.cups }).concat([0])))
      Row {
        anchors.fill: parent
        spacing: 1
        Repeater {
          model: chart.days
          Rectangle {
            required property var modelData
            anchors.bottom: parent.bottom
            width: (chart.width - 29) / 30
            height: Math.max(1, modelData.cups / chart.scaleMax * chart.height)
            color: modelData.cups > 0 ? Util.alpha(root.ink, 0.85) : Util.alpha(root.w.fg, 0.08)
          }
        }
      }
    }

    Header { text: "BY WEEK" }
    Repeater {
      model: root.info ? root.info.weeks.slice().reverse() : []
      Row2 {
        required property var modelData
        label: "Week of " + Qt.formatDate(new Date(modelData.from + "T12:00:00"), "MMM d")
        value: modelData.cups + " cups"
      }
    }

    Header { text: "PER CUP" }
    Row2 { label: "Focus per cup"; value: root.info && root.info.focusPerCup !== null ? root.info.focusPerCup + " h" : "—" }
    Row2 { label: "Tasks per cup"; value: root.info && root.info.tasksPerCup !== null ? String(root.info.tasksPerCup) : "—" }
    Row2 { label: "Agent tokens per cup"; value: root.info && root.info.tokensPerCup ? root.tokensText(root.info.tokensPerCup) : "—" }

    Header { text: "COFFEE DAYS VS THE OTHERS" }
    Repeater {
      model: ["focus", "tasks", "tokens", "xp"]
      Row2 {
        required property string modelData
        readonly property var c: root.info ? root.info.compare[modelData] : null
        label: root.names[modelData]
        value: c ? root.value(modelData, c["with"]) + " with  ·  " + root.value(modelData, c.without) + " without" : ""
      }
    }

    Header { text: "CORRELATION, CUPS A DAY" }
    Repeater {
      model: ["focus", "tasks", "tokens", "xp"]
      Row2 {
        required property string modelData
        label: root.names[modelData]
        value: root.info ? root.strength(root.info.correlations[modelData]) : ""
      }
    }

    Note {
      text: "Over the last 90 days with something logged (" + (root.info ? root.info.daysCompared : 0) + " days). A correlation runs from -1 to +1; it says the two go together, not that one causes the other. One cup is a standard 95 mg."
    }
  }
}
