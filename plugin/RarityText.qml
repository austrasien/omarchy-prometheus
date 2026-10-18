import QtQuick

// An achievement name in its rarity's color. Legendary ones are gold and
// shine: a bright band sweeps across the letters every few seconds.
Item {
  id: root

  property string text: ""
  property color color: "white"
  property bool legendary: false
  property string fontFamily: ""
  property int pixelSize: 14
  property bool bold: true
  property int elide: Text.ElideRight
  // Set (0 to 1) to place the shine by hand, frame by frame; -1 lets it run.
  property real sweepOverride: -1

  implicitWidth: base.implicitWidth
  implicitHeight: base.implicitHeight

  Text {
    id: base
    width: root.width
    textFormat: Text.PlainText
    text: root.text
    color: root.color
    font.family: root.fontFamily
    font.pixelSize: root.pixelSize
    font.bold: root.bold
    elide: root.elide
  }

  // The shine: a clipped window over a white copy of the text, sliding by.
  Item {
    id: band
    visible: root.legendary
    width: Math.max(10, root.pixelSize * 1.6)
    height: base.height
    clip: true
    property real runX: -width
    x: root.sweepOverride >= 0 ? -width + (base.width + width) * root.sweepOverride : runX
    opacity: 0.85

    Text {
      x: -band.x
      width: base.width
      textFormat: Text.PlainText
      text: root.text
      color: "#fffbe6"
      font: base.font
      elide: base.elide
    }

    SequentialAnimation on runX {
      running: root.legendary && root.visible && root.sweepOverride < 0
      loops: Animation.Infinite
      NumberAnimation { from: -band.width; to: base.width; duration: 1400; easing.type: Easing.InOutSine }
      PauseAnimation { duration: 1600 }
    }
  }
}
