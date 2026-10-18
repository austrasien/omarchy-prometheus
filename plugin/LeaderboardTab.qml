import QtQuick
import qs.Commons
import qs.Ui

// Leaderboard tab: your own records, ranked. Days and weeks by XP earned,
// sessions by focus time, quests by the XP earned while active. The current
// day, week, session or quest is highlighted, or shown under the top 10.
Column {
  id: tab

  property var w: null
  property var p: null
  property var info: null      // leaderboard:get
  property string board: "days"

  readonly property bool editing: false
  function focusEntry() { return false }
  spacing: Style.space(10)

  function refresh() {
    if (!p || !p.live) return
    p.call("leaderboard:get", [board], function(ok, d) { if (ok && d && d.success) tab.info = d })
  }
  onBoardChanged: refresh()
  onVisibleChanged: if (visible) refresh()
  Component.onCompleted: if (visible) refresh()
  Connections {
    target: p
    function onProfileChanged() { if (tab.visible) tab.refresh() }
  }

  readonly property string currentName: board === "days" ? "Today" : board === "weeks" ? "This week"
    : board === "sessions" ? "This session" : "Active quest"

  function value(e) {
    if (e.unit !== "s") return e.value + " XP"
    var m = Math.floor(e.value / 60), h = Math.floor(m / 60)
    return h > 0 ? h + "h" + String(m % 60).padStart(2, "0") : m + " min"
  }

  function rankColor(r) {
    return r === 1 ? "#ffd700" : r === 2 ? "#c0c0c0" : r === 3 ? "#cd7f32" : Util.alpha(w.fg, 0.5)
  }

  ButtonGroup {
    anchors.horizontalCenter: parent.horizontalCenter
    options: [
      { value: "days", label: "Days" },
      { value: "weeks", label: "Weeks" },
      { value: "sessions", label: "Sessions" },
      { value: "quests", label: "Quests" }
    ]
    value: tab.board
    foreground: w.fg
    accent: w.accent
    fontFamily: w.fontFamily
    fontSize: Style.font.caption
    focusable: false
    onChanged: function(v) { tab.board = v }
  }

  Text {
    visible: !!tab.info && tab.info.entries.length === 0
    textFormat: Text.PlainText
    text: "Nothing ranked yet."
    color: Util.alpha(w.fg, 0.45)
    font.family: w.fontFamily
    font.pixelSize: Style.font.body
  }

  Column {
    width: parent.width
    spacing: Style.space(2)

    Repeater {
      model: tab.info ? tab.info.entries.concat(tab.info.you ? [null, tab.info.you] : []) : []

      Item {
        id: entry
        required property var modelData
        readonly property bool gap: modelData === null
        width: tab.width
        height: gap ? gapText.implicitHeight : label.implicitHeight + Style.space(6)

        Text {
          id: gapText
          visible: entry.gap
          anchors.horizontalCenter: parent.horizontalCenter
          textFormat: Text.PlainText
          text: "…"
          color: Util.alpha(w.fg, 0.4)
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
        }

        Rectangle {
          visible: !entry.gap && entry.modelData.current
          anchors.fill: parent
          radius: Style.space(4)
          color: Util.alpha(w.accent, 0.14)
        }

        Text {
          id: rank
          visible: !entry.gap
          anchors.left: parent.left
          anchors.leftMargin: Style.space(4)
          anchors.verticalCenter: parent.verticalCenter
          width: Style.space(30)
          textFormat: Text.PlainText
          text: entry.gap ? "" : "#" + entry.modelData.rank
          color: entry.gap ? w.fg : tab.rankColor(entry.modelData.rank)
          font.family: w.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
        }

        Text {
          id: label
          visible: !entry.gap
          anchors.left: rank.right
          anchors.right: amount.left
          anchors.rightMargin: Style.space(6)
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: entry.gap ? "" : (entry.modelData.current ? tab.currentName + "  ·  " : "") + entry.modelData.label
          color: entry.gap ? w.fg : entry.modelData.current ? w.accent : w.fg
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        Text {
          id: amount
          visible: !entry.gap
          anchors.right: parent.right
          anchors.rightMargin: Style.space(4)
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: entry.gap ? "" : tab.value(entry.modelData)
          color: w.gold
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }
    }
  }
}
