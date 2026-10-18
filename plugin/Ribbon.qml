import QtQuick

// A military ribbon bar: a small rectangle with a background color, one to
// three dots in the middle, and a stripe on the left edge or on both edges.
Item {
  id: root

  property color color: "#3b5bdb"
  property color dot: "white"
  property int dots: 1             // 1 daily, 2 weekly, 3 monthly
  property string edges: "none"    // none, left, both
  property real size: 1            // scale: 1 is 30 x 10 px

  implicitWidth: Math.round(30 * size)
  implicitHeight: Math.round(10 * size)

  Rectangle {
    anchors.fill: parent
    radius: Math.max(1, root.height * 0.12)
    color: root.color
    border.width: 1
    border.color: Qt.darker(root.color, 1.6)
    clip: true

    // Edge stripes, in the dot color.
    Rectangle {
      visible: root.edges === "left" || root.edges === "both"
      anchors.left: parent.left
      anchors.leftMargin: Math.round(root.width * 0.12)
      anchors.top: parent.top
      anchors.bottom: parent.bottom
      width: Math.max(2, Math.round(root.width * 0.08))
      color: root.dot
    }

    Rectangle {
      visible: root.edges === "both"
      anchors.right: parent.right
      anchors.rightMargin: Math.round(root.width * 0.12)
      anchors.top: parent.top
      anchors.bottom: parent.bottom
      width: Math.max(2, Math.round(root.width * 0.08))
      color: root.dot
    }

    Row {
      anchors.centerIn: parent
      spacing: Math.max(1, Math.round(root.height * 0.18))

      Repeater {
        model: Math.max(1, Math.min(3, root.dots))

        Rectangle {
          width: Math.max(3, Math.round(root.height * 0.42))
          height: width
          radius: width / 2
          color: root.dot
          border.width: 1
          border.color: Qt.darker(root.dot, 1.4)
        }
      }
    }
  }
}
