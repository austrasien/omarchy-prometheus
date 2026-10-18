import QtQuick
import qs.Commons

// A label on the left, its value on the right.
Item {
  id: row

  property var w: null
  property string label: ""
  property string value: ""
  property bool strong: false

  width: parent ? parent.width : 0
  height: labelText.implicitHeight

  Text {
    id: labelText
    anchors.left: parent.left
    textFormat: Text.PlainText
    text: row.label
    color: Util.alpha(row.w.fg, 0.65)
    font.family: row.w.fontFamily
    font.pixelSize: Style.font.body
  }

  Text {
    anchors.right: parent.right
    textFormat: Text.PlainText
    text: row.value
    color: row.w.fg
    font.family: row.w.fontFamily
    font.pixelSize: Style.font.body
    font.bold: row.strong
  }
}
