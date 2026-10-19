import QtQuick
import qs.Commons

// The league path: the league after each settled round, as a staircase
// from the first round on, each step in its league's color; a gridline per
// league with its name on the left.
Item {
  id: path

  property var w: null
  property var history: []        // leagues:get history
  property var leagues: []        // leagues:get leagues (name, color)
  property int current: 0

  readonly property var levels: {
    if (history.length === 0) return []
    var out = [history[0].before]
    for (var i = 0; i < history.length; i++) out.push(history[i].after)
    return out
  }
  readonly property int lo: levels.length ? Math.max(0, Math.min.apply(null, levels) - 1) : 0
  readonly property int hi: levels.length ? Math.min(leagues.length - 1, Math.max.apply(null, levels) + 1) : 0
  readonly property real labelWidth: Style.space(58)
  readonly property real rowH: (height - Style.space(6)) / Math.max(1, hi - lo)

  height: Style.space(16) * Math.max(2, hi - lo) + Style.space(6)

  function yOf(l) { return Style.space(3) + (hi - l) * rowH }

  Repeater {
    model: path.hi - path.lo + 1
    Item {
      required property int index
      readonly property int league: path.hi - index
      y: path.yOf(league)
      width: path.width
      Rectangle { x: path.labelWidth; width: path.width - path.labelWidth; height: 1; color: Util.alpha(path.w.fg, 0.07) }
      Text {
        anchors.verticalCenter: parent.top
        width: path.labelWidth - Style.space(6)
        horizontalAlignment: Text.AlignRight
        textFormat: Text.PlainText
        text: path.leagues[league] ? path.leagues[league].name : ""
        color: path.leagues[league] ? path.leagues[league].color : path.w.fg
        opacity: parent.league === path.current ? 1 : 0.6
        font.family: path.w.fontFamily
        font.pixelSize: Style.font.caption - 1
        font.bold: parent.league === path.current
      }
    }
  }

  Canvas {
    id: canvas
    x: path.labelWidth
    width: path.width - path.labelWidth
    height: path.height
    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      var lv = path.levels, n = lv.length
      if (n === 0) return
      var step = width / Math.max(1, n)
      ctx.lineWidth = 2.5
      for (var i = 0; i < n; i++) {
        var y = path.yOf(lv[i]), x0 = i * step, x1 = (i + 1) * step
        ctx.strokeStyle = path.leagues[lv[i]] ? path.leagues[lv[i]].color : "white"
        ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke()
        if (i + 1 < n && lv[i + 1] !== lv[i]) {
          ctx.strokeStyle = lv[i + 1] > lv[i] ? "#9ece6a" : "#f7768e"
          ctx.lineWidth = 1.5
          ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x1, path.yOf(lv[i + 1])); ctx.stroke()
          ctx.lineWidth = 2.5
        }
      }
    }
  }
  onLevelsChanged: canvas.requestPaint()
  onWidthChanged: canvas.requestPaint()
  onHeightChanged: canvas.requestPaint()
}
