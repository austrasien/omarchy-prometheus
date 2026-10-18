import QtQuick
import qs.Commons
import qs.Ui

// Leagues tab: ten leagues, Bronze to Diamond, one two-week round at a time
// against nine rivals. Shows the ladder (Emerald and up shine), where this
// round stands (relegation, stagnation or promotion zone) and past rounds.
Column {
  id: tab

  property var w: null
  property var p: null
  property var info: null      // leagues:get
  property string openBio: ""  // the rival whose short bio is shown

  readonly property bool editing: false
  function focusEntry() { return false }
  spacing: Style.space(10)

  function refresh() {
    if (!p || !p.live) return
    p.call("leagues:get", [], function(ok, d) { if (ok && d && d.success) tab.info = d })
  }
  // Reopening the tab starts with every bio closed.
  onVisibleChanged: if (visible) { openBio = ""; refresh() }
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
      return cur.top ? "Top of the table in Diamond. Nowhere higher to go: hold it." : "Bravo! If the round ended now, you would go up to " + next + "."
    if (cur.zone === "relegation") {
      if (cur.bottom) return cur.toSafety + " XP more to climb out of the bottom 3. Bronze has no floor below, but still."
      return "If the round ended now, you would drop to " + below + ". " + cur.toSafety + " XP more to get out of the bottom 3."
    }
    if (cur.top) return "You stay in Diamond, the top league."
    if (cur.rank <= 3 && cur.promotionMin !== null)
      return "Top 3, but promotion out of " + here + " takes " + cur.promotionMin + " XP over the round (" + cur.promotionMinSoFar + " by now): " + cur.toPromotion + " XP more."
    return "You stay in " + here + ". " + cur.toPromotion + " XP more to be promoted (top 3, and " + cur.promotionMin + " XP over the round)."
  }

  function roundLabel(start, end) {
    return weekLabel(start) + " – " + weekLabel(end)
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
            id: gem
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

          // Emerald and up: a reflection runs across the gem, one gem after
          // the other, at full brightness even on a league not reached yet.
          Item {
            visible: index >= 5
            anchors.centerIn: parent
            width: gem.width
            height: gem.height
            rotation: 45
            clip: true

            Rectangle {
              id: glint
              width: parent.width * 0.45
              height: parent.height * 1.6
              y: -parent.height * 0.3
              x: -width
              rotation: 45
              gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "#00ffffff" }
                GradientStop { position: 0.5; color: "#f0ffffff" }
                GradientStop { position: 1.0; color: "#00ffffff" }
              }
              SequentialAnimation on x {
                running: index >= 5 && tab.visible
                loops: Animation.Infinite
                PauseAnimation { duration: Math.max(0, (index - 5) * 180) }
                NumberAnimation { from: -glint.width; to: glint.parent.width + glint.width * 0.2; duration: 650; easing.type: Easing.InOutQuad }
                PauseAnimation { duration: Math.max(0, 1800 - (index - 5) * 180) }
              }
            }
          }
        }
      }
    }
  }

  // The league's name; from Emerald up, a light sweeps across it.
  RarityText {
    anchors.horizontalCenter: parent.horizontalCenter
    width: implicitWidth
    text: tab.cur ? tab.cur.name + " League" : "…"
    color: tab.cur ? tab.cur.color : w.fg
    legendary: !!tab.cur && tab.cur.shining
    fontFamily: w.fontFamily
    pixelSize: Style.font.body + 4
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
        text: tab.cur ? tab.cur.daysLeft + (tab.cur.daysLeft === 1 ? " day left" : " days left") + " in the round" : ""
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
        readonly property bool bioOpen: !modelData.you && !!modelData.bio && tab.openBio === modelData.name
        width: tab.width
        height: (zoneStart ? zoneLabel.implicitHeight + Style.space(4) : 0) + playerRow.height
          + (bioOpen ? bioText.implicitHeight + Style.space(6) : 0)

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
          y: player.zoneStart ? zoneLabel.implicitHeight + Style.space(4) : 0
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
            color: player.modelData.you ? w.fg : nameArea.containsMouse || player.bioOpen ? w.accent : Util.alpha(w.fg, 0.7)
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: player.modelData.you
          }

          // A rival's name opens (or closes) a one-line bio.
          MouseArea {
            id: nameArea
            anchors.fill: parent
            enabled: !player.modelData.you && !!player.modelData.bio
            hoverEnabled: true
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: tab.openBio = player.bioOpen ? "" : player.modelData.name
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

        Text {
          id: bioText
          visible: player.bioOpen
          anchors.top: playerRow.bottom
          anchors.topMargin: Style.space(3)
          x: Style.space(30)
          width: parent.width - x - Style.space(6)
          wrapMode: Text.WordWrap
          textFormat: Text.PlainText
          text: player.modelData.bio ? player.modelData.bio.life + "  ·  " + player.modelData.bio.line : ""
          color: Util.alpha(w.fg, 0.7)
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
          font.italic: true
        }
      }
    }

    Text {
      width: parent.width
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: "Rounds last two weeks, Sunday to the second Saturday. Your rivals are drawn each round from your last two rounds"
        + (tab.cur && tab.cur.reference !== null ? " (average " + Math.round(tab.cur.reference) + " XP)" : "")
        + ", never weaker than the league's level, and earn their XP as the round goes. Top 3 go up if they reach the league's minimum (600 XP a round in Bronze, more above, prorated as the round goes); bottom 3 go down; one league at most. An empty round always goes down."
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
      text: "PAST ROUNDS"
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
          text: tab.roundLabel(modelData.week, modelData.end || modelData.week) + "  ·  " + modelData.xp + " XP"
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
