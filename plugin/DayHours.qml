import QtQuick
import qs.Commons

// The day hour by hour (coffee:day), from the day start: time in session
// (blue bars), agent tokens (thin orange bars), cups, tasks checked and
// quests finished above each hour, and the caffeine in the blood as a
// curve, with the threshold under which a cup is worth it, now, and the
// best time for the next one.
Item {
  id: root

  property var w: null
  property var info: null              // coffee:day
  property color agentColor: "#ff9e64"
  property color coffeeColor: "#c08552"

  readonly property var hours: info ? info.hours : []
  readonly property real colW: width / 24
  readonly property real chartTop: Style.space(30)
  readonly property real chartH: Style.space(70)
  readonly property real maxTokens: Math.max(1, Math.max.apply(null, hours.map(function(h) { return h.tokens }).concat([0])))
  readonly property real maxMg: {
    var m = info ? info.lowMg * 2 : 120
    var c = info ? info.caffeine : []
    for (var i = 0; i < c.length; i++) m = Math.max(m, c[i].mg)
    return m * 1.1
  }
  function xOf(ms) { return info ? (ms - info.fromMs) / (info.toMs - info.fromMs) * width : 0 }
  function yOfMg(mg) { return chartTop + chartH - mg / maxMg * chartH }
  function clock(ms) { return Qt.formatTime(new Date(ms), "HH:mm") }

  height: chartTop + chartH + Style.space(16)

  // Above each hour: cups, tasks, quests.
  Repeater {
    model: root.hours
    Column {
      required property var modelData
      required property int index
      x: index * root.colW
      width: root.colW
      y: 0
      spacing: 0
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        visible: modelData.cups > 0
        textFormat: Text.PlainText
        text: modelData.cups > 1 ? "☕" + modelData.cups : "☕"
        color: root.coffeeColor
        font.pixelSize: Style.font.caption - 2
      }
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        visible: modelData.tasks > 0 || modelData.quests > 0
        textFormat: Text.PlainText
        text: (modelData.quests > 0 ? "★" : "") + (modelData.tasks > 0 ? "✓" + modelData.tasks : "")
        color: modelData.quests > 0 ? root.w.red : root.w.gold
        font.family: root.w.fontFamily
        font.pixelSize: Style.font.caption - 3
      }
    }
  }

  // Grid, session time and tokens per hour.
  Repeater {
    model: root.hours
    Item {
      required property var modelData
      required property int index
      x: index * root.colW
      y: root.chartTop
      width: root.colW
      height: root.chartH
      Rectangle {
        anchors.left: parent.left
        width: 1
        height: parent.height
        color: Util.alpha(root.w.fg, index % 6 === 0 ? 0.12 : 0.04)
      }
      Rectangle {
        anchors.bottom: parent.bottom
        x: 1
        width: parent.width * 0.6 - 1
        height: parent.height * Math.min(60, modelData.focus) / 60
        radius: 1
        color: Util.alpha(root.w.accent, 0.55)
      }
      Rectangle {
        anchors.bottom: parent.bottom
        x: parent.width * 0.62
        width: Math.max(1, parent.width * 0.28)
        visible: modelData.tokens > 0
        height: Math.max(1, parent.height * Math.sqrt(modelData.tokens / root.maxTokens))
        color: Util.alpha(root.agentColor, 0.8)
      }
    }
  }

  // Caffeine in the blood, the threshold, now and the best time for a cup.
  Canvas {
    id: curve
    anchors.fill: parent
    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      var info = root.info
      if (!info) return
      var pts = info.caffeine
      // Threshold under which a cup is worth it.
      ctx.setLineDash([3, 3])
      ctx.strokeStyle = Qt.rgba(root.coffeeColor.r, root.coffeeColor.g, root.coffeeColor.b, 0.5)
      ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(0, root.yOfMg(info.lowMg)); ctx.lineTo(width, root.yOfMg(info.lowMg)); ctx.stroke()
      ctx.setLineDash([])
      if (pts.length > 1) {
        ctx.beginPath()
        ctx.moveTo(root.xOf(pts[0].at), root.yOfMg(0))
        for (var i = 0; i < pts.length; i++) ctx.lineTo(root.xOf(pts[i].at), root.yOfMg(pts[i].mg))
        ctx.lineTo(root.xOf(pts[pts.length - 1].at), root.yOfMg(0))
        ctx.closePath()
        ctx.fillStyle = Qt.rgba(root.coffeeColor.r, root.coffeeColor.g, root.coffeeColor.b, 0.18)
        ctx.fill()
        ctx.beginPath()
        for (var j = 0; j < pts.length; j++) {
          var x = root.xOf(pts[j].at), y = root.yOfMg(pts[j].mg)
          if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
        }
        ctx.strokeStyle = root.coffeeColor
        ctx.lineWidth = 2
        ctx.stroke()
      }
      // Now.
      if (info.now >= info.fromMs && info.now < info.toMs) {
        ctx.strokeStyle = "rgba(255,255,255,0.35)"
        ctx.lineWidth = 1
        ctx.beginPath(); ctx.moveTo(root.xOf(info.now), root.chartTop); ctx.lineTo(root.xOf(info.now), root.chartTop + root.chartH); ctx.stroke()
      }
      // Best time for the next cup.
      var ideal = info.coffee && info.coffee.ideal ? info.coffee.ideal.at : null
      if (ideal && ideal < info.toMs) {
        var ix = root.xOf(ideal)
        ctx.setLineDash([2, 2])
        ctx.strokeStyle = String(root.w.green)
        ctx.lineWidth = 1.5
        ctx.beginPath(); ctx.moveTo(ix, root.chartTop); ctx.lineTo(ix, root.chartTop + root.chartH); ctx.stroke()
        ctx.setLineDash([])
      }
    }
  }
  onInfoChanged: curve.requestPaint()
  onWidthChanged: curve.requestPaint()

  // Hours along the bottom.
  Repeater {
    model: 9
    Text {
      required property int index
      x: Math.min(root.width - implicitWidth, Math.max(0, index * 3 * root.colW - implicitWidth / 2))
      y: root.chartTop + root.chartH + Style.space(2)
      textFormat: Text.PlainText
      text: root.info ? Qt.formatTime(new Date(root.info.fromMs + index * 3 * 3600000), "HH") : ""
      color: Util.alpha(root.w.fg, 0.45)
      font.family: root.w.fontFamily
      font.pixelSize: Style.font.caption - 2
    }
  }
}
