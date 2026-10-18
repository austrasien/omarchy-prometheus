import QtQuick
import QtQuick.Effects

// A season medal: one or two holographic bars. Won, it shines in its colors.
// Still to win, it sits grey and dull; under the mouse it wakes up: the colors
// flood back in, it grows with a bounce, a halo of its own color breathes
// around it, sparks burst out and the foil starts shining. Enough to want it.
Item {
  id: root

  property int bars: 1
  property var colors: null        // { bg, dot, edge }
  property bool won: false
  property real size: 1.2

  readonly property bool lit: won || hover.hovered
  readonly property color bg: colors ? colors.bg : "#666"
  readonly property color dotColor: colors ? colors.dot : "#ccc"
  readonly property color edgeColor: colors ? colors.edge : "#999"

  implicitWidth: bars_.implicitWidth
  implicitHeight: bars_.implicitHeight

  HoverHandler { id: hover; enabled: !root.won }

  // The effect's knobs, animated here and read by the layer effect below.
  property real fxSaturation: lit ? 0 : -1
  property real fxBrightness: lit ? (won ? 0 : 0.12) : -0.25
  property real fxGlow: 0
  property real fxGlowScale: 1.15
  Behavior on fxSaturation { NumberAnimation { duration: 450; easing.type: Easing.OutCubic } }
  Behavior on fxBrightness { NumberAnimation { duration: 450; easing.type: Easing.OutCubic } }

  Row {
    id: bars_
    anchors.centerIn: parent
    spacing: 1
    transformOrigin: Item.Center
    opacity: root.lit ? 1 : 0.55
    Behavior on opacity { NumberAnimation { duration: 300 } }
    Repeater {
      model: root.bars
      HoloRibbon {
        size: root.size
        color: root.bg
        dot: root.dotColor
        edge: root.edgeColor
        shining: root.lit
      }
    }
    layer.enabled: true
    layer.effect: MultiEffect {
      autoPaddingEnabled: true
      saturation: root.fxSaturation
      brightness: root.fxBrightness
      shadowEnabled: true
      shadowColor: Qt.lighter(root.bg, 1.8)
      shadowBlur: 1.0
      shadowOpacity: root.fxGlow
      shadowScale: root.fxGlowScale
      shadowHorizontalOffset: 0
      shadowVerticalOffset: 0
    }
  }

  // Waking up: a bounce, a little wiggle, then the halo breathes.
  states: State {
    name: "tempted"
    when: hover.hovered && !root.won
  }
  transitions: [
    Transition {
      to: "tempted"
      SequentialAnimation {
        ScriptAction { script: burst.start() }
        ParallelAnimation {
          NumberAnimation { target: bars_; property: "scale"; to: 1.55; duration: 520; easing.type: Easing.OutElastic; easing.amplitude: 1.2; easing.period: 0.45 }
          SequentialAnimation {
            NumberAnimation { target: bars_; property: "rotation"; to: -7; duration: 80 }
            NumberAnimation { target: bars_; property: "rotation"; to: 6; duration: 110 }
            NumberAnimation { target: bars_; property: "rotation"; to: -3; duration: 110 }
            NumberAnimation { target: bars_; property: "rotation"; to: 0; duration: 120 }
          }
          NumberAnimation { target: root; property: "fxGlow"; to: 1; duration: 400 }
        }
      }
    },
    Transition {
      from: "tempted"
      ParallelAnimation {
        NumberAnimation { target: bars_; property: "scale"; to: 1; duration: 260; easing.type: Easing.OutCubic }
        NumberAnimation { target: bars_; property: "rotation"; to: 0; duration: 200 }
        NumberAnimation { target: root; property: "fxGlow"; to: 0; duration: 260 }
      }
    }
  ]

  SequentialAnimation {
    running: hover.hovered && !root.won
    loops: Animation.Infinite
    NumberAnimation { target: root; property: "fxGlowScale"; to: 1.45; duration: 700; easing.type: Easing.InOutSine }
    NumberAnimation { target: root; property: "fxGlowScale"; to: 1.15; duration: 700; easing.type: Easing.InOutSine }
  }

  // Sparks: eight little stars thrown out from the medal.
  Item {
    id: burst
    anchors.centerIn: parent
    width: 0
    height: 0
    z: 3
    function start() { for (var i = 0; i < sparks.count; i++) sparks.itemAt(i).fly() }

    Repeater {
      id: sparks
      model: 8
      Text {
        id: spark
        required property int index
        readonly property real angle: index * Math.PI / 4 + 0.3
        readonly property real reach: root.implicitWidth * 0.9 + 10
        text: index % 2 ? "✦" : "✧"
        color: index % 3 === 0 ? "white" : Qt.lighter(root.dotColor, 1.2)
        font.pixelSize: 9
        x: -width / 2
        y: -height / 2
        opacity: 0
        function fly() { anim.restart() }
        ParallelAnimation {
          id: anim
          NumberAnimation { target: spark; property: "x"; from: -spark.width / 2; to: Math.cos(spark.angle) * spark.reach - spark.width / 2; duration: 650; easing.type: Easing.OutCubic }
          NumberAnimation { target: spark; property: "y"; from: -spark.height / 2; to: Math.sin(spark.angle) * spark.reach * 0.6 - spark.height / 2; duration: 650; easing.type: Easing.OutCubic }
          SequentialAnimation {
            NumberAnimation { target: spark; property: "opacity"; from: 0; to: 1; duration: 120 }
            NumberAnimation { target: spark; property: "opacity"; to: 0; duration: 530; easing.type: Easing.InQuad }
          }
          NumberAnimation { target: spark; property: "rotation"; from: 0; to: 180; duration: 650 }
        }
      }
    }
  }
}
