import QtQuick
import qs.Commons
import qs.Ui

// Achievements tab: recent unlocks with their lines, then every family with
// its next tier and the progress toward it. Secret families stay "???"
// until one of their tiers unlocks. Fetched when the tab is shown.
Column {
  id: tab

  property var w: null
  property var p: null

  property var achData: null       // achievements:list
  property string filter: "open"   // open: families with tiers left; all; done

  readonly property bool editing: false
  spacing: Style.space(10)

  function refresh() {
    if (!p || !p.live) return
    p.call("achievements:list", [], function(ok, d) { if (ok && d && d.success) tab.achData = d })
  }

  function focusEntry() { return false }

  onVisibleChanged: if (visible) refresh()
  Component.onCompleted: if (visible) refresh()

  // Unlocks arrive as toasts; re-read so the tab is current if it is open.
  Connections {
    target: p
    function onToast(kind, title, text) { if (kind === "achievement" && tab.visible) tab.refresh() }
  }

  readonly property var families: achData ? achData.families || [] : []

  // The 3 latest unlocks, across families, newest first.
  readonly property var recent: {
    var all = []
    for (var i = 0; i < families.length; i++) {
      var f = families[i]
      for (var j = 0; j < f.tiers.length; j++)
        if (f.tiers[j].unlockedAt) all.push(f.tiers[j])
    }
    all.sort(function(a, b) { return b.unlockedAt - a.unlockedAt })
    return all.slice(0, 3)
  }

  function doneCount(f) {
    var n = 0
    for (var i = 0; i < f.tiers.length; i++) if (f.tiers[i].unlockedAt) n++
    return n
  }

  function nextTier(f) {
    for (var i = 0; i < f.tiers.length; i++) if (!f.tiers[i].unlockedAt) return f.tiers[i]
    return null
  }

  function lastUnlocked(f) {
    var last = null
    for (var i = 0; i < f.tiers.length; i++) if (f.tiers[i].unlockedAt) last = f.tiers[i]
    return last
  }

  readonly property var shown: families.filter(function(f) {
    var next = tab.nextTier(f)
    if (tab.filter === "open") return next !== null
    if (tab.filter === "done") return tab.doneCount(f) > 0
    return true
  }).sort(function(a, b) {
    // Closest to the next tier first; secrets and empty measures last.
    function score(f) {
      var n = tab.nextTier(f)
      if (!n || f.value === null || n.threshold === null || f.compare !== "ge") return 2
      return 1 - Math.min(1, f.value / Math.max(0.0001, n.threshold))
    }
    return score(a) - score(b)
  })

  function clockLabel(h) {
    var hh = Math.floor(h) % 24, mm = Math.round((h - Math.floor(h)) * 60)
    return hh + ":" + String(mm).padStart(2, "0")
  }

  function progressText(f, next) {
    if (f.value === null || f.value === undefined) return ""
    if (f.compare === "lt") return "best: " + clockLabel(f.value)
    if (f.compare === "gt") return "latest: " + clockLabel(f.value)
    var unit = f.unit === "h" ? " h" : f.unit === "%" ? " %" : f.unit === "days" ? " days" : ""
    var v = Math.floor(f.value * 10) / 10
    return next && next.threshold !== null ? v + " / " + next.threshold + unit : v + unit
  }

  // ---- summary
  Item {
    width: parent.width
    height: summaryText.implicitHeight

    Text {
      id: summaryText
      anchors.left: parent.left
      textFormat: Text.PlainText
      text: tab.achData ? tab.achData.unlocked + " / " + tab.achData.total + " unlocked" : "…"
      color: w.gold
      font.family: w.fontFamily
      font.pixelSize: Style.font.body
      font.bold: true
    }

    Text {
      anchors.right: parent.right
      anchors.verticalCenter: summaryText.verticalCenter
      textFormat: Text.PlainText
      text: tab.achData ? "+" + tab.achData.xp + " XP" : ""
      color: Util.alpha(w.fg, 0.6)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  // ---- recent unlocks, with their lines
  Column {
    width: parent.width
    spacing: Style.space(6)
    visible: tab.recent.length > 0

    PanelSectionHeader {
      text: "LATEST"
      foreground: w.fg
      fontFamily: w.fontFamily
    }

    Repeater {
      model: tab.recent

      Column {
        required property var modelData
        width: tab.width
        spacing: Style.space(2)

        Item {
          width: parent.width
          height: recentName.implicitHeight

          Text {
            id: recentName
            anchors.left: parent.left
            anchors.right: recentXp.left
            anchors.rightMargin: Style.space(6)
            textFormat: Text.PlainText
            text: modelData.name
            color: w.fg
            font.family: w.fontFamily
            font.pixelSize: Style.font.body
            font.bold: true
            elide: Text.ElideRight
          }

          Text {
            id: recentXp
            anchors.right: parent.right
            textFormat: Text.PlainText
            text: "+" + modelData.xp + " XP"
            color: w.gold
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        Text {
          width: parent.width
          wrapMode: Text.WordWrap
          textFormat: Text.PlainText
          text: modelData.quip || ""
          color: Util.alpha(w.fg, 0.6)
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
          font.italic: true
        }
      }
    }
  }

  PanelSeparator { width: parent.width; foreground: w.fg }

  ButtonGroup {
    anchors.horizontalCenter: parent.horizontalCenter
    options: [
      { value: "open", label: "To unlock" },
      { value: "done", label: "Unlocked" },
      { value: "all", label: "All" }
    ]
    value: tab.filter
    foreground: w.fg
    accent: w.accent
    fontFamily: w.fontFamily
    fontSize: Style.font.caption
    focusable: false
    onChanged: function(v) { tab.filter = v }
  }

  // ---- families
  Flickable {
    width: parent.width
    height: Math.min(familyList.implicitHeight, Style.space(420))
    contentWidth: width
    contentHeight: familyList.implicitHeight
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    interactive: contentHeight > height

    Column {
      id: familyList
      width: parent.width
      spacing: Style.space(12)

      Repeater {
        model: tab.shown

        Column {
          id: fam
          required property var modelData
          readonly property var next: tab.nextTier(modelData)
          readonly property var last: tab.lastUnlocked(modelData)
          readonly property int done: tab.doneCount(modelData)
          readonly property bool complete: next === null
          width: familyList.width
          spacing: Style.space(4)

          Item {
            width: parent.width
            height: Math.max(famText.implicitHeight, laurel.height)

            Column {
              id: famText
              anchors.left: parent.left
              anchors.right: laurel.left
              anchors.rightMargin: Style.space(8)
              spacing: Style.space(2)

              Item {
                width: parent.width
                height: famName.implicitHeight

                Text {
                  id: famName
                  anchors.left: parent.left
                  anchors.right: famCount.left
                  anchors.rightMargin: Style.space(6)
                  textFormat: Text.PlainText
                  text: fam.complete ? (fam.last ? fam.last.name : fam.modelData.title) : fam.next.name
                  color: fam.complete ? w.gold : w.fg
                  font.family: w.fontFamily
                  font.pixelSize: Style.font.body
                  font.bold: true
                  elide: Text.ElideRight
                }

                Text {
                  id: famCount
                  anchors.right: parent.right
                  anchors.verticalCenter: famName.verticalCenter
                  visible: fam.modelData.tiers.length > 1
                  textFormat: Text.PlainText
                  text: fam.done + "/" + fam.modelData.tiers.length
                  color: Util.alpha(w.fg, 0.5)
                  font.family: w.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              Text {
                width: parent.width
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
                text: fam.complete ? "Complete." : fam.next.desc
                color: Util.alpha(w.fg, 0.65)
                font.family: w.fontFamily
                font.pixelSize: Style.font.caption
              }
            }

            Laurel {
              id: laurel
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              size: Style.space(26)
              text: String(fam.complete ? (fam.last ? fam.last.xp : 0) : fam.next.xp)
              color: w.gold
              fontFamily: w.fontFamily
              opacity: fam.complete ? 0.5 : 1
            }
          }

          // Progress toward the next tier (count-like families only).
          Item {
            visible: !fam.complete && fam.modelData.value !== null && fam.modelData.compare === "ge"
              && fam.next && fam.next.threshold !== null
            width: parent.width
            height: Style.space(5)

            Rectangle {
              anchors.fill: parent
              radius: height / 2
              color: Util.alpha(w.fg, 0.12)
            }

            Rectangle {
              height: parent.height
              radius: height / 2
              color: w.gold
              width: fam.next && fam.next.threshold
                ? parent.width * Math.min(1, (fam.modelData.value || 0) / fam.next.threshold) : 0
            }
          }

          Text {
            visible: text !== ""
            textFormat: Text.PlainText
            text: tab.progressText(fam.modelData, fam.next)
            color: Util.alpha(w.fg, 0.45)
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption
          }

          // The line of the last tier unlocked.
          Text {
            visible: !!(fam.last && fam.last.quip)
            width: parent.width
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: fam.last && fam.last.quip ? "« " + fam.last.quip + " »" : ""
            color: Util.alpha(w.gold, 0.75)
            font.family: w.fontFamily
            font.pixelSize: Style.font.caption
            font.italic: true
          }
        }
      }
    }
  }
}
