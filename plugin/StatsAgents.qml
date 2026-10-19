import QtQuick
import qs.Commons
import qs.Ui

// The Agents view of Stats (stats:agents): tokens burned by coding agents
// on every machine, as a sign of work. Today, 30 days, machines, models,
// projects, when they work, and how.
Column {
  id: root

  property var w: null
  property var info: null          // stats:agents
  property color ink: "#ff9e64"
  property var tokensText: function(n) { return String(n) }

  spacing: Style.space(8)

  function money(v) { return "$" + (v >= 100 ? Math.round(v) : v.toFixed(2)) }
  function pct(v) { return v === null || v === undefined ? "—" : v + " %" }
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s }

  component Header: PanelSectionHeader { foreground: root.w.fg; fontFamily: root.w.fontFamily }
  component Row2: StatRow { w: root.w }
  component Note: Text {
    width: root.width
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    color: Util.alpha(root.w.fg, 0.45)
    font.family: root.w.fontFamily
    font.pixelSize: Style.font.caption
  }

  Text {
    visible: !root.info
    textFormat: Text.PlainText
    text: "Reading the agents' transcripts…"
    color: Util.alpha(root.w.fg, 0.5)
    font.family: root.w.fontFamily
    font.pixelSize: Style.font.body
  }

  Column {
    width: parent.width
    spacing: Style.space(6)
    visible: !!root.info

    Header { text: "TODAY" }
    Row2 { label: "Tokens"; value: root.info ? root.tokensText(root.info.today.tokens) : ""; strong: true }
    Row2 { label: "Estimated cost (API prices)"; value: root.info ? root.money(root.info.today.cost) : "" }
    Row2 { label: "Prompts typed here"; value: root.info ? String(root.info.today.prompts) : "" }
    Row2 { label: "Conversations here"; value: root.info ? String(root.info.today.conversations) : "" }

    Header { text: "LAST 30 DAYS" }
    Item {
      id: chart
      width: parent.width
      height: Style.space(64)
      readonly property var days: root.info ? root.info.days : []
      readonly property real scaleMax: Math.max(1, Math.max.apply(null, days.map(function(d) { return d.tokens }).concat([0])))
      Row {
        anchors.fill: parent
        spacing: 1
        Repeater {
          model: chart.days
          Rectangle {
            required property var modelData
            required property int index
            anchors.bottom: parent.bottom
            width: (chart.width - 29) / 30
            height: Math.max(modelData.tokens > 0 ? 2 : 1, modelData.tokens / chart.scaleMax * chart.height)
            color: modelData.tokens > 0 ? Util.alpha(root.ink, index === 29 ? 1 : 0.7) : Util.alpha(root.w.fg, 0.08)
          }
        }
      }
    }
    Row2 { label: "Tokens"; value: root.info ? root.tokensText(root.info.last30.tokens) : "" }
    Row2 { label: "Estimated cost"; value: root.info ? root.money(root.info.last30.cost) : "" }
    Row2 { label: "All time"; value: root.info ? root.tokensText(root.info.lifetime.tokens) + "  ·  " + root.money(root.info.lifetime.cost) : "" }

    Header { text: "BY MACHINE, 30 DAYS" }
    Repeater {
      model: root.info ? root.info.devices : []
      Row2 {
        required property var modelData
        label: root.cap(modelData.key)
        value: root.tokensText(modelData.tokens) + "  ·  " + root.money(modelData.cost)
      }
    }

    Header { text: "BY MODEL, 30 DAYS" }
    Repeater {
      model: root.info ? root.info.families : []
      Row2 {
        required property var modelData
        label: modelData.key === "unknown" ? "Not told (older snapshots)" : root.cap(modelData.key)
        value: root.tokensText(modelData.tokens)
      }
    }

    Header { text: "TOP PROJECTS HERE, 30 DAYS"; visible: !!root.info && root.info.projects.length > 0 }
    Repeater {
      model: root.info ? root.info.projects : []
      Row2 {
        required property var modelData
        label: modelData.key
        value: root.tokensText(modelData.tokens) + "  ·  " + root.money(modelData.cost)
      }
    }

    Header { text: "WHEN AGENTS WORK, 8 WEEKS" }
    Item {
      id: heat
      width: parent.width
      height: 7 * (cell + 2) + Style.space(14)
      readonly property real cell: Math.floor((width - Style.space(16)) / 24) - 2
      readonly property var grid: root.info ? root.info.heatmap : []
      readonly property real scaleMax: {
        var m = 1
        for (var d = 0; d < grid.length; d++) for (var h = 0; h < 24; h++) m = Math.max(m, grid[d][h])
        return m
      }
      Column {
        spacing: 2
        Repeater {
          model: heat.grid
          Row {
            required property var modelData
            required property int index
            spacing: 2
            Text {
              width: Style.space(14)
              textFormat: Text.PlainText
              text: ["S", "M", "T", "W", "T", "F", "S"][index]
              color: Util.alpha(root.w.fg, 0.55)
              font.family: root.w.fontFamily
              font.pixelSize: Style.font.caption - 1
            }
            Repeater {
              model: modelData
              Rectangle {
                required property real modelData
                width: heat.cell
                height: heat.cell
                radius: 2
                color: modelData > 0 ? Util.alpha(root.ink, 0.15 + 0.85 * Math.sqrt(modelData / heat.scaleMax)) : Util.alpha(root.w.fg, 0.05)
              }
            }
          }
        }
        Row {
          Item { width: Style.space(14) + 2; height: 1 }
          Repeater {
            model: 24
            Text {
              required property int index
              width: heat.cell + 2
              textFormat: Text.PlainText
              text: index % 6 === 0 ? String(index) : ""
              color: Util.alpha(root.w.fg, 0.45)
              font.family: root.w.fontFamily
              font.pixelSize: Style.font.caption - 2
            }
          }
        }
      }
    }

    Header { text: "HOW, 30 DAYS" }
    Row2 { label: "Outside your focus sessions"; value: root.info ? root.pct(root.info.outsideShare) : "" }
    Row2 { label: "Conversations at once, peak"; value: root.info ? String(root.info.parallelPeak) : "" }
    Row2 { label: "Read from the cache (here)"; value: root.info ? root.pct(root.info.cacheShare) : "" }
    Row2 { label: "Tokens per prompt (here)"; value: root.info && root.info.tokensPerPrompt ? root.tokensText(root.info.tokensPerPrompt) : "—" }
    Row2 { label: "Written per prompt (here)"; value: root.info && root.info.outputPerPrompt ? root.tokensText(root.info.outputPerPrompt) : "—" }

    Note {
      text: "Every token counts: input, output and cache. This machine reads Claude Code's transcripts; others come from the agents panel's snapshots every 10 minutes, spread evenly when the laptop slept (the heatmap leaves those out). "
        + (root.info ? "XP: 1 per " + root.tokensText(root.info.xpPerDay.tokensPerXp) + " tokens, " + root.info.xpPerDay.cap + " a day at most." : "")
    }
  }
}
