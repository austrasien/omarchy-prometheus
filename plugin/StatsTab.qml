import QtQuick
import qs.Commons
import qs.Ui

// Stats tab: one view at a time, picked with the buttons on top. Overview:
// the hours goal, a few insights, the week by week history (paged back up
// to 52 weeks), and today's apps. The others (StatsExtra): XP by source,
// tasks, focus quality, a heatmap, challenges, presence, context. Fetched
// when shown.
Column {
  id: tab

  property var w: null
  property var p: null
  property string view: "overview"
  // Agent tokens: their own color and scale next to the focus bars.
  readonly property color agentColor: "#ff9e64"
  function tokensText(n) {
    if (n >= 1e9) return (n / 1e9).toFixed(n >= 1e10 ? 0 : 1) + "B"
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M"
    if (n >= 1e3) return Math.round(n / 1e3) + "k"
    return String(n)
  }
  property var extra: null     // stats:extra
  property var agents: null    // stats:agents
  property var coffee: null    // stats:coffee

  property var goal: null      // hoursGoal:get -> { goal, progress }
  property var insights: null  // stats:insights
  property var week: null      // stats:days -> { weekOffset, isoWeek, days, hasOlder }
  property var weekStats: null // stats:summary over the shown week
  property int weekOffset: 0
  property int selected: -1    // index of the inspected day, -1 = whole week
  property var timeline: null  // stats:timeline for the inspected day (or today)
  property string hoverText: ""
  property string spotApp: ""      // app picked in the legend, highlighted in the strip
  property var dayApps: []     // apps of the inspected day, from stats:summary
  property bool dayAppsLoading: false

  // Today's apps come live with the state; any other day is fetched once.
  // The day is read from week.days directly: the selectedDay binding may
  // not have caught up with `selected` yet when this handler runs.
  onSelectedChanged: {
    spotApp = ""
    loadTimeline()
    dayApps = []
    dayAppsLoading = false
    var day = week && week.days && selected >= 0 ? week.days[selected] : null
    if (!day || isTodayDate(day.date) || !p || !p.live) return
    var index = selected
    dayAppsLoading = true
    p.call("stats:summary", [{ fromMs: day.fromMs, toMs: day.fromMs + 24 * 3600 * 1000 - 1 }], function(ok, d) {
      if (tab.selected !== index) return
      tab.dayAppsLoading = false
      if (ok && d && d.success) tab.dayApps = d.apps || []
    })
  }

  // The inspected day's timeline; today's when no day is selected.
  function loadTimeline() {
    if (!p || !p.live) return
    var day = week && week.days && selected >= 0 ? week.days[selected] : null
    var index = selected
    // No window: the daemon's today, with its day start.
    p.call("stats:timeline", day ? [{ fromMs: day.fromMs }] : [], function(ok, d) {
      if (ok && d && d.success && tab.selected === index) tab.timeline = d
    })
  }

  Timer {
    interval: 60 * 1000
    repeat: true
    running: tab.visible && tab.selected < 0
    onTriggered: tab.loadTimeline()
  }

  function isTodayDate(date) { return date === p.todayDate }

  readonly property bool showingOtherDay: !!selectedDay && !isTodayDate(selectedDay.date)
  readonly property var shownApps: showingOtherDay ? dayApps : p.apps

  readonly property int maxWeeks: 52
  readonly property bool editing: false
  spacing: Style.space(10)

  readonly property string leftGlyph: String.fromCodePoint(0xF0141)
  readonly property string rightGlyph: String.fromCodePoint(0xF0142)
  readonly property var monthNames: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  readonly property var dayNames: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

  function refresh() {
    p.call("stats:extra", [], function(ok, d) { if (ok && d && d.success) tab.extra = d })
    p.call("stats:agents", [], function(ok, d) { if (ok && d && d.success) tab.agents = d })
    p.call("stats:coffee", [], function(ok, d) { if (ok && d && d.success) tab.coffee = d })
    if (!p || !p.live) return
    p.call("hoursGoal:get", [], function(ok, d) { if (ok && d && d.success) tab.goal = d })
    p.call("stats:insights", [], function(ok, d) { if (ok && d && d.success) tab.insights = d })
    loadWeek()
    loadTimeline()
  }

  function loadWeek() {
    if (!p || !p.live) return
    var offset = weekOffset
    p.call("stats:days", [offset], function(ok, d) {
      if (!ok || !d || !d.success || offset !== tab.weekOffset) return
      tab.week = d
      tab.selected = -1
      var days = d.days || []
      if (days.length === 7) {
        var to = offset === 0 ? Date.now() : days[6].fromMs + 24 * 3600 * 1000 - 1
        p.call("stats:summary", [{ fromMs: days[0].fromMs, toMs: to }], function(ok2, s) {
          if (ok2 && s && s.success && offset === tab.weekOffset) tab.weekStats = s
        })
      }
    })
  }

  function page(step) {
    var next = Math.max(0, Math.min(maxWeeks - 1, weekOffset + step))
    if (next === weekOffset) return
    if (step > 0 && week && !week.hasOlder) return
    weekOffset = next
    loadWeek()
  }

  function focusEntry() { return false }

  onVisibleChanged: if (visible) { view = "overview"; refresh() }
  Component.onCompleted: if (visible) refresh()

  // The goal only counts closed sessions: the running one is added here.
  readonly property int liveSeconds: p ? p.elapsed : 0

  readonly property string goalPeriodLabel: {
    var period = goal && goal.goal ? goal.goal.period : ""
    return period === "day" ? "Daily" : period === "week" ? "Weekly" : period === "month" ? "Monthly" : ""
  }

  function dateOf(day) { return new Date(day.date + "T12:00:00") }

  readonly property string weekLabel: {
    if (!week || !week.days || week.days.length !== 7) return ""
    var a = dateOf(week.days[0]), b = dateOf(week.days[6])
    var left = a.getMonth() === b.getMonth() ? String(a.getDate()) : a.getDate() + " " + monthNames[a.getMonth()]
    return left + " – " + b.getDate() + " " + monthNames[b.getMonth()] + " · W" + week.isoWeek
  }

  function deltaText(now, then) {
    if (then <= 0) return now > 0 ? "nothing yesterday at this time" : ""
    var pct = Math.round((now - then) / then * 100)
    return (pct >= 0 ? "+" : "") + pct + " % vs yesterday at this time"
  }

  // The inspected day, or the week's totals.
  readonly property var selectedDay: week && selected >= 0 && week.days ? week.days[selected] : null

  // ---- day timeline
  readonly property var tlSegments: timeline ? timeline.segments || [] : []

  readonly property var tlAgents: timeline ? timeline.agents || [] : []

  // The span covers the apps and the agents' measured quarter hours (the
  // ones spread over a gap could stretch it over the whole day).
  readonly property var tlMeasured: tlAgents.filter(function(a) { return !a.estimated })
  readonly property real tlFrom: {
    var first = Infinity
    if (tlSegments.length > 0) first = tlSegments[0].start
    if (tlMeasured.length > 0) first = Math.min(first, tlMeasured[0].start)
    return first === Infinity ? 0 : Math.floor(first / 3600000) * 3600000
  }

  readonly property real tlTo: {
    var end = 0
    for (var i = 0; i < tlSegments.length; i++) end = Math.max(end, tlSegments[i].end)
    for (var j = 0; j < tlMeasured.length; j++) end = Math.max(end, tlMeasured[j].start + 900000)
    return end > 0 ? Math.ceil(end / 3600000) * 3600000 : 0
  }

  readonly property real tlAgentMax: {
    var m = 1
    for (var i = 0; i < tlAgents.length; i++) m = Math.max(m, tlAgents[i].tokens)
    return m
  }

  readonly property real tlSpan: Math.max(1, tlTo - tlFrom)

  // Time per app over the day, and the total, from the strip's segments.
  readonly property var tlTotals: {
    var totals = {}
    for (var i = 0; i < tlSegments.length; i++) {
      var sg = tlSegments[i]
      totals[sg.app] = (totals[sg.app] || 0) + (sg.end - sg.start)
    }
    return totals
  }

  readonly property real tlSum: {
    var t = 0
    for (var k in tlTotals) t += tlTotals[k]
    return Math.max(1, t)
  }

  // Most used apps of the day get the palette, in order; the rest is grey.
  readonly property var tlRanking: Object.keys(tlTotals).sort(function(a, b) { return tlTotals[b] - tlTotals[a] })

  function percent(app) {
    var pct = (tlTotals[app] || 0) / tlSum * 100
    return pct >= 1 ? Math.round(pct) + " %" : "< 1 %"
  }

  readonly property real legendDot: Style.space(8)

  readonly property real legendGap: Style.space(12)

  // Used to measure an entry: the percent then the name, as drawn.
  function legendLabel(app) { return percent(app) + "  " + app }

  readonly property var legendLines: {
    var apps = tlRanking.slice(0, (w.palette || []).length)
    var lines = [], line = [], used = 0, max = tab.width
    for (var i = 0; i < apps.length; i++) {
      var itemWidth = legendDot + 2 * Style.space(4) + legendMetrics.advanceWidth(legendLabel(apps[i]))
      var needed = line.length > 0 ? used + legendGap + itemWidth : itemWidth
      if (line.length > 0 && needed > max) {
        lines.push(line)
        line = []
        needed = itemWidth
      }
      line.push(apps[i])
      used = needed
    }
    if (line.length > 0) lines.push(line)
    return lines
  }

  function appColor(app) {
    var i = tlRanking.indexOf(app)
    var pal = w.palette || []
    return i >= 0 && i < pal.length ? pal[i] : Util.alpha(w.fg, 0.3)
  }

  function clock(ms) { return Qt.formatTime(new Date(ms), "HH:mm") }

  ButtonGroup {
    anchors.horizontalCenter: parent.horizontalCenter
    options: [
      { value: "overview", label: "Overview" },
      { value: "agents", label: "Agents" },
      { value: "xp", label: "XP" },
      { value: "tasks", label: "Tasks" },
      { value: "focus", label: "Focus" }
    ]
    value: tab.view
    foreground: w.fg
    accent: w.accent
    fontFamily: w.fontFamily
    fontSize: Style.font.caption
    focusable: false
    onChanged: function(v) { tab.view = v }
  }

  ButtonGroup {
    anchors.horizontalCenter: parent.horizontalCenter
    options: [
      { value: "heatmap", label: "Heatmap" },
      { value: "challenges", label: "Challenges" },
      { value: "presence", label: "Presence" },
      { value: "context", label: "Context" },
      { value: "coffee", label: "Coffee" }
    ]
    value: tab.view
    foreground: w.fg
    accent: w.accent
    fontFamily: w.fontFamily
    fontSize: Style.font.caption
    focusable: false
    onChanged: function(v) { tab.view = v }
  }

  PanelSeparator { width: parent.width; foreground: w.fg }

  StatsAgents {
    width: parent.width
    visible: tab.view === "agents"
    w: tab.w
    info: tab.agents
    ink: tab.agentColor
    tokensText: tab.tokensText
  }

  StatsCoffee {
    width: parent.width
    visible: tab.view === "coffee"
    w: tab.w
    info: tab.coffee
    tokensText: tab.tokensText
  }

  StatsExtra {
    width: parent.width
    visible: tab.view !== "overview" && tab.view !== "agents" && tab.view !== "coffee"
    w: tab.w
    info: tab.extra
    view: tab.view
  }

  Column {
    width: parent.width
    spacing: Style.space(10)
    visible: tab.view === "overview"

    // ---- hours goal
    Column {
      width: parent.width
      spacing: Style.space(6)
      visible: !!(tab.goal && tab.goal.goal)

      readonly property real worked: tab.goal && tab.goal.progress ? (tab.goal.progress.workedSeconds || 0) + tab.liveSeconds : 0
      readonly property real target: tab.goal && tab.goal.goal ? tab.goal.goal.hours * 3600 : 1

      StatRow {
        w: tab.w
        label: tab.goalPeriodLabel + " goal" + (parent.worked >= parent.target ? "  " + String.fromCodePoint(0xF012C) : "")
        value: p.formatShort(parent.worked) + " / " + (tab.goal && tab.goal.goal ? tab.goal.goal.hours : 0) + " h"
        strong: true
      }

      Rectangle {
        width: parent.width
        height: Style.space(6)
        radius: height / 2
        color: Util.alpha(w.fg, 0.12)

        Rectangle {
          height: parent.height
          radius: parent.radius
          width: parent.width * Math.min(1, parent.parent.worked / Math.max(1, parent.parent.target))
          color: w.accent
        }
      }

      PanelSeparator { width: parent.width; foreground: w.fg }
    }

    // ---- insights
    PanelSectionHeader {
      text: "TODAY"
      foreground: w.fg
      fontFamily: w.fontFamily
    }

    StatRow {
      w: tab.w
      label: "Focus"
      value: tab.insights ? p.formatShort(tab.insights.today.focusSeconds) : "—"
      strong: true
    }
    StatRow {
      w: tab.w
      label: "Tracked time"
      value: tab.insights ? p.formatShort(tab.insights.today.trackedSeconds) : p.formatShort(p.trackedSeconds)
    }

    Text {
      width: parent.width
      visible: text !== ""
      wrapMode: Text.WordWrap
      textFormat: Text.PlainText
      text: {
        var i = tab.insights
        if (!i) return ""
        var parts = []
        var d = tab.deltaText(i.today.trackedSeconds, i.yesterdaySameTime.trackedSeconds)
        if (d) parts.push(d)
        if (i.topApp) parts.push("mostly " + i.topApp.app + " (" + p.formatShort(i.topApp.seconds) + ")")
        if (i.busiestDay) {
          var bd = tab.dateOf(i.busiestDay)
          parts.push("busiest day of the week: " + tab.dayNames[bd.getDay()] + " " + bd.getDate()
            + " (" + p.formatShort(i.busiestDay.trackedSeconds) + ")")
        }
        return parts.join(" · ")
      }
      color: Util.alpha(w.fg, 0.6)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }

    PanelSeparator { width: parent.width; foreground: w.fg }

    // ---- week history
    Item {
      width: parent.width
      height: weekHeader.implicitHeight

      Text {
        id: prevWeek
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: tab.leftGlyph
        readonly property bool enabledNav: !!(tab.week && tab.week.hasOlder) && tab.weekOffset < tab.maxWeeks - 1
        color: !enabledNav ? Util.alpha(w.fg, 0.2) : prevArea.containsMouse ? w.accent : Util.alpha(w.fg, 0.7)
        font.family: w.fontFamily
        font.pixelSize: Style.font.body + 2

        MouseArea {
          id: prevArea
          anchors.fill: parent
          anchors.margins: -Style.space(6)
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: tab.page(1)
        }
      }

      Text {
        id: weekHeader
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        text: tab.weekOffset === 0 ? "THIS WEEK  ·  " + tab.weekLabel : tab.weekLabel
        color: w.fg
        font.family: w.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      Text {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: tab.rightGlyph
        color: tab.weekOffset === 0 ? Util.alpha(w.fg, 0.2) : nextArea.containsMouse ? w.accent : Util.alpha(w.fg, 0.7)
        font.family: w.fontFamily
        font.pixelSize: Style.font.body + 2

        MouseArea {
          id: nextArea
          anchors.fill: parent
          anchors.margins: -Style.space(6)
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: tab.page(-1)
        }
      }
    }

    Row {
      id: bars
      width: parent.width
      height: Style.space(72)
      spacing: Style.space(6)
      readonly property var days: tab.week ? tab.week.days || [] : []
      readonly property real maxSeconds: {
        var m = 60
        for (var i = 0; i < days.length; i++) m = Math.max(m, days[i].trackedSeconds, days[i].focusSeconds)
        return m
      }
      readonly property real barWidth: (width - spacing * 6) / 7
      readonly property real maxTokens: {
        var m = 1
        for (var i = 0; i < days.length; i++) m = Math.max(m, days[i].tokens || 0)
        return m
      }

      Repeater {
        model: bars.days

        // The whole column is the hit area: bar, empty space above it and label.
        Item {
          id: dayCol
          required property var modelData
          required property int index
          readonly property bool isToday: tab.weekOffset === 0 && modelData.date === p.todayDate
          readonly property bool isSelected: tab.selected === index
          readonly property bool hovered: dayArea.containsMouse && !modelData.future
          width: bars.barWidth
          height: bars.height

          Rectangle {
            anchors.fill: parent
            anchors.margins: -Style.space(2)
            radius: Style.space(4)
            color: dayCol.isSelected ? Util.alpha(w.accent, 0.12) : dayCol.hovered ? Util.alpha(w.fg, 0.07) : "transparent"
          }

          Column {
            anchors.fill: parent
            spacing: Style.space(4)

            Item {
              width: parent.width
              height: parent.height - dayLabel.implicitHeight - parent.spacing

              // Tracked time behind, focus time in front.
              Rectangle {
                anchors.bottom: parent.bottom
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width, Style.space(22))
                height: Math.max(Style.space(2), parent.height * dayCol.modelData.trackedSeconds / bars.maxSeconds)
                radius: Style.space(3)
                color: Util.alpha(w.fg, dayCol.modelData.trackedSeconds > 0 ? 0.18 : 0.08)
              }

              Rectangle {
                anchors.bottom: parent.bottom
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width, Style.space(22))
                visible: dayCol.modelData.focusSeconds > 0
                height: Math.max(Style.space(2), parent.height * dayCol.modelData.focusSeconds / bars.maxSeconds)
                radius: Style.space(3)
                color: dayCol.isSelected || dayCol.isToday || dayCol.hovered ? w.accent : Util.alpha(w.accent, 0.55)
              }

              // Agent tokens: a thin bar on the right, on the week's own scale.
              Rectangle {
                anchors.bottom: parent.bottom
                x: parent.width / 2 + Math.min(parent.width, Style.space(22)) / 2 + Style.space(2)
                width: Style.space(4)
                visible: (dayCol.modelData.tokens || 0) > 0
                height: Math.max(Style.space(2), parent.height * (dayCol.modelData.tokens || 0) / bars.maxTokens)
                radius: Style.space(2)
                color: dayCol.isSelected || dayCol.isToday || dayCol.hovered ? tab.agentColor : Util.alpha(tab.agentColor, 0.6)
              }
            }

            Text {
              id: dayLabel
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
              textFormat: Text.PlainText
              text: ["S", "M", "T", "W", "T", "F", "S"][tab.dateOf(dayCol.modelData).getDay()]
              color: dayCol.isSelected || dayCol.isToday || dayCol.hovered ? w.accent : Util.alpha(w.fg, dayCol.modelData.future ? 0.25 : 0.5)
              font.family: w.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: dayCol.isSelected || dayCol.isToday
            }
          }

          MouseArea {
            id: dayArea
            anchors.fill: parent
            hoverEnabled: true
            enabled: !dayCol.modelData.future
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: tab.selected = tab.selected === dayCol.index ? -1 : dayCol.index
          }
        }
      }
    }

    Text {
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      textFormat: Text.PlainText
      text: tab.selected >= 0 ? "Click again to go back to the week" : "Click a day for its details · arrows: previous weeks"
      color: Util.alpha(w.fg, 0.4)
      font.family: w.fontFamily
      font.pixelSize: Style.font.caption
    }


    StatRow {
      w: tab.w
      label: tab.selectedDay ? "Focus " + tab.dayNames[tab.dateOf(tab.selectedDay).getDay()] + " " + tab.dateOf(tab.selectedDay).getDate() : "Focus"
      value: tab.selectedDay ? p.formatShort(tab.selectedDay.focusSeconds) : tab.weekStats ? p.formatShort(tab.weekStats.focusSeconds) : "—"
      strong: true
    }
    StatRow {
      w: tab.w
      label: "Agent tokens"
      visible: value !== "0"
      value: {
        if (tab.selectedDay) return tab.tokensText(tab.selectedDay.tokens || 0)
        var t = 0, days = tab.week ? tab.week.days || [] : []
        for (var i = 0; i < days.length; i++) t += days[i].tokens || 0
        return tab.tokensText(t)
      }
    }
    StatRow {
      w: tab.w
      label: "Tracked time"
      value: {
        if (tab.selectedDay) return p.formatShort(tab.selectedDay.trackedSeconds)
        if (!tab.week || !tab.week.days) return "—"
        var t = 0
        for (var i = 0; i < tab.week.days.length; i++) t += tab.week.days[i].trackedSeconds
        return p.formatShort(t)
      }
    }
    StatRow {
      w: tab.w
      visible: !tab.selectedDay
      label: "Sessions"
      value: tab.weekStats ? String(tab.weekStats.sessions) + (tab.weekStats.deepSessions > 0 ? "  ·  " + tab.weekStats.deepSessions + " of 2 h+" : "") : "—"
    }
    StatRow {
      w: tab.w
      visible: !tab.selectedDay && !!(tab.weekStats && tab.weekStats.switchesPerHour)
      label: "App switches / h in session"
      value: tab.weekStats && tab.weekStats.switchesPerHour ? String(tab.weekStats.switchesPerHour) : ""
    }





    // Legend entries split into centered lines that fit the panel width.
    // FontMetrics measures without being written to, so the binding below
    // does not depend on its own result (TextMetrics.text made it loop).
    FontMetrics { id: legendMetrics; font.family: w.fontFamily; font.pixelSize: Style.font.caption; font.bold: true }





    Column {
      width: parent.width
      spacing: Style.space(6)

      PanelSeparator { width: parent.width; foreground: w.fg }

      PanelSectionHeader {
        text: tab.showingOtherDay
          ? "DAY · " + (tab.dayNames[tab.dateOf(tab.selectedDay).getDay()] + " " + tab.dateOf(tab.selectedDay).getDate()).toUpperCase()
          : "DAY"
        foreground: w.fg
        fontFamily: w.fontFamily
      }

      // Agent tokens per quarter hour, above the apps; paler where spread
      // over a gap between two snapshots of another machine.
      Item {
        visible: tab.tlAgents.length > 0
        width: parent.width
        height: Style.space(18)
        clip: true

        Repeater {
          model: tab.tlAgents
          Rectangle {
            required property var modelData
            anchors.bottom: parent.bottom
            x: (modelData.start - tab.tlFrom) / tab.tlSpan * parent.width
            width: Math.max(1, 900000 / tab.tlSpan * parent.width - 1)
            height: Math.max(1, parent.height * Math.sqrt(modelData.tokens / tab.tlAgentMax))
            color: Util.alpha(tab.agentColor, modelData.estimated ? 0.3 : 0.85)
          }
        }
      }

      Text {
        visible: tab.tlSegments.length === 0
        textFormat: Text.PlainText
        text: "Nothing tracked that day."
        color: Util.alpha(w.fg, 0.45)
        font.family: w.fontFamily
        font.pixelSize: Style.font.body
      }

      Item {
        id: strip
        visible: tab.tlSegments.length > 0
        width: parent.width
        height: Style.space(14) + Style.space(6)

        Rectangle {
          id: track
          width: parent.width
          height: Style.space(14)
          radius: Style.space(3)
          color: Util.alpha(w.fg, 0.06)
          clip: true

          Repeater {
            model: tab.tlSegments

            Rectangle {
              required property var modelData
              x: (modelData.start - tab.tlFrom) / tab.tlSpan * track.width
              width: Math.max(1, (modelData.end - modelData.start) / tab.tlSpan * track.width)
              height: track.height
              color: tab.appColor(modelData.app)
              opacity: tab.spotApp === "" || tab.spotApp === modelData.app ? 1 : 0.18
            }
          }
        }

        // Sessions, underlined in the accent color.
        Repeater {
          model: tab.timeline ? tab.timeline.sessions || [] : []

          Rectangle {
            required property var modelData
            x: Math.max(0, (modelData.start - tab.tlFrom) / tab.tlSpan * track.width)
            y: track.height + Style.space(2)
            width: Math.max(2, (modelData.end - modelData.start) / tab.tlSpan * track.width)
            height: Style.space(3)
            radius: height / 2
            color: w.accent
          }
        }

        MouseArea {
          anchors.fill: parent
          hoverEnabled: true
          onExited: tab.hoverText = ""
          onPositionChanged: function(mouse) {
            var at = tab.tlFrom + mouse.x / track.width * tab.tlSpan
            var segs = tab.tlSegments, hit = ""
            for (var i = 0; i < segs.length; i++) {
              if (at >= segs[i].start && at <= segs[i].end) {
                hit = segs[i].app + " · " + tab.clock(segs[i].start) + " – " + tab.clock(segs[i].end)
                break
              }
            }
            var sess = tab.timeline ? tab.timeline.sessions || [] : []
            for (var j = 0; j < sess.length; j++) {
              if (at >= sess[j].start && at <= sess[j].end) {
                hit += (hit ? "  ·  " : "") + "session " + (sess[j].task || "untitled")
                break
              }
            }
            tab.hoverText = hit
          }
        }
      }

      readonly property string spotInfo: tab.spotApp === "" ? ""
        : tab.spotApp + " · " + p.formatShort((tab.tlTotals[tab.spotApp] || 0) / 1000) + " · " + tab.percent(tab.spotApp)

      Item {
        visible: tab.tlSegments.length > 0
        width: parent.width
        height: fromLabel.implicitHeight

        Text {
          id: fromLabel
          anchors.left: parent.left
          textFormat: Text.PlainText
          text: tab.hoverText !== "" || tab.spotApp !== "" ? "" : tab.clock(tab.tlFrom)
          color: Util.alpha(w.fg, 0.45)
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          textFormat: Text.PlainText
          text: tab.hoverText !== "" ? tab.hoverText : parent.parent.spotInfo
          color: w.fg
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        Text {
          anchors.right: parent.right
          textFormat: Text.PlainText
          text: tab.hoverText !== "" || tab.spotApp !== "" ? "" : tab.clock(tab.tlTo)
          color: Util.alpha(w.fg, 0.45)
          font.family: w.fontFamily
          font.pixelSize: Style.font.caption
        }
      }

      // Legend: the colored apps with their share of the day, centered.
      // A click highlights that app in the strip; a second click clears it.
      Column {
        visible: tab.tlSegments.length > 0
        width: parent.width
        spacing: Style.space(4)

        Repeater {
          model: tab.legendLines

          Row {
            required property var modelData
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: tab.legendGap

            Repeater {
              model: parent.modelData

              Item {
                id: chip
                required property var modelData
                readonly property bool spotted: tab.spotApp === modelData
                readonly property bool dimmed: tab.spotApp !== "" && !spotted
                width: chipRow.implicitWidth
                height: chipRow.implicitHeight

                Row {
                  id: chipRow
                  spacing: Style.space(4)
                  opacity: chip.dimmed ? 0.4 : 1

                  Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: tab.legendDot
                    height: width
                    radius: width / 2
                    color: tab.appColor(chip.modelData)
                    border.width: chip.spotted ? Math.max(1, Style.space(1.5)) : 0
                    border.color: w.fg
                  }

                  // The share, in the app's color, right after the dot.
                  Text {
                    textFormat: Text.PlainText
                    text: tab.percent(chip.modelData)
                    color: tab.appColor(chip.modelData)
                    font.family: w.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                  }

                  Text {
                    textFormat: Text.PlainText
                    text: chip.modelData
                    color: w.fg
                    font.family: w.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: chip.spotted
                  }
                }

                MouseArea {
                  anchors.fill: parent
                  anchors.margins: -Style.space(3)
                  cursorShape: Qt.PointingHandCursor
                  onClicked: tab.spotApp = chip.spotted ? "" : chip.modelData
                }
              }
            }
          }
        }
      }
    }

    // ---- apps
    Column {
      width: parent.width
      spacing: Style.space(6)
      visible: tab.shownApps.length > 0 || tab.showingOtherDay

      PanelSeparator { width: parent.width; foreground: w.fg }

      PanelSectionHeader {
        text: tab.showingOtherDay
          ? "APPS · " + (tab.dayNames[tab.dateOf(tab.selectedDay).getDay()] + " " + tab.dateOf(tab.selectedDay).getDate()
            + " " + tab.monthNames[tab.dateOf(tab.selectedDay).getMonth()]).toUpperCase()
          : "APPS TODAY"
        foreground: w.fg
        fontFamily: w.fontFamily
      }

      Text {
        visible: tab.showingOtherDay && tab.shownApps.length === 0
        textFormat: Text.PlainText
        text: tab.dayAppsLoading ? "Loading…" : "No app tracked that day."
        color: Util.alpha(w.fg, 0.45)
        font.family: w.fontFamily
        font.pixelSize: Style.font.body
      }

      Repeater {
        model: tab.shownApps

        Item {
          required property var modelData
          width: parent.width
          height: appName.implicitHeight + Style.space(6)

          Rectangle {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            height: parent.height
            radius: Style.space(3)
            width: parent.width * Math.min(1, (modelData.seconds || 0) / Math.max(1, tab.shownApps[0].seconds || 1))
            color: Util.alpha(w.accent, 0.14)
          }

          Text {
            id: appName
            anchors.left: parent.left
            anchors.leftMargin: Style.space(6)
            anchors.right: appTime.left
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: modelData.app || "?"
            color: w.fg
            font.family: w.fontFamily
            font.pixelSize: Style.font.body
            elide: Text.ElideRight
          }

          Text {
            id: appTime
            anchors.right: parent.right
            anchors.rightMargin: Style.space(6)
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: p.formatShort(modelData.seconds || 0)
            color: Util.alpha(w.fg, 0.6)
            font.family: w.fontFamily
            font.pixelSize: Style.font.body
          }
        }
      }
    }
  }
}
