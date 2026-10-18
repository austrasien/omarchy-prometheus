import QtQuick
import qs.Commons
import qs.Ui

// Settings tab: the hours goal, apps that are never recorded, and aliases
// that rename or merge apps (applied when reading, so they also rewrite
// the past and can be undone).
Column {
  id: tab

  property var w: null
  property var p: null

  property string goalPeriod: "off"   // off | day | week | month
  property real goalHours: 0
  property var hidden: []
  property var aliases: ({})   // raw app name -> shown name
  property var known: []       // [{ app, alias, seconds }] seen over 30 days
  property var words: []       // forbidden words in window titles
  property int dayStart: 5     // hour the day starts at
  property int presenceEvery: 20   // minutes between "Still there?" checks
  property string handle: ""      // the @handle on the share card
  property string shareFormat: "gif"   // gif | apng

  readonly property bool editing: handleField.activeFocus || hideField.activeFocus || wordField.activeFocus || aliasFrom.activeFocus || aliasTo.activeFocus
  spacing: Style.space(10)

  readonly property var goalLimits: ({ day: [0.5, 16], week: [1, 80], month: [1, 368] })
  readonly property var goalDefaults: ({ day: 4, week: 20, month: 80 })
  readonly property string closeGlyph: String.fromCodePoint(0xF0156)

  function refresh() {
    if (!p || !p.live) return
    p.call("hoursGoal:get", [], function(ok, d) { if (ok && d && d.success) tab.applyGoal(d.goal) })
    p.call("apps:getHidden", [], function(ok, d) { if (ok && d && d.success) tab.hidden = d.hiddenApps || [] })
    p.call("apps:getAliases", [], function(ok, d) { if (ok && d && d.success) tab.aliases = d.aliases || {} })
    p.call("apps:getHiddenWords", [], function(ok, d) { if (ok && d && d.success) tab.words = d.hiddenTitleWords || [] })
    p.call("settings:getDayStart", [], function(ok, d) { if (ok && d && d.success) tab.dayStart = d.dayStartHour })
    p.call("settings:getPresenceEvery", [], function(ok, d) { if (ok && d && d.success) tab.presenceEvery = d.minutes })
    p.call("settings:getHandle", [], function(ok, d) { if (ok && d && d.success) { tab.handle = d.handle; handleField.text = d.handle } })
    p.call("settings:getShareFormat", [], function(ok, d) { if (ok && d && d.success) tab.shareFormat = d.format })
    p.call("apps:known", [30], function(ok, d) { if (ok && d && d.success) tab.known = d.apps || [] })
  }

  readonly property var aliasList: {
    var out = []
    for (var k in aliases) out.push({ from: k, to: aliases[k] })
    out.sort(function(a, b) { return a.to.localeCompare(b.to) || a.from.localeCompare(b.from) })
    return out
  }

  function setAliases(map) {
    p.act("apps:setAliases", [map], "Aliases", function(d) {
      tab.aliases = d ? d.aliases || {} : {}
      p.call("apps:known", [30], function(ok, k) { if (ok && k && k.success) tab.known = k.apps || [] })
    })
  }

  function setDayStart(hour) {
    var h = Math.max(0, Math.min(12, hour))
    if (h === dayStart) return
    p.act("settings:setDayStart", [h], "Day start", function(d) {
      if (d) tab.dayStart = d.dayStartHour
      w.refreshGoal()
    })
  }

  // Saved as it is typed (a moment after the last key), no button.
  function saveHandle() {
    var h = handleField.text.trim().replace(/^@+/, "")
    if (h === handle) return
    p.act("settings:setHandle", [h], "Handle", function(d) { if (d) tab.handle = d.handle })
  }

  Timer { id: handleSaveTimer; interval: 600; onTriggered: tab.saveHandle() }

  function setShareFormat(f) {
    if (f === shareFormat) return
    p.act("settings:setShareFormat", [f], "Export", function(d) { if (d) tab.shareFormat = d.format })
  }

  function setPresenceEvery(minutes) {
    var m = Math.max(5, Math.min(120, minutes))
    if (m === presenceEvery) return
    p.act("settings:setPresenceEvery", [m], "Presence", function(d) { if (d) tab.presenceEvery = d.minutes })
  }

  function setWords(list) {
    p.act("apps:setHiddenWords", [list], "Forbidden words", function(d) { tab.words = d ? d.hiddenTitleWords || [] : [] })
  }

  function addWord() {
    var word = wordField.text.trim()
    if (word.length === 0) return
    setWords(words.concat([word]))
    wordField.text = ""
  }

  function addAlias() {
    var from = aliasFrom.text.trim(), to = aliasTo.text.trim()
    if (from.length === 0 || to.length === 0) return
    var next = {}
    for (var k in aliases) next[k] = aliases[k]
    next[from] = to
    setAliases(next)
    aliasFrom.text = ""
    aliasTo.text = ""
  }

  function removeAlias(from) {
    var next = {}
    for (var k in aliases) if (k !== from) next[k] = aliases[k]
    setAliases(next)
  }

  function applyGoal(goal) {
    goalPeriod = goal ? goal.period : "off"
    goalHours = goal ? goal.hours : 0
  }

  function setGoal(period, hours) {
    if (period === "off") {
      p.act("hoursGoal:set", ["off"], "Goal", function(d) { tab.applyGoal(null); w.refreshGoal() })
      return
    }
    var lim = goalLimits[period]
    var h = Math.round(Math.min(lim[1], Math.max(lim[0], hours)) * 2) / 2
    p.act("hoursGoal:set", [{ hours: h, period: period }], "Goal", function(d) { tab.applyGoal(d ? d.goal : null); w.refreshGoal() })
  }

  function setHidden(list) {
    p.act("apps:setHidden", [list], "Hidden apps", function(d) { tab.hidden = d ? d.hiddenApps || [] : [] })
  }

  function hideTyped() {
    var name = hideField.text.trim()
    if (name.length === 0) return
    setHidden(hidden.concat([name]))
    hideField.text = ""
  }

  function focusEntry() { return false }

  onVisibleChanged: if (visible) refresh()
  Component.onCompleted: if (visible) refresh()

  // ---- the player's @handle, for the share card
  PanelSectionHeader {
    text: "HANDLE"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  Row {
    width: parent.width
    spacing: Style.space(6)

    Text {
      anchors.verticalCenter: handleField.verticalCenter
      textFormat: Text.PlainText
      text: "@"
      color: Util.alpha(w.fg, 0.7)
      font.family: w.fontFamily
      font.pixelSize: Style.font.body
      font.bold: true
    }

    TextField {
      id: handleField
      width: parent.width - Style.space(20)
      placeholderText: "your handle, shown on the panel and when you share"
      foreground: w.fg
      accent: w.accent
      font.family: w.fontFamily
      onTextEdited: handleSaveTimer.restart()
      onAccepted: tab.saveHandle()
      onActiveFocusChanged: if (!activeFocus) tab.saveHandle()
      Keys.onEscapePressed: w.close()
    }
  }

  // ---- share export format
  PanelSectionHeader {
    text: "SHARE EXPORT"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  ButtonGroup {
    options: [
      { value: "gif", label: "GIF" },
      { value: "apng", label: "Animated PNG" }
    ]
    value: tab.shareFormat
    foreground: w.fg
    accent: w.accent
    fontFamily: w.fontFamily
    fontSize: Style.font.caption
    focusable: false
    onChanged: function(v) { tab.setShareFormat(v) }
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: tab.shareFormat === "apng"
      ? "Animated PNG: finer colors. Open in Browser to see it move (image viewers like imv show only its first frame)."
      : "GIF: plays everywhere, image viewers and social networks included."
    color: Util.alpha(w.fg, 0.55)
    font.family: w.fontFamily
    font.pixelSize: Style.font.caption
  }

  // ---- day start
  PanelSectionHeader {
    text: "DAY START"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "Before this hour, time counts for the day before: a night working until 1:00 stays with its evening."
    color: Util.alpha(w.fg, 0.55)
    font.family: w.fontFamily
    font.pixelSize: Style.font.caption
  }

  Row {
    spacing: Style.space(6)

    Button {
      text: "−"
      foreground: w.fg
      accent: w.accent
      bordered: true
      onClicked: tab.setDayStart(tab.dayStart - 1)
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(70)
      horizontalAlignment: Text.AlignHCenter
      textFormat: Text.PlainText
      text: tab.dayStart + " h"
      color: w.fg
      font.family: w.fontFamily
      font.pixelSize: Style.font.body
      font.bold: true
    }

    Button {
      text: "+"
      foreground: w.fg
      accent: w.accent
      bordered: true
      onClicked: tab.setDayStart(tab.dayStart + 1)
    }
  }

  PanelSeparator { width: parent.width; foreground: w.fg }

  // ---- presence check
  PanelSectionHeader {
    text: "PRESENCE CHECK"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "During a session, \"Still there?\" shows up at this interval. Unanswered for 4 min, the session pauses."
    color: Util.alpha(w.fg, 0.55)
    font.family: w.fontFamily
    font.pixelSize: Style.font.caption
  }

  Row {
    spacing: Style.space(6)

    Button {
      text: "−"
      foreground: w.fg
      accent: w.accent
      bordered: true
      onClicked: tab.setPresenceEvery(tab.presenceEvery - 5)
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(70)
      horizontalAlignment: Text.AlignHCenter
      textFormat: Text.PlainText
      text: tab.presenceEvery + " min"
      color: w.fg
      font.family: w.fontFamily
      font.pixelSize: Style.font.body
      font.bold: true
    }

    Button {
      text: "+"
      foreground: w.fg
      accent: w.accent
      bordered: true
      onClicked: tab.setPresenceEvery(tab.presenceEvery + 5)
    }
  }

  PanelSeparator { width: parent.width; foreground: w.fg }

  // ---- hours goal
  PanelSectionHeader {
    text: "HOURS GOAL"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  ButtonGroup {
    options: [
      { value: "off", label: "None" },
      { value: "day", label: "Day" },
      { value: "week", label: "Week" },
      { value: "month", label: "Month" }
    ]
    value: tab.goalPeriod
    foreground: w.fg
    accent: w.accent
    fontFamily: w.fontFamily
    fontSize: Style.font.caption
    focusable: false
    onChanged: function(v) { tab.setGoal(v, tab.goalDefaults[v] || 0) }
  }

  Row {
    visible: tab.goalPeriod !== "off"
    spacing: Style.space(6)

    Button {
      text: "−"
      foreground: w.fg
      accent: w.accent
      bordered: true
      onClicked: tab.setGoal(tab.goalPeriod, tab.goalHours - (tab.goalPeriod === "day" ? 0.5 : 1))
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(70)
      horizontalAlignment: Text.AlignHCenter
      textFormat: Text.PlainText
      text: tab.goalHours + " h"
      color: w.fg
      font.family: w.fontFamily
      font.pixelSize: Style.font.body
      font.bold: true
    }

    Button {
      text: "+"
      foreground: w.fg
      accent: w.accent
      bordered: true
      onClicked: tab.setGoal(tab.goalPeriod, tab.goalHours + (tab.goalPeriod === "day" ? 0.5 : 1))
    }
  }

  PanelSeparator { width: parent.width; foreground: w.fg }

  // ---- hidden apps
  PanelSectionHeader {
    text: "APPS NEVER RECORDED"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "Time spent in these apps is neither counted nor written to disk."
    color: Util.alpha(w.fg, 0.55)
    font.family: w.fontFamily
    font.pixelSize: Style.font.caption
  }

  Row {
    width: parent.width
    spacing: Style.space(6)

    TextField {
      id: hideField
      width: parent.width - hideButton.width - currentButton.width - 2 * parent.spacing
      placeholderText: "App name"
      foreground: w.fg
      accent: w.accent
      font.family: w.fontFamily
      onAccepted: tab.hideTyped()
      Keys.onEscapePressed: w.close()
    }

    Button {
      id: hideButton
      anchors.verticalCenter: hideField.verticalCenter
      text: "Hide"
      foreground: w.fg
      accent: w.accent
      bordered: true
      onClicked: tab.hideTyped()
    }

    Button {
      id: currentButton
      anchors.verticalCenter: hideField.verticalCenter
      text: "Current"
      tooltipText: p.window ? "Hide " + p.window.app : ""
      foreground: w.fg
      accent: w.accent
      bordered: true
      onClicked: if (p.window) tab.setHidden(tab.hidden.concat([p.window.app]))
    }
  }

  Repeater {
    model: tab.hidden

    Item {
      required property var modelData
      width: tab.width
      height: hiddenName.implicitHeight + Style.space(6)

      Text {
        id: hiddenName
        anchors.left: parent.left
        anchors.leftMargin: Style.space(4)
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: modelData
        color: w.fg
        font.family: w.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        anchors.right: parent.right
        anchors.rightMargin: Style.space(4)
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: tab.closeGlyph
        color: removeArea.containsMouse ? w.accent : Util.alpha(w.fg, 0.55)
        font.family: w.fontFamily
        font.pixelSize: Style.font.body

        MouseArea {
          id: removeArea
          anchors.fill: parent
          anchors.margins: -Style.space(4)
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: tab.setHidden(tab.hidden.filter(function(a) { return a !== modelData }))
        }
      }
    }
  }

  PanelSeparator { width: parent.width; foreground: w.fg }

  // ---- forbidden title words
  PanelSectionHeader {
    text: "FORBIDDEN WORDS IN TITLES"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "A window whose title contains one of these words is neither counted nor written to disk. Case is ignored."
    color: Util.alpha(w.fg, 0.55)
    font.family: w.fontFamily
    font.pixelSize: Style.font.caption
  }

  Row {
    width: parent.width
    spacing: Style.space(6)

    TextField {
      id: wordField
      width: parent.width - wordButton.width - parent.spacing
      placeholderText: "Word or phrase"
      foreground: w.fg
      accent: w.accent
      font.family: w.fontFamily
      onAccepted: tab.addWord()
      Keys.onEscapePressed: w.close()
    }

    Button {
      id: wordButton
      anchors.verticalCenter: wordField.verticalCenter
      text: "Add"
      foreground: w.fg
      accent: w.accent
      bordered: true
      onClicked: tab.addWord()
    }
  }

  Repeater {
    model: tab.words

    Item {
      required property var modelData
      width: tab.width
      height: wordText.implicitHeight + Style.space(6)

      Text {
        id: wordText
        anchors.left: parent.left
        anchors.leftMargin: Style.space(4)
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: modelData
        color: w.fg
        font.family: w.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        anchors.right: parent.right
        anchors.rightMargin: Style.space(4)
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: tab.closeGlyph
        color: wordRemoveArea.containsMouse ? w.accent : Util.alpha(w.fg, 0.55)
        font.family: w.fontFamily
        font.pixelSize: Style.font.body

        MouseArea {
          id: wordRemoveArea
          anchors.fill: parent
          anchors.margins: -Style.space(4)
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: tab.setWords(tab.words.filter(function(x) { return x !== modelData }))
        }
      }
    }
  }

  PanelSeparator { width: parent.width; foreground: w.fg }

  // ---- aliases
  PanelSectionHeader {
    text: "RENAME OR MERGE"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "Give several apps the same name to add them up. Applies to the past too."
    color: Util.alpha(w.fg, 0.55)
    font.family: w.fontFamily
    font.pixelSize: Style.font.caption
  }

  Row {
    width: parent.width
    spacing: Style.space(6)

    TextField {
      id: aliasFrom
      width: (parent.width - aliasButton.width - arrow.width - 3 * parent.spacing) / 2
      placeholderText: "App"
      foreground: w.fg
      accent: w.accent
      font.family: w.fontFamily
      onAccepted: aliasTo.forceActiveFocus()
      Keys.onEscapePressed: w.close()
    }

    Text {
      id: arrow
      anchors.verticalCenter: aliasFrom.verticalCenter
      textFormat: Text.PlainText
      text: "→"
      color: Util.alpha(w.fg, 0.5)
      font.family: w.fontFamily
      font.pixelSize: Style.font.body
    }

    TextField {
      id: aliasTo
      width: aliasFrom.width
      placeholderText: "New name"
      foreground: w.fg
      accent: w.accent
      font.family: w.fontFamily
      onAccepted: tab.addAlias()
      Keys.onEscapePressed: w.close()
    }

    Button {
      id: aliasButton
      anchors.verticalCenter: aliasFrom.verticalCenter
      text: "OK"
      foreground: w.fg
      accent: w.accent
      bordered: true
      onClicked: tab.addAlias()
    }
  }

  // Recently seen apps without an alias: a click fills the first field.
  Flow {
    width: parent.width
    spacing: Style.space(6)
    visible: knownRepeater.count > 0

    Repeater {
      id: knownRepeater
      model: tab.known.filter(function(a) { return a.alias === a.app }).slice(0, 10)

      Rectangle {
        required property var modelData
        width: chipText.implicitWidth + Style.space(12)
        height: chipText.implicitHeight + Style.space(6)
        radius: height / 2
        color: chipArea.containsMouse ? Util.alpha(w.accent, 0.2) : Util.alpha(w.fg, 0.08)

        Text {
          id: chipText
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: modelData.app
          color: w.fg
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
        }

        MouseArea {
          id: chipArea
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: {
            aliasFrom.text = modelData.app
            aliasTo.forceActiveFocus()
          }
        }
      }
    }
  }

  Repeater {
    model: tab.aliasList

    Item {
      required property var modelData
      width: tab.width
      height: aliasText.implicitHeight + Style.space(6)

      Text {
        id: aliasText
        anchors.left: parent.left
        anchors.leftMargin: Style.space(4)
        anchors.right: removeAliasGlyph.left
        anchors.rightMargin: Style.space(6)
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: modelData.from + "  →  " + modelData.to
        color: w.fg
        font.family: w.fontFamily
        font.pixelSize: Style.font.body
        elide: Text.ElideRight
      }

      Text {
        id: removeAliasGlyph
        anchors.right: parent.right
        anchors.rightMargin: Style.space(4)
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: tab.closeGlyph
        color: removeAliasArea.containsMouse ? w.accent : Util.alpha(w.fg, 0.55)
        font.family: w.fontFamily
        font.pixelSize: Style.font.body

        MouseArea {
          id: removeAliasArea
          anchors.fill: parent
          anchors.margins: -Style.space(4)
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: tab.removeAlias(modelData.from)
        }
      }
    }
  }
}
