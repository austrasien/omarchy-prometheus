import QtQuick
import qs.Commons

// The share card, styled as a military ID: a league-colored band, an insignia
// with the league gem and rank chevrons, service fields, the medal rack, the
// legendary achievements, a holographic seal and a machine-readable strip.
// `frame` (0 to 1) drives every shine, so the card can be captured frame by
// frame into an animated PNG. It sits off to the side of the panel: only
// grabbed, never seen.
Rectangle {
  id: card

  property var w: null
  property var info: null          // share:get
  property real frame: 0           // 0 to 1: where every shine is in its cycle

  readonly property var profile: info ? info.profile : null
  readonly property var league: info ? info.league : null
  readonly property color leagueColor: league ? league.color : "#cd7f32"
  readonly property var medals: info ? (info.seasonMedals || []).concat(info.medals || []) : []
  readonly property var seasons: info ? (info.seasons || []) : []
  readonly property var legendary: info ? (info.legendary || []) : []
  readonly property color ink: "#e6e2cf"          // the card's printed text, warm off-white
  readonly property color dim: Qt.rgba(0.90, 0.88, 0.81, 0.55)
  readonly property string mono: w ? w.fontFamily : "monospace"

  width: 600
  // As tall as its content: compact, whatever the number of medals.
  height: Math.max(rack.y + rack.implicitHeight, sealBox.y + sealBox.height) + 14 + strip.height
  radius: 16
  clip: true
  color: "#1b2117"
  border.width: 2
  border.color: Qt.darker(leagueColor, 1.4)

  function gradeColor(g) {
    return g === "S" ? w.legendaryColor : g === "A" ? w.gold : g === "B" ? w.green : g === "C" ? ink
      : g === "D" ? "#ea9a23" : g === "F" ? w.red : dim
  }
  function tokens(t) {
    return t >= 1e9 ? (t / 1e9).toFixed(2) + "B" : t >= 1e6 ? (t / 1e6).toFixed(1) + "M" : t >= 1e3 ? Math.round(t / 1e3) + "K" : String(t)
  }

    function upper(s) { return (s || "").toUpperCase() }
  function enlisted(iso) { return iso ? upper(Qt.formatDate(new Date(iso + "T12:00:00"), "dd MMM yyyy")) : "—" }
  function shortSeason(label) {          // "Autumn 2026" -> "AUT 26"
    var parts = (label || "").split(" ")
    return parts.length === 2 ? upper(parts[0].slice(0, 3)) + " " + parts[1].slice(2) : upper(label)
  }
  function mrz(s, n) {
    var t = upper(s).replace(/[^A-Z0-9]/g, "<")
    while (t.length < n) t += "<"
    return t.slice(0, n)
  }

  // ---- background: a soft gradient and fine guilloche lines
  Rectangle {
    anchors.fill: parent
    gradient: Gradient {
      GradientStop { position: 0.0; color: "#232b1e" }
      GradientStop { position: 1.0; color: "#141812" }
    }
  }
  Item {
    anchors.fill: parent
    opacity: 0.07
    Repeater {
      model: 46
      Rectangle {
        required property int index
        x: index * 18 - 200
        y: -40
        width: 1
        height: card.height * 1.6
        rotation: 32
        color: card.ink
      }
    }
  }
  // A large faint gem, watermark-style.
  Rectangle {
    x: card.width - 190
    y: 70
    width: 220
    height: 220
    rotation: 45
    color: "transparent"
    border.width: 18
    border.color: card.leagueColor
    opacity: 0.06
  }

  // ---- the band
  Rectangle {
    id: band
    width: parent.width
    height: 36
    gradient: Gradient {
      orientation: Gradient.Horizontal
      GradientStop { position: 0.0; color: Qt.darker(card.leagueColor, 2.2) }
      GradientStop { position: 1.0; color: Qt.darker(card.leagueColor, 3.2) }
    }

    Text {
      x: 18
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: "PROMETHEUS"
      color: card.ink
      font.family: card.mono
      font.pixelSize: 15
      font.bold: true
      font.letterSpacing: 4
    }
    Text {
      anchors.right: parent.right
      anchors.rightMargin: 18
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: "SERVICE IDENTIFICATION CARD"
      color: card.dim
      font.family: card.mono
      font.pixelSize: 10
      font.bold: true
      font.letterSpacing: 2
    }
  }
  Rectangle { y: band.height; width: parent.width; height: 2; color: Qt.darker(w.gold, 1.2) }

  // ---- the insignia
  Rectangle {
    id: insignia
    x: 18
    y: 52
    width: 118
    height: 150
    radius: 8
    color: Qt.rgba(0, 0, 0, 0.25)
    border.width: 1
    border.color: Qt.rgba(0.9, 0.88, 0.8, 0.25)

    // The league's insignia shape, with a glint passing over it.
    LeagueGem {
      anchors.horizontalCenter: parent.horizontalCenter
      y: 14
      width: 54
      height: 54
      league: card.league && card.league.index !== undefined ? card.league.index : 0
      color: card.leagueColor
      glint: card.frame
    }

    // Rank chevrons: one per five levels, three at most.
    Column {
      anchors.horizontalCenter: parent.horizontalCenter
      y: 76
      spacing: -6
      Repeater {
        model: card.profile ? Math.max(1, Math.min(3, Math.ceil(card.profile.level / 5))) : 1
        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          textFormat: Text.PlainText
          text: "︿"
          color: w.gold
          font.pixelSize: 22
          font.bold: true
        }
      }
    }

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.bottom: parent.bottom
      anchors.bottomMargin: 10
      textFormat: Text.PlainText
      text: card.league ? card.upper(card.league.name) : ""
      color: card.leagueColor
      font.family: card.mono
      font.pixelSize: 12
      font.bold: true
      font.letterSpacing: 2
    }
  }

  // ---- service fields
  Grid {
    id: fields
    x: 152
    y: 52
    columns: 2
    columnSpacing: 22
    rowSpacing: 6

    Repeater {
      model: [
        { k: "NAME", v: card.info && card.info.handle ? "@" + card.info.handle : "@anonymous", big: true },
        { k: "SERVICE NO.", v: card.info ? card.info.serviceNumber : "" },
        { k: "RANK", v: card.profile ? "LEVEL " + card.profile.level : "" },
        { k: "XP", v: card.profile ? card.profile.xp + " XP" : "" },
        { k: "LEAGUE", v: card.league ? card.upper(card.league.name) : "" },
        { k: "ENLISTED", v: card.enlisted(card.info ? card.info.firstDay : null) },
        { k: "TOKENS BURNED", v: card.tokens(card.info && card.info.agents ? card.info.agents.tokens : 0) },
        { k: "COMPUTE", v: card.info && card.info.agents ? "$" + Math.round(card.info.agents.cost) : "$0" }
      ]
      Column {
        required property var modelData
        spacing: 1
        Text {
          textFormat: Text.PlainText
          text: modelData.k
          color: card.dim
          font.family: card.mono
          font.pixelSize: 8
          font.bold: true
          font.letterSpacing: 1.5
        }
        Text {
          textFormat: Text.PlainText
          text: modelData.v
          color: card.ink
          font.family: card.mono
          font.pixelSize: modelData.big ? 17 : 12
          font.bold: true
        }
      }
    }
  }

  // XP toward the next level, a thin bar under the fields.
  Rectangle {
    x: 152
    y: fields.y + fields.height + 8
    width: card.width - 152 - 140
    height: 4
    radius: 2
    color: Qt.rgba(0.9, 0.88, 0.8, 0.15)
    Rectangle {
      height: parent.height
      radius: 2
      width: card.profile ? parent.width * Math.min(1, card.profile.levelXp / Math.max(1, card.profile.levelCost)) : 0
      color: w.gold
    }
  }

  // ---- service record: every season, as compact chips
  Column {
    x: card.width - 124
    y: 52
    width: 106
    spacing: 3

    Text {
      textFormat: Text.PlainText
      text: "SERVICE RECORD"
      color: card.dim
      font.family: card.mono
      font.pixelSize: 8
      font.bold: true
      font.letterSpacing: 1.5
    }
    Repeater {
      model: card.seasons.slice(0, 6)
      Item {
        required property var modelData
        width: 106
        height: 15
        Text {
          textFormat: Text.PlainText
          text: card.shortSeason(modelData.label)
          color: card.ink
          font.family: card.mono
          font.pixelSize: 10
          font.bold: true
          anchors.verticalCenter: parent.verticalCenter
        }
        RarityText {
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: implicitWidth
          text: modelData.running ? "…" : modelData.grade
          color: card.gradeColor(modelData.running ? "" : modelData.grade)
          legendary: !modelData.running && modelData.grade === "S"
          sweepOverride: card.frame
          fontFamily: card.mono
          pixelSize: 12
        }
      }
    }
  }

  // ---- the medal rack
  Column {
    id: rack
    x: 18
    y: 214
    width: card.width - 36 - 70
    spacing: 4

    Text {
      textFormat: Text.PlainText
      text: "DECORATIONS"
      color: card.dim
      font.family: card.mono
      font.pixelSize: 8
      font.bold: true
      font.letterSpacing: 1.5
    }

    Flow {
      width: parent.width
      spacing: 2
      Repeater {
        model: card.medals
        Item {
          required property var modelData
          readonly property bool season: modelData.period === "season"
          width: season ? holo.width : plain.width
          height: season ? holo.height : plain.height
          // A band of light sweeps across the whole rack, seen only on the
          // ribbons themselves.
          Item {
            id: medalCell
            anchors.fill: parent
            z: 2
            clip: true
            Rectangle {
              readonly property real sweep: rack.width + 120
              width: 26
              height: medalCell.height * 3
              anchors.verticalCenter: parent.verticalCenter
              rotation: 25
              x: -60 + sweep * card.frame - medalCell.parent.x
              gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "#00ffffff" }
                GradientStop { position: 0.5; color: "#d8ffffff" }
                GradientStop { position: 1.0; color: "#00ffffff" }
              }
            }
          }

          HoloRibbon {
            id: holo
            visible: parent.season
            size: 1.25
            phaseOverride: card.frame
            color: parent.season ? parent.modelData.color : "#555"
            dot: parent.season ? parent.modelData.dot : "white"
            edge: parent.season ? parent.modelData.edge : "#999"
            edges: parent.season && parent.modelData.bars === 2 ? "both" : "left"
          }
          Ribbon {
            id: plain
            visible: !parent.season
            size: 1.25
            color: parent.modelData.color
            dot: parent.modelData.dot
            dots: parent.modelData.dots || 1
            edges: parent.modelData.edges || "none"
          }
        }
      }
    }

    // League stamps: one per shining league, inked for each round finished
    // in it.
    Text {
      visible: !!card.info && !!card.info.stamps && card.info.stamps.length > 0
      topPadding: 4
      textFormat: Text.PlainText
      text: "LEAGUE STAMPS"
      color: card.dim
      font.family: card.mono
      font.pixelSize: 8
      font.bold: true
      font.letterSpacing: 1.5
    }
    Row {
      visible: !!card.info && !!card.info.stamps && card.info.stamps.length > 0
      spacing: 6
      Repeater {
        model: card.info && card.info.stamps ? card.info.stamps : []
        Stamp {
          required property var modelData
          league: modelData.index
          name: modelData.name
          ink: modelData.color
          count: modelData.count
          fontFamily: card.mono
        }
      }
    }

    // Legendary achievements, gold and shining.
    Flow {
      width: parent.width
      spacing: 8
      visible: card.legendary.length > 0
      Text {
        textFormat: Text.PlainText
        text: "★ LEGENDARY"
        color: w.legendaryColor
        font.family: card.mono
        font.pixelSize: 9
        font.bold: true
        font.letterSpacing: 1
      }
      Repeater {
        model: card.legendary.slice(0, 8)
        RarityText {
          required property string modelData
          width: implicitWidth
          text: modelData
          color: w.legendaryColor
          legendary: true
          sweepOverride: card.frame
          fontFamily: card.mono
          pixelSize: 10
        }
      }
    }
  }

  // ---- the holographic seal: a round foil, its rainbow drifting with `frame`
  Item {
    id: sealBox
    x: card.width - 78
    y: 214
    width: 58
    height: 58

    Canvas {
      id: seal
      anchors.fill: parent
      property real phase: card.frame
      onPhaseChanged: requestPaint()
      onPaint: {
        var ctx = getContext("2d")
        var r = width / 2
        ctx.reset()
        ctx.save()
        ctx.beginPath()
        ctx.arc(r, r, r - 1, 0, 2 * Math.PI)
        ctx.clip()
        ctx.fillStyle = "#3a3f4a"
        ctx.fillRect(0, 0, width, height)
        var colors = ["#ff6b6b", "#ffd66b", "#7dff7d", "#6be6ff", "#7d7dff", "#ff7dff"]
        var span = width * 2.4
        var start = -span + span * phase
        var g = ctx.createLinearGradient(start, 0, start + span * 2, height * 0.6)
        for (var k = 0; k <= 12; k++) g.addColorStop(k / 12, colors[k % colors.length])
        ctx.globalAlpha = 0.75
        ctx.fillStyle = g
        ctx.fillRect(0, 0, width, height)
        ctx.restore()
        ctx.beginPath()
        ctx.arc(r, r, r - 1, 0, 2 * Math.PI)
        ctx.lineWidth = 2
        ctx.strokeStyle = "rgba(255,255,255,0.4)"
        ctx.stroke()
      }
    }
    Text {
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: "P"
      color: Qt.rgba(1, 1, 1, 0.9)
      font.family: card.mono
      font.pixelSize: 24
      font.bold: true
      style: Text.Outline
      styleColor: Qt.rgba(0, 0, 0, 0.35)
    }
  }

  // ---- a hologram sweeping the whole card: a wide rainbow-tinted band of
  // light crossing it diagonally once per loop
  Item {
    anchors.fill: parent
    z: 10
    Rectangle {
      width: 170
      height: card.height * 2.2
      y: -card.height * 0.6
      rotation: 24
      x: -260 + (card.width + 420) * card.frame
      opacity: 0.22
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0.00; color: "#00ffffff" }
        GradientStop { position: 0.30; color: "#66ff9ad5" }
        GradientStop { position: 0.45; color: "#ffffffff" }
        GradientStop { position: 0.55; color: "#ff9adfff" }
        GradientStop { position: 0.70; color: "#66b4ff9a" }
        GradientStop { position: 1.00; color: "#00ffffff" }
      }
    }
  }

  // ---- the machine-readable strip
  Rectangle {
    id: strip
    anchors.bottom: parent.bottom
    width: parent.width
    height: 40
    color: Qt.rgba(0, 0, 0, 0.28)
    Column {
      x: 18
      anchors.verticalCenter: parent.verticalCenter
      spacing: 1
      Text {
        textFormat: Text.PlainText
        text: "ID" + "PRM" + "<<" + card.mrz(card.info ? card.info.handle || "ANONYMOUS" : "", 28) + card.mrz("", 10)
        color: card.dim
        font.family: card.mono
        font.pixelSize: 11
        font.letterSpacing: 1.5
      }
      Text {
        textFormat: Text.PlainText
        text: card.mrz((card.info ? (card.info.serviceNumber || "").replace(/-/g, "") : "") + "<"
          + (card.info && card.info.firstDay ? card.info.firstDay.replace(/-/g, "") : "") + "<"
          + (card.league ? card.league.name : "") + "<LV" + (card.profile ? card.profile.level : ""), 40)
        color: card.dim
        font.family: card.mono
        font.pixelSize: 11
        font.letterSpacing: 1.5
      }
    }
  }
}
