import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.rtg.omarchy-blink"

  property bool connected: false
  property bool armed: false
  property bool refreshing: false
  property string lastError: ""
  readonly property string helperPath: Qt.resolvedUrl("blink_helper.py").toString().replace(/^file:\/\//, "")
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function applyStatus(text) {
    try {
      var data = JSON.parse(String(text || "{}"))
      if (data.connected !== undefined) connected = data.connected === true
      if (data.armed !== undefined) armed = data.armed === true
      lastError = data.error || ""
      if (panelLoader.item && panelLoader.item.applyStatus) panelLoader.item.applyStatus(data)
    } catch (error) {
      lastError = "Invalid Blink response"
    }
  }

  function refresh() {
    if (refreshing) return
    refreshing = true
    statusProcess.command = ["uv", "run", helperPath, "status"]
    statusProcess.running = true
  }

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }

  function injectPanel() {
    if (!panelLoader.item) return
    panelLoader.item.bar = root.bar
    panelLoader.item.anchorItem = button
    panelLoader.item.hostWidget = root
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  onBarChanged: injectPanel()
  Component.onCompleted: refresh()

  Timer {
    interval: Math.max(60, Number(root.setting("refreshIntervalSec", 60))) * 1000
    repeat: true
    running: true
    onTriggered: root.refresh()
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: { root.injectPanel(); Qt.callLater(root.injectPanel) }
  }

  Process {
    id: statusProcess
    running: false
    command: []
    stdout: StdioCollector { id: statusOutput; waitForEnd: true }
    stderr: StdioCollector { id: statusError; waitForEnd: true }
    onExited: function(exitCode) {
      root.refreshing = false
      var output = String(statusOutput.text || "")
      if (output) root.applyStatus(output)
      else if (exitCode !== 0) root.lastError = String(statusError.text || "Blink refresh failed")
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // A wordmark is intentional here: private-use icon mappings vary between
    // Nerd Font releases and can turn camera glyphs into Wi-Fi-like symbols.
    text: root.refreshing ? "blink…" : "blink"
    tooltipText: root.lastError ? "Blink: " + root.lastError : (root.connected ? (root.armed ? "Blink armed" : "Blink disarmed") : "Connect Blink")
    onPressed: function(buttonCode) { if (buttonCode === Qt.LeftButton) root.toggle() }
  }
}
