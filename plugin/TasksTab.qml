import QtQuick
import qs.Commons
import qs.Ui

// Tasks tab: Prometheus' own list, kept by prometheusd. Greyed out until a
// session is started; during a session (running or paused), clicking a task
// marks it done. Today's Obsidian todos are only offered as suggestions
// while the add field has focus: one way, nothing is written to the note.
Column {
  id: tab

  property var w: null
  property var p: null
  property var o: null   // Journal, read only

  property var tasks: []      // [{ id, text, source, createdAt }]
  property var done: []       // done today, latest first: [{ id, text, doneAt }]
  property int doneToday: 0
  property bool showDone: false   // done tasks shown at the head of the list
  property int selIndex: -1

  readonly property bool active: !!p && p.session !== null
  readonly property bool editing: addField.activeFocus
  spacing: Style.space(10)

  readonly property string uncheckedGlyph: String.fromCodePoint(0xF0131)
  readonly property string checkedGlyph: String.fromCodePoint(0xF0132)
  readonly property string closeGlyph: String.fromCodePoint(0xF0156)

  // Journal todos not already in the list, matching what is typed.
  readonly property var suggestions: {
    if (!o || !addField.activeFocus) return []
    var have = {}
    for (var i = 0; i < tasks.length; i++) have[tasks[i].text] = true
    var q = addField.text.trim().toLowerCase()
    return o.open.filter(function(t) {
      return !have[t.text] && (q === "" || t.text.toLowerCase().indexOf(q) >= 0)
    }).slice(0, 8)
  }
  onSuggestionsChanged: if (selIndex >= suggestions.length) selIndex = suggestions.length - 1

  function refresh() {
    if (!p || !p.live) return
    p.call("tasks:list", [], function(ok, d) {
      if (!ok || !d || !d.success) return
      tab.tasks = d.tasks || []
      tab.done = d.done || []
      tab.doneToday = d.doneToday || 0
      if (tab.doneToday === 0) tab.showDone = false
    })
  }

  function add(text, source) {
    var t = (text || "").trim()
    if (!active || t.length === 0) return
    p.act("tasks:add", [t, source || "manual"], "Ajout", function() {
      addField.text = ""
      tab.selIndex = -1
      tab.refresh()
    })
  }

  function addChosen() {
    if (selIndex >= 0 && selIndex < suggestions.length) add(suggestions[selIndex].text, "obsidian")
    else add(addField.text, "manual")
  }

  function complete(task) {
    if (!active) return
    p.act("tasks:complete", [task.id], "Tâche", tab.refresh)
  }

  // Deleting drops a task without checking it, so without its XP.
  function remove(task) {
    if (!active) return
    p.act("tasks:delete", [task.id], "Suppression", tab.refresh)
  }

  // Re-checking a done task puts it back in the to-do list.
  function reopen(task) {
    if (!active) return
    p.act("tasks:reopen", [task.id], "Tâche", tab.refresh)
  }

  // Done tasks first when unfolded, then the open ones.
  readonly property var rows: (showDone ? done.map(function(t) { return { task: t, isDone: true } }) : [])
    .concat(tasks.map(function(t) { return { task: t, isDone: false } }))

  function focusEntry() {
    if (!active) return false
    addField.forceActiveFocus()
    return true
  }

  onVisibleChanged: if (visible) refresh()
  Component.onCompleted: if (visible) refresh()

  Text {
    width: parent.width
    visible: !tab.active
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "Lance une session pour gérer tes tâches."
    color: Util.alpha(w.fg, 0.75)
    font.family: w.fontFamily
    font.pixelSize: Style.font.body
  }

  // Everything below is dimmed and inert without a session.
  Column {
    width: parent.width
    spacing: Style.space(10)
    enabled: tab.active
    opacity: tab.active ? 1 : 0.4

    // ---- add
    Row {
      width: parent.width
      spacing: Style.space(6)

      TextField {
        id: addField
        width: parent.width - addButton.width - parent.spacing
        placeholderText: "Nouvelle tâche"
        foreground: w.fg
        accent: w.accent
        font.family: w.fontFamily
        onActiveFocusChanged: if (activeFocus && tab.o) tab.o.refresh()
        onTextChanged: tab.selIndex = -1
        onAccepted: tab.addChosen()
        Keys.onDownPressed: if (tab.suggestions.length > 0) tab.selIndex = Math.min(tab.suggestions.length - 1, tab.selIndex + 1)
        Keys.onUpPressed: tab.selIndex = Math.max(-1, tab.selIndex - 1)
        Keys.onEscapePressed: {
          if (tab.selIndex >= 0) tab.selIndex = -1
          else w.close()
        }
      }

      Button {
        id: addButton
        anchors.verticalCenter: addField.verticalCenter
        text: "Ajouter"
        foreground: w.fg
        accent: w.accent
        bordered: true
        onClicked: tab.addChosen()
      }
    }

    // ---- journal suggestions, shown only while typing a task
    Column {
      width: parent.width
      spacing: Style.space(2)
      visible: tab.suggestions.length > 0

      Text {
        textFormat: Text.PlainText
        text: "DEPUIS LE JOURNAL  ·  ↑↓ puis Entrée"
        color: Util.alpha(w.fg, 0.45)
        font.family: w.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      Repeater {
        model: tab.suggestions

        Rectangle {
          id: sugg
          required property var modelData
          required property int index
          readonly property bool selected: index === tab.selIndex
          width: parent.width
          height: suggText.implicitHeight + Style.space(8)
          radius: Style.space(4)
          color: selected ? Util.alpha(w.accent, 0.18) : (suggArea.containsMouse ? Util.alpha(w.fg, 0.06) : "transparent")

          Text {
            id: suggIcon
            anchors.left: parent.left
            anchors.leftMargin: Style.space(6)
            anchors.top: suggText.top
            textFormat: Text.PlainText
            text: tab.uncheckedGlyph
            color: Util.alpha(w.fg, 0.45)
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            id: suggText
            anchors.left: suggIcon.right
            anchors.leftMargin: Style.space(8)
            anchors.right: parent.right
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: sugg.modelData.text
            color: sugg.selected ? w.accent : Util.alpha(w.fg, 0.8)
            font.family: w.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.Wrap
          }

          MouseArea {
            id: suggArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: tab.add(sugg.modelData.text, "obsidian")
          }
        }
      }
    }

    Item {
      width: parent.width
      height: todoHeader.implicitHeight

      PanelSectionHeader {
        id: todoHeader
        anchors.left: parent.left
        text: "À FAIRE"
        foreground: w.fg
        fontFamily: w.fontFamily
      }

      Text {
        id: doneToggle
        anchors.right: parent.right
        anchors.verticalCenter: todoHeader.verticalCenter
        visible: tab.doneToday > 0
        textFormat: Text.PlainText
        text: (tab.showDone ? "masquer " : "") + tab.doneToday + " faite" + (tab.doneToday > 1 ? "s" : "") + " aujourd'hui"
        color: Util.alpha(w.fg, 0.55)
        font.family: w.fontFamily
        font.pixelSize: Style.font.caption

        MouseArea {
          id: doneArea
          anchors.fill: parent
          anchors.margins: -Style.space(4)
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: tab.showDone = !tab.showDone
        }
      }
    }

    Text {
      visible: tab.tasks.length === 0 && !tab.showDone
      textFormat: Text.PlainText
      text: "Rien en attente."
      color: Util.alpha(w.fg, 0.45)
      font.family: w.fontFamily
      font.pixelSize: Style.font.body
    }

    Flickable {
      width: parent.width
      height: Math.min(list.implicitHeight, Style.space(340))
      contentWidth: width
      contentHeight: list.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      interactive: contentHeight > height

      Column {
        id: list
        width: parent.width
        spacing: Style.space(4)

        Repeater {
          model: tab.rows

          Item {
            id: row
            required property var modelData
            readonly property var task: modelData.task
            readonly property bool isDone: modelData.isDone
            width: list.width
            height: Math.max(rowText.implicitHeight, Style.space(24)) + Style.space(6)

            Rectangle {
              anchors.fill: parent
              radius: Style.space(4)
              color: rowArea.containsMouse ? Util.alpha(w.accent, 0.12) : "transparent"
            }

            Text {
              id: check
              anchors.left: parent.left
              anchors.leftMargin: Style.space(4)
              anchors.top: rowText.top
              textFormat: Text.PlainText
              text: row.isDone ? tab.checkedGlyph : tab.uncheckedGlyph
              color: rowArea.containsMouse || row.isDone ? w.accent : Util.alpha(w.fg, 0.6)
              font.family: w.fontFamily
              font.pixelSize: Style.font.body
            }

            Text {
              id: rowText
              anchors.left: check.right
              anchors.leftMargin: Style.space(8)
              anchors.right: deleteGlyph.left
              anchors.rightMargin: Style.space(6)
              anchors.top: parent.top
              anchors.topMargin: Style.space(3)
              textFormat: Text.PlainText
              text: row.task.text
              color: row.isDone ? Util.alpha(w.fg, 0.45) : w.fg
              font.family: w.fontFamily
              font.pixelSize: Style.font.body
              font.strikeout: row.isDone
              wrapMode: Text.Wrap
            }

            // On hover, a cross to delete the task (open ones only).
            Text {
              id: deleteGlyph
              anchors.right: laurel.left
              anchors.rightMargin: Style.space(6)
              anchors.verticalCenter: parent.verticalCenter
              visible: !row.isDone
              textFormat: Text.PlainText
              text: tab.closeGlyph
              opacity: rowArea.containsMouse || deleteArea.containsMouse ? 1 : 0
              color: deleteArea.containsMouse ? w.red : Util.alpha(w.fg, 0.55)
              font.family: w.fontFamily
              font.pixelSize: Style.font.body
              z: 2

              MouseArea {
                id: deleteArea
                anchors.fill: parent
                anchors.margins: -Style.space(4)
                enabled: !row.isDone
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: tab.remove(row.task)
              }
            }

            // What the task is worth: 1 XP, +1 for each day it has waited.
            Laurel {
              id: laurel
              anchors.right: parent.right
              anchors.rightMargin: Style.space(4)
              anchors.verticalCenter: parent.verticalCenter
              size: Style.space(24)
              text: String(row.task.xp || 1)
              color: w.gold
              fontFamily: w.fontFamily
              opacity: row.isDone ? 0.45 : 1
            }

            // The whole row checks the task, or puts a done one back.
            MouseArea {
              id: rowArea
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: row.isDone ? tab.reopen(row.task) : tab.complete(row.task)
            }
          }
        }
      }
    }
  }
}
