import QtQuick

// A season ribbon: a ribbon with a star, edge bars for the goals reached, under
// a holographic foil, like a rare trading card. A rainbow sheen drifts across it, fine diagonal lines catch
// the light, and a bright band sweeps over it every few seconds.
Item {
  id: root

  property color color: "#555"
  property color dot: "white"
  property color edge: "#999"
  property real size: 1
  property string edges: "both"    // left: season goal, both: hard goal
  property bool shining: true
  // Set (0 to 1) to hold the foil at a given point of its cycle, frame by
  // frame (the animated share card); -1 lets it run.
  property real phaseOverride: -1

  implicitWidth: ribbon.implicitWidth
  implicitHeight: ribbon.implicitHeight

  Ribbon {
    id: ribbon
    anchors.fill: parent
    size: root.size
    color: root.color
    dot: root.dot
    edgeColor: root.edge
    star: true
    edges: root.edges
  }

  Item {
    id: foil
    anchors.fill: parent
    anchors.margins: 1
    clip: true

    property real runningPhase: 0
    readonly property real phase: root.phaseOverride >= 0 ? root.phaseOverride : runningPhase
    NumberAnimation on runningPhase {
      running: root.shining && root.visible && root.phaseOverride < 0
      from: 0; to: 1; duration: 3200; loops: Animation.Infinite
    }

    // Rainbow sheen, three widths long, drifting left to right.
    Rectangle {
      width: foil.width * 3
      height: foil.height
      x: -foil.width * 2 * (1 - foil.phase)
      opacity: 0.13
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
          opacity: 0.06
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
        GradientStop { position: 0.5; color: "#66ffffff" }
        GradientStop { position: 1.0; color: "#00ffffff" }
      }
    }
  }
}
