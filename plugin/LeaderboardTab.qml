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
    : board === "sessions" || board === "tokenSessions" ? "This session" : board === "tokens" ? "Today" : "Active quest"

  function value(e) {
    if (e.unit === "tokens") {
      var t = e.value
      return (t >= 1e9 ? (t / 1e9).toFixed(2) + "B" : t >= 1e6 ? (t / 1e6).toFixed(1) + "M" : Math.round(t / 1e3) + "k") + " tokens"
    }
    if (e.unit !== "s") return e.value + " XP"
    var m = Math.floor(e.value / 60), h = Math.floor(m / 60)
    return h > 0 ? h + "h" + String(m % 60).padStart(2, "0") : m + " min"
  }

  // Quests can be taken off the board (an open one is deleted); the XP stays.
  function removeQuest(e) {
    p.act("leaderboard:removeQuest", [e.id], "Remove", tab.refresh)
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

  // Agent tokens: the days and the focus sessions that burned the most.
  ButtonGroup {
    anchors.horizontalCenter: parent.horizontalCenter
    options: [
      { value: "tokens", label: "Token days" },
      { value: "tokenSessions", label: "Token sessions" }
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

        HoverHandler { id: rowHover; enabled: !entry.gap }

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
          anchors.right: removeGlyph.left
          anchors.rightMargin: Style.space(6)
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: entry.gap ? "" : (entry.modelData.current ? tab.currentName + "  ·  " : "") + entry.modelData.label
          color: entry.gap ? w.fg : entry.modelData.current ? w.accent : w.fg
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        // On a quest, a cross to take it off the board.
        Text {
          id: removeGlyph
          readonly property bool usable: !entry.gap && tab.board === "quests" && !!entry.modelData.id
          anchors.right: amount.left
          anchors.rightMargin: usable ? Style.space(8) : 0
          anchors.verticalCenter: parent.verticalCenter
          width: usable ? implicitWidth : 0
          textFormat: Text.PlainText
          text: String.fromCodePoint(0xF0156)
          opacity: usable && (rowHover.hovered || removeArea.containsMouse) ? 1 : 0
          color: removeArea.containsMouse ? w.red : Util.alpha(w.fg, 0.55)
          font.family: w.fontFamily
          font.pixelSize: Style.font.body

          MouseArea {
            id: removeArea
            anchors.fill: parent
            anchors.margins: -Style.space(4)
            enabled: removeGlyph.usable
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: tab.removeQuest(entry.modelData)
          }
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
