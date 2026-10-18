import QtQuick
import qs.Commons

// The share card: what is grabbed into a PNG when the player shares. Built
// from share:get. Not shown in the panel (it sits off to the side); it only
// has to be laid out to be grabbed.
Rectangle {
  id: card

  property var w: null
  property var info: null          // share:get

  readonly property var profile: info ? info.profile : null
  readonly property var league: info ? info.league : null
  readonly property var medals: info ? (info.seasonMedals || []).concat(info.medals || []) : []
  readonly property var seasons: info ? info.seasons || [] : []

  width: 560
  height: content.implicitHeight + 56
  radius: 18
  color: "#16171f"
  border.width: 2
  border.color: league ? Qt.darker(league.color, 1.3) : "#333"

  function gradeColor(g) {
    return g === "S" ? w.legendaryColor : g === "A" ? w.gold : g === "B" ? w.green : g === "C" ? w.fg
      : g === "D" ? "#ea9a23" : w.red
  }

  function dateLabel(iso) { return iso ? Qt.formatDate(new Date(iso + "T12:00:00"), "MMMM d, yyyy") : "" }

  Column {
    id: content
    x: 28
    y: 28
    width: card.width - 56
    spacing: 14

    // ---- who
    Item {
      width: parent.width
      height: Math.max(title.implicitHeight + handle.implicitHeight + 4, leagueBox.height)

      Text {
        id: title
        textFormat: Text.PlainText
        text: "PROMETHEUS"
        color: w.accent
        font.family: w.fontFamily
        font.pixelSize: 13
        font.bold: true
        font.letterSpacing: 3
      }

      Text {
        id: handle
        anchors.top: title.bottom
        anchors.topMargin: 4
        textFormat: Text.PlainText
        text: card.info && card.info.handle ? "@" + card.info.handle : "@anonymous"
        color: w.fg
        font.family: w.fontFamily
        font.pixelSize: 26
        font.bold: true
      }

      Column {
        id: leagueBox
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2

        Text {
          anchors.right: parent.right
          textFormat: Text.PlainText
          text: card.league ? card.league.name + " League" : ""
          color: card.league ? card.league.color : w.fg
          font.family: w.fontFamily
          font.pixelSize: 17
          font.bold: true
        }

        Text {
          anchors.right: parent.right
          textFormat: Text.PlainText
          text: card.profile ? "Level " + card.profile.level : ""
          color: w.gold
          font.family: w.fontFamily
          font.pixelSize: 15
          font.bold: true
        }
      }
    }

    // ---- XP and the bar
    Column {
      width: parent.width
      spacing: 6

      Item {
        width: parent.width
        height: xpText.implicitHeight

        Text {
          id: xpText
          textFormat: Text.PlainText
          text: card.profile ? card.profile.xp + " XP" : ""
          color: w.fg
          font.family: w.fontFamily
          font.pixelSize: 15
          font.bold: true
        }

        Text {
          anchors.right: parent.right
          anchors.verticalCenter: xpText.verticalCenter
          textFormat: Text.PlainText
          text: card.profile ? card.profile.levelXp + " / " + card.profile.levelCost + " to level " + (card.profile.level + 1) : ""
          color: Util.alpha(w.fg, 0.6)
          font.family: w.fontFamily
          font.pixelSize: 12
        }
      }

      Rectangle {
        width: parent.width
        height: 8
        radius: 4
        color: Util.alpha(w.fg, 0.12)

        Rectangle {
          height: parent.height
          radius: parent.radius
          width: card.profile ? parent.width * Math.min(1, card.profile.levelXp / Math.max(1, card.profile.levelCost)) : 0
          color: w.gold
        }
      }
    }

    // ---- every medal: the seasons' first, then month, week, day
    Flow {
      width: parent.width
      spacing: 3
      visible: card.medals.length > 0

      Repeater {
        model: card.medals

        Item {
          required property var modelData
          readonly property bool season: modelData.period === "season"
          width: season ? holo.width : plain.width
          height: season ? holo.height : plain.height

          HoloRibbon {
            id: holo
            visible: parent.season
            size: 1.6
            shining: false
            color: parent.season ? parent.modelData.color : "#555"
            dot: parent.season ? parent.modelData.dot : "white"
            edge: parent.season ? parent.modelData.edge : "#999"
            edges: parent.season && parent.modelData.bars === 2 ? "both" : "left"
          }

          Ribbon {
            id: plain
            visible: !parent.season
            size: 1.6
            color: parent.modelData.color
            dot: parent.modelData.dot
            dots: parent.modelData.dots || 1
            edges: parent.modelData.edges || "none"
          }
        }
      }
    }

    Rectangle { width: parent.width; height: 1; color: Util.alpha(w.fg, 0.12) }

    // ---- every season
    Text {
      textFormat: Text.PlainText
      text: "SEASONS"
      color: Util.alpha(w.fg, 0.55)
      font.family: w.fontFamily
      font.pixelSize: 11
      font.bold: true
      font.letterSpacing: 2
    }

    Repeater {
      model: card.seasons

      Item {
        required property var modelData
        width: content.width
        height: seasonGrade.implicitHeight

        Text {
          id: seasonGrade
          width: 34
          textFormat: Text.PlainText
          text: modelData.running ? "…" : modelData.grade
          color: modelData.running ? Util.alpha(w.fg, 0.5) : card.gradeColor(modelData.grade)
          font.family: w.fontFamily
          font.pixelSize: 22
          font.bold: true
        }

        Text {
          anchors.left: seasonGrade.right
          anchors.verticalCenter: seasonGrade.verticalCenter
          textFormat: Text.PlainText
          text: modelData.label + (modelData.running ? "  ·  in progress" : "")
          color: w.fg
          font.family: w.fontFamily
          font.pixelSize: 14
          font.bold: true
        }

        Text {
          anchors.right: parent.right
          anchors.verticalCenter: seasonGrade.verticalCenter
          textFormat: Text.PlainText
          text: modelData.xp + " / " + modelData.goal + " XP"
          color: Util.alpha(w.fg, 0.7)
          font.family: w.fontFamily
          font.pixelSize: 13
        }
      }
    }

    Rectangle { width: parent.width; height: 1; color: Util.alpha(w.fg, 0.12) }

    Item {
      width: parent.width
      height: since.implicitHeight

      Text {
        id: since
        textFormat: Text.PlainText
        text: card.info && card.info.firstDay ? "Playing since " + card.dateLabel(card.info.firstDay) : ""
        color: Util.alpha(w.fg, 0.6)
        font.family: w.fontFamily
        font.pixelSize: 12
      }

      Text {
        anchors.right: parent.right
        textFormat: Text.PlainText
        text: "omarchy-prometheus"
        color: Util.alpha(w.fg, 0.35)
        font.family: w.fontFamily
        font.pixelSize: 11
      }
    }
  }
}
