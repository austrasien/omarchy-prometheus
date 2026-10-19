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
  property color breakColor: "#2ac3de"
  property var breakAt: null           // when "Break?" is due, in the running session

  readonly property var hours: info ? info.hours : []

  // Series hidden from the legend (clicked off).
  property var hidden: ({})
  function shown(key) { return !hidden[key] }
  function toggle(key) {
    var h = Object.assign({}, hidden)
    h[key] = !h[key]
    hidden = h
    curve.requestPaint()
  }
  readonly property var series: [
    { key: "focus", label: "Session", color: w.accent },
    { key: "tokens", label: "Tokens", color: agentColor },
    { key: "caffeine", label: "Caffeine", color: coffeeColor },
    { key: "cups", label: "Cups", color: coffeeColor, glyph: "☕" },
    { key: "tasks", label: "Tasks", color: w.gold, glyph: "✓" },
    { key: "quests", label: "Quests", color: w.red, glyph: "★" },
    { key: "ideal", label: "Best time", color: w.green },
    { key: "break", label: "Break", color: breakColor }
  ]
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

  height: chartTop + chartH + Style.space(16) + legend.implicitHeight + Style.space(6)

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
        visible: modelData.cups > 0 && root.shown("cups")
        textFormat: Text.PlainText
        text: modelData.cups > 1 ? "☕" + modelData.cups : "☕"
        color: root.coffeeColor
        font.pixelSize: Style.font.caption - 2
      }
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        readonly property bool q: modelData.quests > 0 && root.shown("quests")
        readonly property bool t: modelData.tasks > 0 && root.shown("tasks")
        visible: q || t
        textFormat: Text.PlainText
        text: (q ? "★" : "") + (t ? "✓" + modelData.tasks : "")
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
        visible: root.shown("focus")
        height: parent.height * Math.min(60, modelData.focus) / 60
        radius: 1
        color: Util.alpha(root.w.accent, 0.55)
      }
      Rectangle {
        anchors.bottom: parent.bottom
        x: parent.width * 0.62
        width: Math.max(1, parent.width * 0.28)
        visible: modelData.tokens > 0 && root.shown("tokens")
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
      if (root.shown("caffeine")) {
      ctx.setLineDash([3, 3])
      ctx.strokeStyle = Qt.rgba(root.coffeeColor.r, root.coffeeColor.g, root.coffeeColor.b, 0.5)
      ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(0, root.yOfMg(info.lowMg)); ctx.lineTo(width, root.yOfMg(info.lowMg)); ctx.stroke()
      ctx.setLineDash([])
      }
      // Up to now, filled; what is to come (no other cup), dashed.
      var past = pts.filter(function(p) { return !p.future })
      var next = pts.filter(function(p) { return p.future })
      if (past.length && next.length) next.unshift(past[past.length - 1])
      if (past.length > 1 && root.shown("caffeine")) {
        ctx.beginPath()
        ctx.moveTo(root.xOf(past[0].at), root.yOfMg(0))
        for (var i = 0; i < past.length; i++) ctx.lineTo(root.xOf(past[i].at), root.yOfMg(past[i].mg))
        ctx.lineTo(root.xOf(past[past.length - 1].at), root.yOfMg(0))
        ctx.closePath()
        ctx.fillStyle = Qt.rgba(root.coffeeColor.r, root.coffeeColor.g, root.coffeeColor.b, 0.18)
        ctx.fill()
        ctx.beginPath()
        for (var j = 0; j < past.length; j++) {
          var x = root.xOf(past[j].at), y = root.yOfMg(past[j].mg)
          if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
        }
        ctx.strokeStyle = root.coffeeColor
        ctx.lineWidth = 2
        ctx.stroke()
      }
      if (next.length > 1 && root.shown("caffeine")) {
        ctx.beginPath()
        for (var k = 0; k < next.length; k++) {
          var nx = root.xOf(next[k].at), ny = root.yOfMg(next[k].mg)
          if (k === 0) ctx.moveTo(nx, ny); else ctx.lineTo(nx, ny)
        }
        ctx.setLineDash([4, 3])
        ctx.strokeStyle = Qt.rgba(root.coffeeColor.r, root.coffeeColor.g, root.coffeeColor.b, 0.7)
        ctx.lineWidth = 1.5
        ctx.stroke()
        ctx.setLineDash([])
      }
      // Now.
      if (info.now >= info.fromMs && info.now < info.toMs) {
        ctx.strokeStyle = "rgba(255,255,255,0.35)"
        ctx.lineWidth = 1
        ctx.beginPath(); ctx.moveTo(root.xOf(info.now), root.chartTop); ctx.lineTo(root.xOf(info.now), root.chartTop + root.chartH); ctx.stroke()
      }
      // When "Break?" is due.
      if (root.breakAt && root.breakAt >= info.fromMs && root.breakAt < info.toMs && root.shown("break")) {
        var bx = root.xOf(root.breakAt)
        ctx.setLineDash([2, 2])
        ctx.strokeStyle = String(root.breakColor)
        ctx.lineWidth = 1.5
        ctx.beginPath(); ctx.moveTo(bx, root.chartTop); ctx.lineTo(bx, root.chartTop + root.chartH); ctx.stroke()
        ctx.setLineDash([])
      }
      // Best time for the next cup.
      var ideal = info.coffee && info.coffee.ideal ? info.coffee.ideal.at : null
      if (ideal && ideal < info.toMs && root.shown("ideal")) {
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
  onBreakAtChanged: curve.requestPaint()
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

  // Legend: a dot per series, click to hide or show it; split into
  // centered lines that fit the width.
  FontMetrics { id: legendMetrics; font.family: root.w.fontFamily; font.pixelSize: Style.font.caption - 1 }
  function legendText(e) { return (e.glyph ? e.glyph + " " : "") + e.label }
  readonly property var legendLines: {
    var lines = [], line = [], used = 0, gap = Style.space(10)
    for (var i = 0; i < series.length; i++) {
      var wd = Style.space(13) + legendMetrics.advanceWidth(legendText(series[i]))
      var need = line.length ? used + gap + wd : wd
      if (line.length && need > width) { lines.push(line); line = []; need = wd }
      line.push(series[i])
      used = need
    }
    if (line.length) lines.push(line)
    return lines
  }

  Column {
    id: legend
    y: root.chartTop + root.chartH + Style.space(18)
    width: root.width
    spacing: Style.space(4)
    Repeater {
      model: root.legendLines
      Row {
        required property var modelData
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Style.space(10)
        Repeater {
          model: modelData
          Item {
            id: item
            required property var modelData
            readonly property bool on: root.shown(modelData.key)
            width: entry.implicitWidth
            height: entry.implicitHeight
            opacity: on ? 1 : 0.4
            Row {
              id: entry
              spacing: Style.space(4)
              Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(9)
                height: width
                radius: width / 2
                color: item.on ? item.modelData.color : "transparent"
                border.width: 1.5
                border.color: item.modelData.color
              }
              Text {
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: root.legendText(item.modelData)
                color: Util.alpha(root.w.fg, 0.8)
                font.family: root.w.fontFamily
                font.pixelSize: Style.font.caption - 1
                font.strikeout: !item.on
              }
            }
            MouseArea {
              anchors.fill: parent
              anchors.margins: -Style.space(3)
              cursorShape: Qt.PointingHandCursor
              onClicked: root.toggle(item.modelData.key)
            }
          }
        }
      }
    }
  }
}
