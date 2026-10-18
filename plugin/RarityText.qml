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
    x: -width
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

    SequentialAnimation on x {
      running: root.legendary && root.visible
      loops: Animation.Infinite
      NumberAnimation { from: -band.width; to: base.width; duration: 1400; easing.type: Easing.InOutSine }
      PauseAnimation { duration: 1600 }
    }
  }
}
