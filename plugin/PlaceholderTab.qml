import QtQuick
import qs.Commons

// A tab whose content is still to be designed.
Column {
  id: tab

  property var w: null
  property string title: ""
  property string blurb: ""

  readonly property bool editing: false
  function focusEntry() { return false }
  spacing: Style.space(8)

  Text {
    width: parent.width
    textFormat: Text.PlainText
    text: tab.title
    color: w.fg
    font.family: w.fontFamily
    font.pixelSize: Style.font.body
    font.bold: true
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: tab.blurb
    color: Util.alpha(w.fg, 0.6)
    font.family: w.fontFamily
    font.pixelSize: Style.font.caption
  }
}
