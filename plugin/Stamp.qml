import QtQuick

// A rubber stamp on the ID card, one per shining league: inked in the
// league's color (a double ring, the league's star, its name and the number
// of rounds finished in it), a little askew like a real stamp. Not earned
// yet: a faint dashed outline.
Item {
  id: stamp

  property int league: 5
  property string name: ""
  property color ink: "#50c878"
  property int count: 0
  property string fontFamily: ""
  readonly property bool earned: count > 0

  width: 58
  height: 58
  rotation: [-11, 7, -4, 12, -8][(league - 5 + 5) % 5]

  Canvas {
    id: rings
    anchors.fill: parent
    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      var c = width / 2
      ctx.strokeStyle = stamp.earned ? stamp.ink : "rgba(230,226,207,0.22)"
      ctx.globalAlpha = stamp.earned ? 0.9 : 1
      if (!stamp.earned) ctx.setLineDash ? ctx.setLineDash([3, 3]) : null
      ctx.lineWidth = stamp.earned ? 2.6 : 1.2
      ctx.beginPath(); ctx.arc(c, c, c - 2, 0, 2 * Math.PI); ctx.stroke()
      if (stamp.earned) {
        ctx.lineWidth = 1
        ctx.beginPath(); ctx.arc(c, c, c - 6, 0, 2 * Math.PI); ctx.stroke()
        // Ink worn here and there.
        ctx.globalCompositeOperation = "destination-out"
        for (var k = 0; k < 7; k++) {
          var a = (k * 97 + stamp.league * 31) % 360 * Math.PI / 180
          ctx.beginPath()
          ctx.arc(c + (c - 3) * Math.cos(a), c + (c - 3) * Math.sin(a), 1.6, 0, 2 * Math.PI)
          ctx.fill()
        }
      }
    }
    Component.onCompleted: requestPaint()
  }

  Text {
    anchors.horizontalCenter: parent.horizontalCenter
    y: 9
    textFormat: Text.PlainText
    text: stamp.name.toUpperCase()
    color: stamp.earned ? stamp.ink : Qt.rgba(0.9, 0.88, 0.81, 0.25)
    opacity: stamp.earned ? 0.9 : 1
    font.family: stamp.fontFamily
    font.pixelSize: 7
    font.bold: true
    font.letterSpacing: 0.5
  }

  LeagueGem {
    anchors.centerIn: parent
    width: 18
    height: 18
    league: stamp.league
    color: stamp.ink
    fill: stamp.earned ? 0.9 : 0.18
  }

  Text {
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 9
    textFormat: Text.PlainText
    text: stamp.earned ? "×" + stamp.count : "—"
    color: stamp.earned ? stamp.ink : Qt.rgba(0.9, 0.88, 0.81, 0.25)
    opacity: stamp.earned ? 0.9 : 1
    font.family: stamp.fontFamily
    font.pixelSize: 8
    font.bold: true
  }
}
