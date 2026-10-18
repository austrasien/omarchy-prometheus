import QtQuick
import QtQuick.Shapes

// A number inside a laurel wreath: two branches curving up around it, open
// at the top. Each branch is a thin stem with leaves set along it, tilted
// outward. Drawn in QML so it follows the theme color and scales with `size`.
Item {
  id: root

  property string text: ""
  property color color: "white"
  property string fontFamily: ""
  property real size: 24          // height of the wreath, in pixels

  implicitWidth: size * 1.2
  implicitHeight: size

  readonly property int leavesPerSide: 6
  readonly property real cx: width / 2
  readonly property real cy: height * 0.5
  readonly property real rx: size * 0.47
  readonly property real ry: size * 0.44
  // Angles in degrees, 0° to the right, y growing down: 90° is the bottom.
  readonly property real fromDeg: 100     // stems start just off the bottom
  readonly property real spanDeg: 135     // and curve up to about 10 o'clock

  function px(deg) { return cx + Math.cos(deg * Math.PI / 180) * rx }
  function py(deg) { return cy + Math.sin(deg * Math.PI / 180) * ry }

  // Stems.
  Shape {
    anchors.fill: parent
    preferredRendererType: Shape.CurveRenderer

    ShapePath {
      strokeColor: root.color
      strokeWidth: Math.max(1, root.size * 0.045)
      fillColor: "transparent"
      capStyle: ShapePath.RoundCap
      PathAngleArc {
        centerX: root.cx; centerY: root.cy
        radiusX: root.rx; radiusY: root.ry
        startAngle: root.fromDeg; sweepAngle: root.spanDeg
      }
    }

    ShapePath {
      strokeColor: root.color
      strokeWidth: Math.max(1, root.size * 0.045)
      fillColor: "transparent"
      capStyle: ShapePath.RoundCap
      PathAngleArc {
        centerX: root.cx; centerY: root.cy
        radiusX: root.rx; radiusY: root.ry
        startAngle: 180 - root.fromDeg; sweepAngle: -root.spanDeg
      }
    }
  }

  // Leaves: on each branch, from the bottom up, getting a little smaller.
  Repeater {
    model: root.leavesPerSide * 2

    Rectangle {
      required property int index
      readonly property bool isLeft: index < root.leavesPerSide
      readonly property real t: (index % root.leavesPerSide + 0.5) / root.leavesPerSide
      readonly property real deg: isLeft ? root.fromDeg + t * root.spanDeg : 180 - (root.fromDeg + t * root.spanDeg)
      width: root.size * 0.11
      height: root.size * 0.24 * (1.05 - 0.3 * t)
      radius: width / 2
      color: root.color
      // Leaves sit just outside the stem and lean along it, tips outward.
      x: root.cx + Math.cos(deg * Math.PI / 180) * (root.rx + root.size * 0.06) - width / 2
      y: root.cy + Math.sin(deg * Math.PI / 180) * (root.ry + root.size * 0.06) - height / 2
      rotation: deg + 90 + (isLeft ? 40 : -40)
    }
  }

  Text {
    anchors.centerIn: parent
    textFormat: Text.PlainText
    text: root.text
    color: root.color
    font.family: root.fontFamily
    font.pixelSize: Math.round(root.size * (root.text.length > 2 ? 0.32 : 0.42))
    font.bold: true
  }
}
