import QtQuick
import qs.Commons

// An unlocked achievement as a capsule, like the one the bar shows when it
// unlocks: the rarity's color, a trophy, the name and its XP; a light sweeps
// across it now and then, and a legendary one has a rainbow sheen.
Item {
  id: cap

  property var w: null
  property var tier: null            // a tier from achievements:list
  property bool selected: false
  property bool dimmed: false          // another one is selected
  signal picked()

  // The selected one stands out: bigger, a white ring, a caret pointing at
  // its legend below; the others step back.
  scale: selected ? 1.1 : 1
  opacity: dimmed ? 0.4 : 1
  z: selected ? 1 : 0
  Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutBack } }
  Behavior on opacity { NumberAnimation { duration: 160 } }

  readonly property string rarity: tier ? tier.rarity || "normal" : "normal"
  readonly property color tint: rarity === "normal" ? w.gold : w.rarityColor(rarity)
  readonly property string trophyGlyph: String.fromCodePoint(0xF0538)

  implicitWidth: label.implicitWidth + Style.space(20)
  implicitHeight: label.implicitHeight + Style.space(8)

  Rectangle {
    anchors.centerIn: parent
    width: parent.width + Style.space(4)
    height: parent.height + Style.space(4)
    radius: height / 2
    color: "transparent"
    border.width: cap.selected ? 2.5 : 1.5
    border.color: cap.selected ? "white" : cap.tint
    visible: cap.selected || area.containsMouse
  }

  Canvas {
    visible: cap.selected
    width: 10
    height: 6
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.top: parent.bottom
    anchors.topMargin: 4
    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      ctx.fillStyle = "white"
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(width, 0); ctx.lineTo(width / 2, height); ctx.closePath(); ctx.fill()
    }
  }

  Rectangle {
    id: body
    anchors.fill: parent
    radius: height / 2
    clip: true
    color: cap.tint
    border.width: 1
    border.color: Qt.lighter(cap.tint, 1.4)

    Rectangle {
      visible: cap.rarity === "legendary"
      width: body.width * 3
      height: body.height
      opacity: 0.28
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
      NumberAnimation on x {
        running: cap.visible && cap.rarity === "legendary"
        loops: Animation.Infinite
        from: -body.width * 2; to: 0; duration: 2600
      }
    }

    // The shine, slower than in the bar: these sit there a while.
    Rectangle {
      width: Math.max(12, body.height * 1.2)
      height: body.height * 3
      anchors.verticalCenter: parent.verticalCenter
      rotation: 25
      opacity: cap.rarity === "normal" ? 0.5 : 0.8
      gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0.0; color: "#00ffffff" }
        GradientStop { position: 0.5; color: "#c0ffffff" }
        GradientStop { position: 1.0; color: "#00ffffff" }
      }
      SequentialAnimation on x {
        running: cap.visible
        loops: Animation.Infinite
        PauseAnimation { duration: (cap.tier ? (cap.tier.unlockedAt % 7) : 0) * 450 }
        NumberAnimation { from: -body.height * 2; to: body.width + body.height; duration: 1100; easing.type: Easing.InOutQuad }
        PauseAnimation { duration: 3200 }
      }
    }
  }

  Text {
    id: label
    anchors.centerIn: parent
    textFormat: Text.PlainText
    text: cap.tier ? cap.trophyGlyph + " " + cap.tier.name + "  +" + cap.tier.xp : ""
    color: "#14151f"
    font.family: cap.w.fontFamily
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  MouseArea {
    id: area
    anchors.fill: parent
    anchors.margins: -Style.space(2)
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: cap.picked()
  }
}
