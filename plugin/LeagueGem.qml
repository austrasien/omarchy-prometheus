import QtQuick

// A league's insignia: Bronze a circle, Silver a triangle, Gold a square,
// then one side more each league up (Sapphire a pentagon, Ruby a hexagon,
// ... Diamond eleven sides). `glint` (0 to 1) places a band of light across
// it, cut to its shape; -1 for none. Drawn on a canvas so the light follows
// the outline exactly.
Canvas {
  id: gem

  property int league: 0
  property color color: "#cd7f32"
  property bool ringed: false        // a white outline: the current league
  property real fill: 1              // opacity of the body (dim for leagues not reached)
  property real glint: -1

  readonly property int sides: league === 0 ? 0 : league + 2

  onLeagueChanged: requestPaint()
  onColorChanged: requestPaint()
  onRingedChanged: requestPaint()
  onFillChanged: requestPaint()
  onGlintChanged: requestPaint()
  onWidthChanged: requestPaint()

  function outline(ctx, r, cx, cy) {
    ctx.beginPath()
    if (sides === 0) {
      ctx.arc(cx, cy, r, 0, 2 * Math.PI)
    } else {
      for (var i = 0; i < sides; i++) {
        // A point on top for odd shapes, a flat edge for even ones (a square
        // stands as a square, not a diamond).
        var a = -Math.PI / 2 + (sides % 2 === 0 ? Math.PI / sides : 0) + i * 2 * Math.PI / sides
        var x = cx + r * Math.cos(a), y = cy + r * Math.sin(a)
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
      }
      ctx.closePath()
    }
  }

  onPaint: {
    var ctx = getContext("2d")
    ctx.reset()
    var cx = width / 2, cy = height / 2
    // Polygons with few sides look smaller than a circle of the same radius.
    var r = (Math.min(width, height) / 2 - 1.5) * (sides === 3 ? 1.08 : 1)
    if (sides === 3) cy += r * 0.12
    ctx.save()
    ctx.globalAlpha = fill
    outline(ctx, r, cx, cy)
    ctx.fillStyle = color
    ctx.fill()
    ctx.restore()
    if (glint >= 0) {
      ctx.save()
      outline(ctx, r, cx, cy)
      ctx.clip()
      var span = width * 2
      var x0 = -width + span * glint
      var g = ctx.createLinearGradient(x0, 0, x0 + width * 0.7, height * 0.7)
      g.addColorStop(0, "rgba(255,255,255,0)")
      g.addColorStop(0.5, "rgba(255,255,255,0.95)")
      g.addColorStop(1, "rgba(255,255,255,0)")
      ctx.fillStyle = g
      ctx.fillRect(0, 0, width, height)
      ctx.restore()
    }
    if (ringed) {
      outline(ctx, r, cx, cy)
      ctx.lineWidth = 2
      ctx.strokeStyle = "white"
      ctx.stroke()
    }
  }
}
