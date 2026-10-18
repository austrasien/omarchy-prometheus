import QtQuick

// A season ribbon: a plain ribbon under a holographic foil, like a rare
// trading card. A rainbow sheen drifts across it, fine diagonal lines catch
// the light, and a bright band sweeps over it every few seconds.
Item {
  id: root

  property color color: "#555"
  property color dot: "white"
  property color edge: "#999"
  property real size: 1
  property bool shining: true

  implicitWidth: ribbon.implicitWidth
  implicitHeight: ribbon.implicitHeight

  Ribbon {
    id: ribbon
    anchors.fill: parent
    size: root.size
    color: root.color
    dot: root.dot
    edgeColor: root.edge
    dots: 1
    edges: "both"
  }

  Item {
    id: foil
    anchors.fill: parent
    anchors.margins: 1
    clip: true

    property real phase: 0
    NumberAnimation on phase {
      running: root.shining && root.visible
      from: 0; to: 1; duration: 3200; loops: Animation.Infinite
    }

    // Rainbow sheen, three widths long, drifting left to right.
    Rectangle {
      width: foil.width * 3
      height: foil.height
      x: -foil.width * 2 * (1 - foil.phase)
      opacity: 0.32
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0.00; color: "#ff4d4d" }
        GradientStop { position: 0.17; color: "#ffd24d" }
        GradientStop { position: 0.33; color: "#6dff6d" }
        GradientStop { position: 0.50; color: "#4de1ff" }
        GradientStop { position: 0.67; color: "#6d6dff" }
        GradientStop { position: 0.83; color: "#ff6dff" }
        GradientStop { position: 1.00; color: "#ff4d4d" }
      }
    }

    // Fine diagonal lines.
    Item {
      width: foil.width * 2
      height: foil.width * 2
      anchors.centerIn: parent
      rotation: -35
      Repeater {
        model: 14
        Rectangle {
          required property int index
          x: index * parent.width / 14
          width: 1
          height: parent.height
          color: "white"
          opacity: 0.16
        }
      }
    }

    // The bright band: a diagonal flash crossing once per cycle.
    Rectangle {
      width: Math.max(4, foil.width * 0.22)
      height: foil.width * 2
      anchors.verticalCenter: parent.verticalCenter
      x: -width + (foil.width + 2 * width) * foil.phase
      rotation: -35
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0.0; color: "#00ffffff" }
        GradientStop { position: 0.5; color: "#ccffffff" }
        GradientStop { position: 1.0; color: "#00ffffff" }
      }
    }
  }
}
