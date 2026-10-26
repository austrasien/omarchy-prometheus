import QtQuick
import qs.Commons

// A text running once around the disc's inner edge, as in the minimap's
// notifications map: it fades in at noon, goes clockwise through 3, 6 and
// 9 (upright at 6, like a news ticker) and fades out back at noon.
Item {
  id: ring

  property string text: ""
  property color color: Color.foreground
  property int pixelSize: 13
  property real speed: 60          // degrees per second
  property real inset: 12          // from the edge to the letters' middle

  readonly property real radius: width / 2 - inset
  readonly property var chars: Array.from(text)
  readonly property real step: cell.advanceWidth / Math.max(1, radius) * 180 / Math.PI
  readonly property real lap: 360 + chars.length * step
  // How long one pass takes, for the notification's length.
  readonly property int runMs: Math.round(lap / speed * 1000)
  property real offset: 0

  function start() { run.stop(); offset = 0; run.start() }
  function stop() { run.stop(); offset = 0 }

  TextMetrics {
    id: cell
    font.family: Style.fontFamily
    font.pixelSize: ring.pixelSize
    font.bold: true
    text: "M"
  }

  NumberAnimation {
    id: run
    target: ring
    property: "offset"
    from: 0
    to: ring.lap
    duration: ring.runMs
  }

  Repeater {
    model: ring.chars.length
    delegate: Text {
      required property int index
      // Feet outwards: the first letter leads, read upright at 6 o'clock.
      readonly property real a: ring.offset - index * ring.step
      readonly property real rad: a * Math.PI / 180
      visible: a > 0 && a < 360
      opacity: Math.min(1, a / 30, (360 - a) / 30)
      x: ring.width / 2 + ring.radius * Math.sin(rad) - width / 2
      y: ring.height / 2 - ring.radius * Math.cos(rad) - height / 2
      rotation: a + 180
      text: ring.chars[index] || ""
      color: ring.color
      font: cell.font
    }
  }
}
