import QtQuick
import Quickshell
import Quickshell.Io

// Today's open todos under "## Tasks" in the Obsidian daily note, read only.
// Prometheus keeps its own task list; these are just offered as suggestions
// when adding a task. Nothing is ever written back to the note.
//
// Reading goes through obsidian-daily-qs `status`, bundled with austraz.clock.
Item {
  id: root

  property string vault: ""
  property string bin: ""
  property string heading: "Tasks"

  // [{ text }] open todos of today, in note order.
  property var open: []
  property string error: ""

  readonly property bool available: vault !== "" && bin !== ""

  function today() { return Qt.formatDate(new Date(), "yyyy-MM-dd") }
  function clean(raw) { return String(raw).replace(/^[-*]\s+/, "").trim() }

  function refresh() {
    if (!available || readProc.running) return
    readProc.command = [bin, "--vault", vault, "--heading", heading, "status", "--date", today()]
    readProc.running = true
  }

  Process {
    id: readProc
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var d = JSON.parse(text)
          root.open = (d.todos || [])
            .filter(function(t) { return !t.checked })
            .map(function(t) { return { text: root.clean(t.text) } })
            .filter(function(t) { return t.text.length > 0 })
          root.error = ""
        } catch (e) {
          root.open = []
          root.error = "Could not read the journal"
        }
      }
    }
  }
}
