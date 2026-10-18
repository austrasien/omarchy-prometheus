import QtQuick
import qs.Commons
import qs.Ui

// Quests tab: goals that take more than one sitting, kept by prometheusd.
// One quest at a time is active: a red bookmark hangs on the panel and the
// quest shows under the title. Every day a session runs while it is active
// counts as a day worked, and short and long quests pay per day worked.
// Daily quests come back every day; each day's completion is kept.
Column {
  id: tab

  property var w: null
  property var p: null

  property var quests: []     // open quests, active first; each has its own color
  property var done: []       // completed short and long quests, latest first
  property bool showDone: false
  property int doneToday: 0
  property int perDay: 7
  property string kind: "short"

  readonly property bool editing: addField.activeFocus
  spacing: Style.space(10)

  readonly property string uncheckedGlyph: String.fromCodePoint(0xF0131)
  readonly property string checkedGlyph: String.fromCodePoint(0xF0132)
  readonly property string closeGlyph: String.fromCodePoint(0xF0156)
  readonly property string bookmarkGlyph: String.fromCodePoint(0xF00C0)
  readonly property string bookmarkOutlineGlyph: String.fromCodePoint(0xF00C3)

  readonly property var kinds: [
    { value: "daily", label: "Daily" },
    { value: "short", label: "Short" },
    { value: "long", label: "Long" }
  ]

  function rule(k) {
    if (k === "daily") return "Back every day. 5 XP, +1 per day in a row before it, up to 10."
    if (k === "long") return "Followed over more than a week. 30 XP, +5 per day worked on it, up to 150."
    return "Needs a few days to finish. 10 XP, +5 per day worked on it, up to 40."
  }

  function meta(q) {
    if (q.kind === "daily") {
      var parts = ["Daily"]
      if (q.streak > 0) parts.push(q.streak + " in a row")
      if (q.doneToday) parts.push("done today")
      else if (q.timesDone > 0) parts.push("done " + q.timesDone + "×")
      return parts.join("  ·  ")
    }
    var label = q.kind === "long" ? "Long" : "Short"
    var d = q.daysWorked || 0
    return label + "  ·  " + (d === 0 ? "not worked on yet" : d + (d === 1 ? " day" : " days") + " worked")
  }

  function duration(sec) {
    var m = Math.floor(sec / 60), h = Math.floor(m / 60)
    return h > 0 ? h + "h" + (m % 60 < 10 ? "0" : "") + (m % 60) : m + " min"
  }

  // What happened while the quest was active.
  function activityLine(a) {
    if (!a || (a.seconds < 60 && a.tasks === 0 && a.sessions === 0)) return ""
    var parts = [duration(a.seconds), a.sessions + (a.sessions === 1 ? " session" : " sessions")]
    if (a.tasks > 0) parts.push(a.tasks + (a.tasks === 1 ? " task" : " tasks"))
    parts.push("+" + a.xp + " XP")
    return parts.join("  ·  ")
  }

  function refresh() {
    if (!p || !p.live) return
    p.call("quests:list", [], function(ok, d) {
      if (!ok || !d || !d.success) return
      tab.quests = d.quests || []
      tab.done = d.done || []
      tab.doneToday = d.doneToday || 0
      tab.perDay = d.perDay || 7
      if (tab.done.length === 0) tab.showDone = false
    })
  }

  // The bar refreshes the list when the active quest changes elsewhere.
  readonly property string activeId: p && p.quest ? p.quest.id + (p.quest.doneToday ? "+" : "") : ""
  onActiveIdChanged: if (visible) refresh()

  function add() {
    var t = addField.text.trim()
    if (t.length === 0) return
    p.act("quests:add", [t, tab.kind], "Add", function() {
      addField.text = ""
      tab.refresh()
    })
  }

  function toggleActive(q) {
    p.act(q.active ? "quests:deactivate" : "quests:activate", [q.id], "Quest", tab.refresh)
  }

  function check(q) {
    if (q.doneToday) p.act("quests:uncomplete", [q.id], "Quest", tab.refresh)
    else p.act("quests:complete", [q.id], "Quest", tab.refresh)
  }

  function remove(q) { p.act("quests:delete", [q.id], "Delete", tab.refresh) }
  function reopen(q) { p.act("quests:uncomplete", [q.id], "Quest", tab.refresh) }

  readonly property var rows: (showDone ? done.map(function(q) { return { quest: q, isDone: true } }) : [])
    .concat(quests.map(function(q) { return { quest: q, isDone: false } }))

  function focusEntry() {
    addField.forceActiveFocus()
    return true
  }

  onVisibleChanged: if (visible) refresh()
  Component.onCompleted: if (visible) refresh()

  // ---- add
  Row {
    width: parent.width
    spacing: Style.space(6)

    TextField {
      id: addField
      width: parent.width - addButton.width - parent.spacing
      placeholderText: "New quest"
      foreground: w.fg
      accent: w.accent
      font.family: w.fontFamily
      onAccepted: tab.add()
      Keys.onEscapePressed: w.close()
    }

    Button {
      id: addButton
      anchors.verticalCenter: addField.verticalCenter
      text: "Add"
      foreground: w.fg
      accent: w.accent
      bordered: true
      onClicked: tab.add()
    }
  }

  ButtonGroup {
    options: tab.kinds
    value: tab.kind
    foreground: w.fg
    accent: w.accent
    fontFamily: w.fontFamily
    fontSize: Style.font.caption
    focusable: false
    onChanged: function(v) { tab.kind = v }
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: tab.rule(tab.kind) + "  " + tab.doneToday + " / " + tab.perDay + " quests completed today."
    color: Util.alpha(w.fg, 0.55)
    font.family: w.fontFamily
    font.pixelSize: Style.font.caption
  }

  Item {
    width: parent.width
    height: questHeader.implicitHeight

    PanelSectionHeader {
      id: questHeader
      anchors.left: parent.left
      text: "QUESTS"
      foreground: w.fg
      fontFamily: w.fontFamily
    }

    Text {
      anchors.right: parent.right
      anchors.verticalCenter: questHeader.verticalCenter
      visible: tab.done.length > 0
      textFormat: Text.PlainText
      text: (tab.showDone ? "hide " : "") + tab.done.length + " completed"
      color: Util.alpha(w.fg, 0.55)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption

      MouseArea {
        anchors.fill: parent
        anchors.margins: -Style.space(4)
        cursorShape: Qt.PointingHandCursor
        onClicked: tab.showDone = !tab.showDone
      }
    }
  }

  Text {
    width: parent.width
    visible: tab.quests.length === 0 && !tab.showDone
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "No quest yet. A quest is something that takes more than one day."
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
          readonly property var quest: modelData.quest
          readonly property bool isDone: modelData.isDone
          readonly property bool checked: isDone || !!quest.doneToday
          readonly property color questColor: quest.color || w.red
          readonly property bool hovered: rowArea.containsMouse || checkArea.containsMouse
            || markArea.containsMouse || deleteArea.containsMouse
          width: list.width
          height: textBlock.implicitHeight + Style.space(8)

          // The active quest sits in a capsule of its own color.
          Rectangle {
            anchors.fill: parent
            radius: Math.min(height / 2, Style.space(16))
            color: row.quest.active ? Util.alpha(row.questColor, row.hovered ? 0.14 : 0.08)
              : row.hovered ? Util.alpha(w.accent, 0.12) : "transparent"
            border.width: row.quest.active ? 1.5 : 0
            border.color: row.questColor
          }

          // Completes the quest (for today, if daily); checked, undoes it.
          Text {
            id: check
            anchors.left: parent.left
            anchors.leftMargin: Style.space(10)
            anchors.top: textBlock.top
            textFormat: Text.PlainText
            text: row.checked ? tab.checkedGlyph : tab.uncheckedGlyph
            color: checkArea.containsMouse || row.checked ? w.accent : Util.alpha(w.fg, 0.6)
            font.family: w.fontFamily
            font.pixelSize: Style.font.body
            z: 2

            MouseArea {
              id: checkArea
              anchors.fill: parent
              anchors.margins: -Style.space(4)
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: row.isDone ? tab.reopen(row.quest) : tab.check(row.quest)
            }
          }

          Column {
            id: textBlock
            anchors.left: check.right
            anchors.leftMargin: Style.space(8)
            anchors.right: mark.left
            anchors.rightMargin: Style.space(6)
            anchors.top: parent.top
            anchors.topMargin: Style.space(4)
            spacing: Style.space(1)

            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: row.quest.title
              color: row.checked ? Util.alpha(w.fg, 0.45) : w.fg
              font.family: w.fontFamily
              font.pixelSize: Style.font.body
              font.strikeout: row.isDone
              wrapMode: Text.Wrap
            }

            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: tab.meta(row.quest)
              color: Util.alpha(w.fg, 0.5)
              font.family: w.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.Wrap
            }

            Text {
              width: parent.width
              visible: text !== ""
              textFormat: Text.PlainText
              text: tab.activityLine(row.quest.activity)
              color: Util.alpha(w.fg, 0.5)
              font.family: w.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.Wrap
            }

            // When the work happened: one cell per hour of the day,
            // brighter for more focus. Midnight on the left.
            Item {
              id: hoursStrip
              readonly property var hours: row.quest.activity ? row.quest.activity.hours : []
              readonly property int peak: Math.max.apply(null, hours.concat([0]))
              width: parent.width
              height: Style.space(6) + Style.space(3)
              visible: peak > 0

              Row {
                y: Style.space(3)
                spacing: 1
                Repeater {
                  model: hoursStrip.hours
                  Rectangle {
                    required property int modelData
                    width: (hoursStrip.width - 23) / 24
                    height: Style.space(6)
                    radius: 1
                    color: modelData > 0 ? Util.alpha(w.fg, 0.2 + 0.7 * modelData / hoursStrip.peak) : Util.alpha(w.fg, 0.07)
                  }
                }
              }
            }
          }

          // Bookmark: activates the quest, or puts it aside. Always shown,
          // red, on the active one.
          Text {
            id: mark
            anchors.right: deleteGlyph.left
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            visible: !row.isDone
            textFormat: Text.PlainText
            text: row.quest.active ? tab.bookmarkGlyph : tab.bookmarkOutlineGlyph
            opacity: row.quest.active || row.hovered ? 1 : 0
            color: row.quest.active || markArea.containsMouse ? row.questColor : Util.alpha(w.fg, 0.55)
            font.family: w.fontFamily
            font.pixelSize: Style.font.body
            z: 2

            MouseArea {
              id: markArea
              anchors.fill: parent
              anchors.margins: -Style.space(4)
              enabled: !row.isDone
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: tab.toggleActive(row.quest)
            }
          }

          Text {
            id: deleteGlyph
            anchors.right: laurel.left
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            visible: !row.isDone
            textFormat: Text.PlainText
            text: tab.closeGlyph
            opacity: row.hovered ? 1 : 0
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
              onClicked: tab.remove(row.quest)
            }
          }

          // What the quest is worth now, or what it earned.
          Laurel {
            id: laurel
            anchors.right: parent.right
            anchors.rightMargin: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
            size: Style.space(24)
            text: String(row.quest.xp || 0)
            color: w.gold
            fontFamily: w.fontFamily
            opacity: row.checked ? 0.45 : 1
          }

          // The rest of the row activates the quest or puts it aside.
          MouseArea {
            id: rowArea
            anchors.fill: parent
            hoverEnabled: true
            enabled: !row.isDone
            cursorShape: Qt.PointingHandCursor
            onClicked: tab.toggleActive(row.quest)
          }
        }
      }
    }
  }
}
