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
      return cur.promoteAt === null ? "Top of the ladder. Hold Diamond." : "If the week ended now, you would go up to " + next + "."
    if (cur.zone === "relegation") {
      var need = Math.max(1, (cur.relegateBelow || 0) - cur.xp)
      return "If the week ended now, you would drop to " + below + ". " + need + " XP more to stay in " + here + "."
    }
    if (cur.promoteAt === null) return "You stay in Diamond."
    return "You stay in " + here + ". " + (cur.promoteAt - cur.xp) + " XP more to reach the promotion zone."
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

  // ---- this week
  Column {
    width: parent.width
    spacing: Style.space(4)
    visible: !!tab.cur

    Item {
      width: parent.width
      height: zoneText.implicitHeight

      Text {
        id: zoneText
        anchors.left: parent.left
        textFormat: Text.PlainText
        text: tab.zoneTitle()
        color: tab.zoneColor
        font.family: w.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
      }

      Text {
        anchors.right: parent.right
        anchors.verticalCenter: zoneText.verticalCenter
        textFormat: Text.PlainText
        text: tab.cur ? tab.cur.xp + " XP this week  ·  " + tab.cur.daysLeft + (tab.cur.daysLeft === 1 ? " day left" : " days left") : ""
        color: Util.alpha(w.fg, 0.6)
        font.family: w.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    // The three zones on one bar, and the week's XP on it.
    Item {
      id: zones
      width: parent.width
      height: Style.space(12)
      readonly property real scaleMax: !tab.cur ? 1 : Math.max(10, (tab.cur.promoteAt || tab.cur.xp) * 1.3, tab.cur.xp * 1.1)
      function px(v) { return width * Math.min(1, Math.max(0, v) / scaleMax) }
      readonly property real relX: tab.cur && tab.cur.relegateBelow ? px(tab.cur.relegateBelow) : 0
      readonly property real proX: tab.cur && tab.cur.promoteAt !== null ? px(tab.cur.promoteAt) : width

      Rectangle {   // relegation
        x: 0; width: zones.relX; height: parent.height; radius: 3
        color: Util.alpha(w.red, 0.35)
      }
      Rectangle {   // stagnation
        x: zones.relX; width: zones.proX - zones.relX; height: parent.height
        color: Util.alpha(w.fg, 0.12)
      }
      Rectangle {   // promotion
        x: zones.proX; width: zones.width - zones.proX; height: parent.height; radius: 3
        color: Util.alpha(w.green, 0.35)
      }
      Rectangle {   // this week so far
        y: parent.height * 0.3
        height: parent.height * 0.4
        radius: height / 2
        width: tab.cur ? zones.px(tab.cur.xp) : 0
        color: tab.zoneColor
        Behavior on width { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
      }
    }

    Item {
      width: parent.width
      height: lowLabel.implicitHeight

      Text {
        id: lowLabel
        x: Math.max(0, Math.min(zones.relX - implicitWidth / 2, parent.width - implicitWidth))
        visible: !!(tab.cur && tab.cur.relegateBelow)
        textFormat: Text.PlainText
        text: tab.cur && tab.cur.relegateBelow ? tab.cur.relegateBelow + " XP" : ""
        color: Util.alpha(w.red, 0.9)
        font.family: w.fontFamily
        font.pixelSize: Style.font.caption
      }

      Text {
        x: Math.max(0, Math.min(zones.proX - implicitWidth / 2, parent.width - implicitWidth))
        visible: !!(tab.cur && tab.cur.promoteAt !== null)
        textFormat: Text.PlainText
        text: tab.cur && tab.cur.promoteAt !== null ? tab.cur.promoteAt + " XP" : ""
        color: Util.alpha(w.green, 0.9)
        font.family: w.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Text {
      width: parent.width
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: tab.zoneLine()
      color: Util.alpha(w.fg, 0.8)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }

    Text {
      width: parent.width
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: tab.cur && tab.cur.reference !== null
        ? "Your average of the last 4 weeks: " + Math.round(tab.cur.reference) + " XP. Promotion takes 10 % more and the next league's floor; relegation, under 90 % and under this league's floor, or an empty week."
        : "First weeks: the league floors decide. Promotion needs the next league's floor."
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
