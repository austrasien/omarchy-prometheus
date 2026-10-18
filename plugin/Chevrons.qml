import QtQuick

// Three chevrons streaming up (promotion) or down (relegation), on a loop:
// each rises or falls through the box, fading in then out, one after the other.
Item {
  id: root

  property bool up: true
  property color color: "#9ece6a"
  property real glyphSize: 12
  property bool running: visible

  implicitWidth: glyphSize * 1.4
  implicitHeight: glyphSize * 2.4
  clip: true

  Repeater {
    model: 3
    Text {
      id: chev
      required property int index
      anchors.horizontalCenter: parent.horizontalCenter
      text: root.up ? "" : ""        // chevron up, chevron down
      color: root.color
      font.pixelSize: root.glyphSize
      font.bold: true
      readonly property real startY: root.up ? root.height : -height
      readonly property real endY: root.up ? -height : root.height
      y: startY
      opacity: 0

      SequentialAnimation {
        running: root.running
        loops: Animation.Infinite
        PauseAnimation { duration: chev.index * 300 }
        ParallelAnimation {
          NumberAnimation { target: chev; property: "y"; from: chev.startY; to: chev.endY; duration: 900; easing.type: Easing.InOutQuad }
          SequentialAnimation {
            NumberAnimation { target: chev; property: "opacity"; from: 0; to: 1; duration: 250 }
            PauseAnimation { duration: 350 }
            NumberAnimation { target: chev; property: "opacity"; to: 0; duration: 300 }
          }
        }
        PauseAnimation { duration: (2 - chev.index) * 300 }
      }
    }
  }
}
