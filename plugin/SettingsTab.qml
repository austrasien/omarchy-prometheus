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

  readonly property bool editing: hideField.activeFocus || wordField.activeFocus || aliasFrom.activeFocus || aliasTo.activeFocus
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
    p.call("apps:known", [30], function(ok, d) { if (ok && d && d.success) tab.known = d.apps || [] })
  }

  readonly property var aliasList: {
    var out = []
    for (var k in aliases) out.push({ from: k, to: aliases[k] })
    out.sort(function(a, b) { return a.to.localeCompare(b.to) || a.from.localeCompare(b.from) })
    return out
  }

  function setAliases(map) {
    p.act("apps:setAliases", [map], "Alias", function(d) {
      tab.aliases = d ? d.aliases || {} : {}
      p.call("apps:known", [30], function(ok, k) { if (ok && k && k.success) tab.known = k.apps || [] })
    })
  }

  function setDayStart(hour) {
    var h = Math.max(0, Math.min(12, hour))
    if (h === dayStart) return
    p.act("settings:setDayStart", [h], "Début de journée", function(d) {
      if (d) tab.dayStart = d.dayStartHour
      w.refreshGoal()
    })
  }

  function setWords(list) {
    p.act("apps:setHiddenWords", [list], "Mots interdits", function(d) { tab.words = d ? d.hiddenTitleWords || [] : [] })
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
      p.act("hoursGoal:set", ["off"], "Objectif", function(d) { tab.applyGoal(null); w.refreshGoal() })
      return
    }
    var lim = goalLimits[period]
    var h = Math.round(Math.min(lim[1], Math.max(lim[0], hours)) * 2) / 2
    p.act("hoursGoal:set", [{ hours: h, period: period }], "Objectif", function(d) { tab.applyGoal(d ? d.goal : null); w.refreshGoal() })
  }

  function setHidden(list) {
    p.act("apps:setHidden", [list], "Apps masquées", function(d) { tab.hidden = d ? d.hiddenApps || [] : [] })
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

  // ---- day start
  PanelSectionHeader {
    text: "DÉBUT DE JOURNÉE"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "Avant cette heure, le temps compte pour la veille : une soirée jusqu'à 1 h reste dans la même journée."
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

  // ---- hours goal
  PanelSectionHeader {
    text: "OBJECTIF D'HEURES"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  ButtonGroup {
    options: [
      { value: "off", label: "Aucun" },
      { value: "day", label: "Jour" },
      { value: "week", label: "Semaine" },
      { value: "month", label: "Mois" }
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
    text: "APPS NON ENREGISTRÉES"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "Le temps passé dans ces apps n'est ni compté ni écrit sur le disque."
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
      placeholderText: "Nom de l'app"
      foreground: w.fg
      accent: w.accent
      font.family: w.fontFamily
      onAccepted: tab.hideTyped()
      Keys.onEscapePressed: w.close()
    }

    Button {
      id: hideButton
      anchors.verticalCenter: hideField.verticalCenter
      text: "Masquer"
      foreground: w.fg
      accent: w.accent
      bordered: true
      onClicked: tab.hideTyped()
    }

    Button {
      id: currentButton
      anchors.verticalCenter: hideField.verticalCenter
      text: "Actuelle"
      tooltipText: p.window ? "Masquer " + p.window.app : ""
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
    text: "MOTS INTERDITS DANS LES TITRES"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "Une fenêtre dont le titre contient l'un de ces mots n'est ni comptée ni écrite sur le disque. Majuscules ignorées."
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
      placeholderText: "Mot ou expression"
      foreground: w.fg
      accent: w.accent
      font.family: w.fontFamily
      onAccepted: tab.addWord()
      Keys.onEscapePressed: w.close()
    }

    Button {
      id: wordButton
      anchors.verticalCenter: wordField.verticalCenter
      text: "Ajouter"
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
    text: "RENOMMER OU REGROUPER"
    foreground: w.fg
    fontFamily: w.fontFamily
  }

  Text {
    width: parent.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: "Donne le même nom à plusieurs apps pour les additionner. S'applique aussi au passé."
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
      placeholderText: "Nouveau nom"
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
