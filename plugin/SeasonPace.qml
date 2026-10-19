import QtQuick
import qs.Commons

// The running season's XP, cumulative day by day, against the steady pace
// that reaches the goal and the hard goal at the season's end (straight
// lines from the first day). Above a line: ahead of that pace.
Item {
  id: chart

  property var w: null
  property var season: null       // a running season from seasons:get (pace, firstDay, end, goal, hardGoal)
  property color lineColor: "#30b2bf"

  height: Style.space(110)

  function dayIndex(iso) {
    return Math.round((new Date(iso + "T12:00:00") - new Date(season.firstDay + "T12:00:00")) / 86400000)
  }
  readonly property int span: season ? dayIndex(season.end) + 1 : 1
  readonly property real scaleMax: season ? Math.max(season.hardGoal, season.pace.length ? season.pace[season.pace.length - 1].xp : 0) * 1.05 : 1
  readonly property real plotH: height - Style.space(22)

  Canvas {
    id: canvas
    anchors.fill: parent
    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      var s = chart.season
      if (!s || !s.pace) return
      var W = width, H = chart.plotH
      function X(d) { return d / chart.span * W }
      function Y(v) { return H - v / chart.scaleMax * H + 2 }
      // Goal paces, dashed.
      var lines = [[s.goal, "rgba(224,175,104,0.75)"], [s.hardGoal, "rgba(247,118,142,0.75)"]]
      ctx.setLineDash([4, 3])
      ctx.lineWidth = 1.2
      for (var k = 0; k < lines.length; k++) {
        ctx.strokeStyle = lines[k][1]
        ctx.beginPath(); ctx.moveTo(X(0), Y(0)); ctx.lineTo(X(chart.span), Y(lines[k][0])); ctx.stroke()
      }
      ctx.setLineDash([])
      // Today.
      var today = s.pace.length - 1
      ctx.strokeStyle = "rgba(255,255,255,0.12)"
      ctx.beginPath(); ctx.moveTo(X(today + 1), 0); ctx.lineTo(X(today + 1), H + 2); ctx.stroke()
      // XP so far, filled below.
      ctx.beginPath(); ctx.moveTo(X(0), Y(0))
      for (var i = 0; i < s.pace.length; i++) ctx.lineTo(X(i + 1), Y(s.pace[i].xp))
      ctx.lineTo(X(s.pace.length), Y(0)); ctx.closePath()
      ctx.fillStyle = Qt.rgba(chart.lineColor.r, chart.lineColor.g, chart.lineColor.b, 0.18)
      ctx.fill()
      ctx.beginPath(); ctx.moveTo(X(0), Y(0))
      for (var j = 0; j < s.pace.length; j++) ctx.lineTo(X(j + 1), Y(s.pace[j].xp))
      ctx.strokeStyle = chart.lineColor
      ctx.lineWidth = 2
      ctx.stroke()
    }
  }
  onSeasonChanged: canvas.requestPaint()
  onWidthChanged: canvas.requestPaint()

  // Where you stand against each pace, today.
  readonly property real ideal: season && season.pace.length ? season.pace.length / span : 0
  readonly property real xpNow: season && season.pace.length ? season.pace[season.pace.length - 1].xp : 0
  function gap(target) {
    var d = Math.round(xpNow - target * ideal)
    return (d >= 0 ? "+" : "") + d
  }

  Row {
    anchors.bottom: parent.bottom
    spacing: Style.space(12)
    Text {
      textFormat: Text.PlainText
      text: "— you " + Math.round(chart.xpNow)
      color: chart.lineColor
      font.family: chart.w.fontFamily
      font.pixelSize: Style.font.caption - 1
    }
    Text {
      textFormat: Text.PlainText
      text: "- - goal " + (chart.season ? chart.gap(chart.season.goal) : "")
      color: "#e0af68"
      font.family: chart.w.fontFamily
      font.pixelSize: Style.font.caption - 1
    }
    Text {
      textFormat: Text.PlainText
      text: "- - hard " + (chart.season ? chart.gap(chart.season.hardGoal) : "")
      color: "#f7768e"
      font.family: chart.w.fontFamily
      font.pixelSize: Style.font.caption - 1
    }
  }
}
