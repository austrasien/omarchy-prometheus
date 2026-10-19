import QtQuick
import qs.Commons
import qs.Ui

// Achievements tab: names in their rarity's color (normal, common green,
// rare blue, epic purple, legendary gold and shining). Recent unlocks with their lines, then every family with
// its next tier and the progress toward it. Secret families stay "???"
// until one of their tiers unlocks. A family not started yet shows only the
// shape of its text (dots), and so do the tiers after the next one: the daemon
// sends them that way. Fetched when the tab is shown.
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

  // Unlocks of the last 7 days, across families, newest first (16 at most;
  // at least the 3 latest, however old).
  readonly property int recentDays: 7
  readonly property int recentMax: 16
  readonly property var unlockedAll: {
    var all = []
    for (var i = 0; i < families.length; i++) {
      var f = families[i]
      for (var j = 0; j < f.tiers.length; j++)
        if (f.tiers[j].unlockedAt) all.push(f.tiers[j])
    }
    all.sort(function(a, b) { return b.unlockedAt - a.unlockedAt })
    return all
  }
  readonly property var recentAll: {
    var since = Date.now() - recentDays * 86400000
    var out = unlockedAll.filter(function(t) { return t.unlockedAt >= since })
    return out.length >= 3 ? out : unlockedAll.slice(0, 3)
  }
  readonly property var recent: recentAll.slice(0, recentMax)
  property var picked: null              // the capsule pointed at; the newest by default
  readonly property var detail: picked || (recent.length ? recent[0] : null)

  // Capsules split into centered lines that fit the width.
  FontMetrics { id: capMetrics; font.family: w.fontFamily; font.pixelSize: Style.font.caption; font.bold: true }
  readonly property var capsuleLines: {
    var lines = [], line = [], used = 0, gap = Style.space(6)
    for (var i = 0; i < recent.length; i++) {
      var t = recent[i]
      var wd = capMetrics.advanceWidth("\u{F0538} " + t.name + "  +" + t.xp) + Style.space(20)
      var need = line.length ? used + gap + wd : wd
      if (line.length && need > width) { lines.push(line); line = []; need = wd }
      line.push(t)
      used = need
    }
    if (line.length) lines.push(line)
    return lines
  }

  function ago(ms) {
    var m = Math.round((Date.now() - ms) / 60000)
    if (m < 60) return m <= 1 ? "just now" : m + " min ago"
    var h = Math.round(m / 60)
    if (h < 24) return h + " h ago"
    var d = Math.round(h / 24)
    return d === 1 ? "yesterday" : d + " days ago"
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
      if (f.masked) return 3          // the unknown, at the bottom
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
    var unit = f.unit ? " " + f.unit : ""
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

  // ---- recent unlocks, as capsules (like the bar's), the picked one's lines below
  Column {
    width: parent.width
    spacing: Style.space(8)
    visible: tab.recent.length > 0

    PanelSectionHeader {
      text: tab.recentAll.length > tab.recent.length
        ? "LATEST  ·  " + tab.recent.length + " OF " + tab.recentAll.length + " THIS WEEK"
        : "LATEST"
      foreground: w.fg
      fontFamily: w.fontFamily
    }

    Column {
      width: parent.width
      spacing: Style.space(6)
      Repeater {
        model: tab.capsuleLines
        Row {
          required property var modelData
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(6)
          Repeater {
            model: modelData
            AchCapsule {
              required property var modelData
              w: tab.w
              tier: modelData
              selected: tab.detail === modelData
              onPicked: tab.picked = modelData
            }
          }
        }
      }
    }

    Column {
      width: parent.width
      spacing: Style.space(2)
      visible: !!tab.detail

      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        textFormat: Text.PlainText
        text: tab.detail ? tab.detail.desc + "\u00a0\u00a0·\u00a0" + tab.ago(tab.detail.unlockedAt).replace(/ /g, "\u00a0") : ""
        color: Util.alpha(w.fg, 0.75)
        font.family: w.fontFamily
        font.pixelSize: Style.font.caption
      }
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        textFormat: Text.PlainText
        text: tab.detail ? tab.detail.quip || "" : ""
        color: Util.alpha(w.fg, 0.5)
        font.family: w.fontFamily
        font.pixelSize: Style.font.caption
        font.italic: true
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
          // The calendar: one row for the whole collection of dates.
          readonly property bool collection: modelData.kind === "collection"
          readonly property bool masked: !!modelData.masked
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

                // The tier shown (the next one, or the last if complete),
                // in its rarity's color.
                RarityText {
                  id: famName
                  readonly property var shownTier: fam.collection ? null : fam.complete ? fam.last : fam.next
                  readonly property string rarity: shownTier && shownTier.rarity ? shownTier.rarity : "normal"
                  anchors.left: parent.left
                  anchors.right: famCount.left
                  anchors.rightMargin: Style.space(6)
                  text: fam.collection ? fam.modelData.title
                    : fam.complete ? (fam.last ? fam.last.name : fam.modelData.title) : fam.next.name
                  color: fam.masked ? Util.alpha(w.fg, 0.3) : w.rarityColor(rarity)
                  legendary: !fam.masked && rarity === "legendary"
                  fontFamily: w.fontFamily
                  pixelSize: Style.font.body
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
                text: fam.collection
                  ? (fam.last ? "Latest: " + fam.last.name + ". " : "") + "Finish a session on the right day: each date hides an event."
                  : fam.complete ? "Complete." : fam.next.desc
                color: Util.alpha(w.fg, fam.masked ? 0.25 : 0.65)
                font.family: w.fontFamily
                font.pixelSize: Style.font.caption
              }
            }

            Laurel {
              id: laurel
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              size: Style.space(26)
              text: fam.masked ? "?" : String(fam.complete ? (fam.last ? fam.last.xp : 0) : fam.next.xp)
              color: w.gold
              fontFamily: w.fontFamily
              opacity: fam.complete ? 0.5 : fam.masked ? 0.3 : 1
            }
          }

          // Progress toward the next tier (count-like families only).
          Item {
            visible: fam.collection || (!fam.complete && fam.modelData.value !== null && fam.modelData.compare === "ge"
              && fam.next && fam.next.threshold !== null)
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
              width: fam.collection ? parent.width * fam.done / Math.max(1, fam.modelData.tiers.length)
                : fam.next && fam.next.threshold
                ? parent.width * Math.min(1, (fam.modelData.value || 0) / fam.next.threshold) : 0
            }
          }

          Text {
            visible: text !== ""
            textFormat: Text.PlainText
            text: fam.collection ? fam.done + " / " + fam.modelData.tiers.length + " dates found"
              : tab.progressText(fam.modelData, fam.next)
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
