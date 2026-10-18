import QtQuick
import qs.Commons
import qs.Ui

// Seasons tab: calendar quarters. Two XP goals; the first wins a season
// medal with one bar, the second a second bar. Medals are kept for good.
// A finished season gets a grade, A to F, and a recap.
Column {
  id: tab

  property var w: null
  property var p: null
  property var info: null      // seasons:get

  readonly property bool editing: false
  function focusEntry() { return false }
  spacing: Style.space(10)

  function refresh() {
    if (!p || !p.live) return
    p.call("seasons:get", [], function(ok, d) { if (ok && d && d.success) tab.info = d })
  }
  onVisibleChanged: if (visible) refresh()
  Component.onCompleted: if (visible) refresh()
  Connections {
    target: p
    function onProfileChanged() { if (tab.visible) tab.refresh() }
  }

  readonly property var all: info ? info.seasons : []
  readonly property var cur: all.length > 0 && all[all.length - 1].running ? all[all.length - 1] : null
  readonly property var past: all.filter(function(s) { return !s.running }).reverse()

  function medalOf(s) {
    var ms = info ? info.medals : []
    for (var i = 0; i < ms.length; i++) if (ms[i].season === s.key) return ms[i]
    return null
  }

  function gradeColor(g) {
    return g === "A" ? w.gold : g === "B" ? w.green : g === "C" ? w.fg : g === "D" ? "#ea9a23" : w.red
  }

  function dateLabel(iso) { return Qt.formatDate(new Date(iso + "T12:00:00"), "MMM d") }

  // ---- the running season
  Column {
    width: parent.width
    spacing: Style.space(5)
    visible: !!tab.cur

    Item {
      width: parent.width
      height: seasonTitle.implicitHeight

      Text {
        id: seasonTitle
        anchors.left: parent.left
        textFormat: Text.PlainText
        text: tab.cur ? "Season " + tab.cur.number + "  ·  " + tab.cur.label : ""
        color: w.fg
        font.family: w.fontFamily
        font.pixelSize: Style.font.body + 2
        font.bold: true
      }

    }

    Text {
      textFormat: Text.PlainText
      text: tab.cur ? "Ends " + tab.dateLabel(tab.cur.end) + "  ·  " + tab.cur.daysLeft + " days left" : ""
      color: Util.alpha(w.fg, 0.55)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }

    // What each goal wins, above its mark: the medal with an edge bar on the
    // left, then on both sides. Grey until won; hovering either wakes both.
    Item {
      readonly property bool hot: goalMedal.hovering || hardMedal.hovering
      width: parent.width
      height: goalMedal.implicitHeight + Style.space(10)

      SeasonMedal {
        id: goalMedal
        x: tab.cur ? Math.max(0, Math.min(parent.width - width, goals.px(tab.cur.goal) - width / 2)) : 0
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Style.space(4)
        bars: 1
        hot: parent.hot
        won: !!tab.cur && tab.cur.bars >= 1
        colors: tab.cur ? tab.cur.colors : null
        size: 1.2
      }

      SeasonMedal {
        id: hardMedal
        x: tab.cur ? Math.max(0, Math.min(parent.width - width, goals.px(tab.cur.hardGoal) - width / 2)) : 0
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Style.space(4)
        bars: 2
        hot: parent.hot
        won: !!tab.cur && tab.cur.bars >= 2
        colors: tab.cur ? tab.cur.colors : null
        size: 1.2
      }
    }

    // XP against the two goals.
    Item {
      id: goals
      width: parent.width
      height: Style.space(10)
      readonly property real scaleMax: !tab.cur ? 1 : Math.max(tab.cur.hardGoal * 1.1, tab.cur.xp * 1.05)
      function px(v) { return width * Math.min(1, v / scaleMax) }

      Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: Util.alpha(w.fg, 0.12)
      }
      Rectangle {
        height: parent.height
        radius: height / 2
        width: tab.cur ? goals.px(tab.cur.xp) : 0
        color: w.gold
        Behavior on width { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
      }
      Repeater {
        model: tab.cur ? [tab.cur.goal, tab.cur.hardGoal] : []
        Rectangle {
          required property int modelData
          x: goals.px(modelData) - 1
          y: -Style.space(2)
          width: 2
          height: goals.height + Style.space(4)
          color: tab.cur && tab.cur.xp >= modelData ? w.gold : Util.alpha(w.fg, 0.6)
        }
      }
    }

    Item {
      width: parent.width
      height: goalLabel.implicitHeight

      Text {
        id: goalLabel
        x: tab.cur ? Math.max(0, goals.px(tab.cur.goal) - implicitWidth / 2) : 0
        textFormat: Text.PlainText
        text: tab.cur ? "Goal " + tab.cur.goal : ""
        color: Util.alpha(w.fg, 0.6)
        font.family: w.fontFamily
        font.pixelSize: Style.font.caption
      }
      Text {
        x: tab.cur ? Math.min(parent.width - implicitWidth, goals.px(tab.cur.hardGoal) - implicitWidth / 2) : 0
        textFormat: Text.PlainText
        text: tab.cur ? "Hard " + tab.cur.hardGoal : ""
        color: Util.alpha(w.fg, 0.6)
        font.family: w.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Text {
      width: parent.width
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: !tab.cur ? ""
        : tab.cur.xp + " XP so far  ·  projected grade " + tab.cur.projected
          + (tab.cur.bars === 2 ? "  ·  both bars won" : tab.cur.bars === 1 ? "  ·  first bar won, " + (tab.cur.hardGoal - tab.cur.xp) + " XP to the second"
             : "  ·  " + (tab.cur.goal - tab.cur.xp) + " XP to the medal")
      color: Util.alpha(w.fg, 0.8)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }

    Text {
      width: parent.width
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: "XP from focus, tasks, challenges and quests. The goals follow your last season: the first is its XP (300 at least), the hard one 25 % more (600 at least). Grades: A hard goal, B goal, C 75 %, D 50 %, F below."
      color: Util.alpha(w.fg, 0.45)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  // ---- finished seasons, latest first
  Column {
    width: parent.width
    spacing: Style.space(8)
    visible: tab.past.length > 0

    PanelSectionHeader {
      text: "PAST SEASONS"
      foreground: w.fg
      fontFamily: w.fontFamily
    }

    Repeater {
      model: tab.past

      Item {
        id: pastRow
        required property var modelData
        readonly property var medal: tab.medalOf(modelData)
        width: tab.width
        height: Math.max(grade.implicitHeight, pastText.implicitHeight)

        Text {
          id: grade
          anchors.left: parent.left
          width: Style.space(26)
          textFormat: Text.PlainText
          text: pastRow.modelData.grade
          color: tab.gradeColor(pastRow.modelData.grade)
          font.family: w.fontFamily
          font.pixelSize: Style.font.body + 10
          font.bold: true
        }

        Column {
          id: pastText
          anchors.left: grade.right
          anchors.right: pastMedal.left
          anchors.rightMargin: Style.space(6)
          spacing: Style.space(1)

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: "Season " + pastRow.modelData.number + "  ·  " + pastRow.modelData.label
            color: w.fg
            font.family: w.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
          }
          Text {
            width: parent.width
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: pastRow.modelData.xp + " / " + pastRow.modelData.goal + " XP (hard " + pastRow.modelData.hardGoal + ")"
            color: Util.alpha(w.fg, 0.7)
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption
          }
          Text {
            width: parent.width
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: pastRow.modelData.hours + " h  ·  " + pastRow.modelData.sessions + " sessions  ·  "
              + pastRow.modelData.tasks + " tasks  ·  " + pastRow.modelData.quests + " quests  ·  best week "
              + pastRow.modelData.bestWeek + " XP"
            color: Util.alpha(w.fg, 0.5)
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Row {
          id: pastMedal
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          spacing: 1
          HoloRibbon {
            visible: !!pastRow.medal
            size: 1.2
            color: pastRow.medal ? pastRow.medal.color : "#555"
            dot: pastRow.medal ? pastRow.medal.dot : "white"
            edge: pastRow.medal ? pastRow.medal.edge : "#999"
            edges: pastRow.medal && pastRow.medal.bars === 2 ? "both" : "left"
          }
        }
      }
    }
  }
}
