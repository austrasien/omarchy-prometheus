import QtQuick
import qs.Commons
import qs.Ui

// Leagues tab: ten leagues, Bronze to Diamond, one week at a time against
// your own recent weeks. Shows the ladder, where this week stands (relegation,
// stagnation or promotion zone) and the weeks already settled.
Column {
  id: tab

  property var w: null
  property var p: null
  property var info: null      // leagues:get

  readonly property bool editing: false
  function focusEntry() { return false }
  spacing: Style.space(10)

  function refresh() {
    if (!p || !p.live) return
    p.call("leagues:get", [], function(ok, d) { if (ok && d && d.success) tab.info = d })
  }
  onVisibleChanged: if (visible) refresh()
  Component.onCompleted: if (visible) refresh()
  Connections {
    target: p
    function onProfileChanged() { if (tab.visible) tab.refresh() }
  }

  readonly property var cur: info ? info.current : null
  readonly property var ladder: info ? info.leagues : []
  readonly property color zoneColor: !cur ? w.fg : cur.zone === "promotion" ? w.green
    : cur.zone === "relegation" ? w.red : Util.alpha(w.fg, 0.8)

  function leagueName(i) { return i >= 0 && i < ladder.length ? ladder[i].name : "" }

  function zoneTitle() {
    if (!cur) return ""
    return cur.zone === "promotion" ? "Promotion zone" : cur.zone === "relegation" ? "Relegation zone" : "Stagnation zone"
  }

  function zoneLine() {
    if (!cur) return ""
    var next = leagueName(cur.league + 1), here = cur.name, below = leagueName(cur.league - 1)
    if (cur.zone === "promotion")
      return cur.top ? "Top of the table in Diamond. Nowhere higher to go: hold it." : "Bravo! If the week ended now, you would go up to " + next + "."
    if (cur.zone === "relegation") {
      if (cur.bottom) return cur.toSafety + " XP more to climb out of the bottom 3. Bronze has no floor below, but still."
      return "If the week ended now, you would drop to " + below + ". " + cur.toSafety + " XP more to get out of the bottom 3."
    }
    return "You stay in " + here + ". " + cur.toPromotion + " XP more to reach the top 3."
  }

  function weekLabel(iso) {
    var d = new Date(iso + "T12:00:00")
    return Qt.formatDate(d, "MMM d")
  }

  // ---- the ladder: ten gems, the current one bigger and named
  Item {
    width: parent.width
    height: Style.space(30)

    Row {
      anchors.centerIn: parent
      spacing: Style.space(10)

      Repeater {
        model: tab.ladder

        Item {
          required property var modelData
          required property int index
          readonly property bool here: tab.cur && index === tab.cur.league
          width: Style.space(here ? 18 : 11)
          height: width
          anchors.verticalCenter: parent.verticalCenter

          Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.72
            height: width
            rotation: 45
            radius: 2
            color: modelData.color
            opacity: tab.cur && index <= tab.cur.league ? 1 : 0.28
            border.width: parent.here ? 2 : 0
            border.color: "white"
          }
        }
      }
    }
  }

  Text {
    width: parent.width
    horizontalAlignment: Text.AlignHCenter
    textFormat: Text.PlainText
    text: tab.cur ? tab.cur.name + " League" : "…"
    color: tab.cur ? tab.cur.color : w.fg
    font.family: w.fontFamily
    font.pixelSize: Style.font.body + 4
    font.bold: true
  }

  // ---- this week: you and nine rivals, ranked
  Column {
    width: parent.width
    spacing: Style.space(4)
    visible: !!tab.cur

    Item {
      width: parent.width
      height: Math.max(zoneText.implicitHeight, zoneChevrons.height)

      Chevrons {
        id: zoneChevrons
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        visible: !!tab.cur && tab.cur.zone !== "stagnation"
        width: visible ? implicitWidth : 0
        up: !!tab.cur && tab.cur.zone === "promotion"
        color: tab.zoneColor
        glyphSize: 13
      }

      Text {
        id: zoneText
        anchors.left: zoneChevrons.right
        anchors.leftMargin: zoneChevrons.visible ? Style.space(6) : 0
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: tab.zoneTitle() + (tab.cur && tab.cur.zone === "promotion" ? "!" : "")
        color: tab.zoneColor
        font.family: w.fontFamily
        font.pixelSize: Style.font.body + 1
        font.bold: true
      }

      Text {
        anchors.right: parent.right
        anchors.verticalCenter: zoneText.verticalCenter
        textFormat: Text.PlainText
        text: tab.cur ? tab.cur.daysLeft + (tab.cur.daysLeft === 1 ? " day left" : " days left") : ""
        color: Util.alpha(w.fg, 0.6)
        font.family: w.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Text {
      width: parent.width
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: tab.zoneLine()
      color: Util.alpha(w.fg, 0.85)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }

    Repeater {
      model: tab.cur ? tab.cur.players : []

      Item {
        id: player
        required property var modelData
        required property int index
        readonly property color tint: modelData.zone === "promotion" ? w.green
          : modelData.zone === "relegation" ? w.red : w.fg
        readonly property bool zoneStart: index === 0 || index === 3 || index === 7
        width: tab.width
        height: playerRow.height + (zoneStart ? zoneLabel.implicitHeight + Style.space(4) : 0)

        Text {
          id: zoneLabel
          visible: player.zoneStart
          anchors.top: parent.top
          textFormat: Text.PlainText
          text: player.modelData.zone === "promotion" ? "PROMOTION ZONE  ▲"
            : player.modelData.zone === "relegation" ? "RELEGATION ZONE  ▼" : "STAGNATION"
          color: Util.alpha(player.tint, 0.7)
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption - 1
          font.bold: true
          font.letterSpacing: 1
        }

        Rectangle {
          id: playerRow
          anchors.bottom: parent.bottom
          width: parent.width
          height: Style.space(24)
          radius: Style.space(4)
          color: player.modelData.you ? Util.alpha(player.modelData.zone === "stagnation" ? w.accent : player.tint, 0.22)
            : Util.alpha(player.tint, player.modelData.zone === "stagnation" ? 0.03 : 0.07)
          border.width: player.modelData.you ? 1 : 0
          border.color: player.modelData.zone === "stagnation" ? w.accent : player.tint

          Text {
            id: rankText
            anchors.left: parent.left
            anchors.leftMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(24)
            textFormat: Text.PlainText
            text: player.modelData.rank
            color: Util.alpha(player.tint, 0.8)
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
          }

          Text {
            anchors.left: rankText.right
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: player.modelData.you ? "You" : player.modelData.name
            color: player.modelData.you ? w.fg : Util.alpha(w.fg, 0.7)
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: player.modelData.you
          }

          // Your row: the chevrons stream up or down with your zone.
          Chevrons {
            anchors.right: xpText.left
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            height: parent.height
            visible: player.modelData.you && player.modelData.zone !== "stagnation"
            up: player.modelData.zone === "promotion"
            color: player.tint
            glyphSize: 10
          }

          Text {
            id: xpText
            anchors.right: parent.right
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: player.modelData.xp + " XP"
            color: player.modelData.you ? w.gold : Util.alpha(w.fg, 0.6)
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: player.modelData.you
          }
        }
      }
    }

    Text {
      width: parent.width
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: "Your rivals are drawn each week from your last 4 weeks"
        + (tab.cur && tab.cur.reference !== null ? " (average " + Math.round(tab.cur.reference) + " XP)" : "")
        + ", a little stronger each league up, and earn their XP as the week goes. Top 3 go up, bottom 3 go down, one league at most. An empty week always goes down."
      color: Util.alpha(w.fg, 0.45)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  // ---- settled weeks, latest first
  Column {
    width: parent.width
    spacing: Style.space(3)
    visible: tab.info && tab.info.history.length > 0

    PanelSectionHeader {
      text: "PAST WEEKS"
      foreground: w.fg
      fontFamily: w.fontFamily
    }

    Repeater {
      model: tab.info ? tab.info.history.slice(-8).reverse() : []

      Item {
        required property var modelData
        width: tab.width
        height: weekText.implicitHeight

        Text {
          id: weekText
          anchors.left: parent.left
          textFormat: Text.PlainText
          text: "Week of " + tab.weekLabel(modelData.week) + "  ·  " + modelData.xp + " XP"
          color: Util.alpha(w.fg, 0.75)
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          anchors.right: parent.right
          textFormat: Text.PlainText
          text: modelData.outcome === "up" ? "▲ " + tab.leagueName(modelData.after)
            : modelData.outcome === "down" ? "▼ " + tab.leagueName(modelData.after)
            : "= " + tab.leagueName(modelData.after)
          color: modelData.outcome === "up" ? w.green : modelData.outcome === "down" ? w.red : Util.alpha(w.fg, 0.6)
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: modelData.outcome !== "stay"
        }
      }
    }
  }
}
