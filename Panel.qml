import QtQuick
import QtQuick.Controls
import QtMultimedia
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.jonathanriche.omarchy-blink"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property bool connected: false
  property bool armed: false
  property bool busy: false
  property bool needs2fa: false
  property string message: ""
  property var cameras: []
  property var systems: []
  property string liveCamera: ""
  property string liveUrl: ""
  readonly property string helperPath: Qt.resolvedUrl("blink_helper.py").toString().replace(/^file:\/\//, "")
  readonly property color contentForeground: bar ? bar.foreground : Color.foreground
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family

  function open() { controller.show(); refresh() }
  function close() { stopLive(); controller.hide() }
  function toggle() { if (opened) close(); else open() }
  function switchPanel(direction) {
    if (bar && typeof bar.switchPanelFrom === "function") return bar.switchPanelFrom(hostWidget || root, direction)
    return false
  }

  function applyStatus(data) {
    if (!data) return
    connected = data.connected === true
    armed = data.armed === true
    cameras = data.cameras || []
    systems = data.systems || []
    if (data.error) message = String(data.error)
  }

  function refresh() {
    if (busy || !connected) return
    busy = true
    actionProcess.command = ["uv", "run", helperPath, "status"]
    actionProcess.running = true
  }

  function connectBlink() {
    if (busy || emailField.text.trim() === "" || passwordField.text === "") return
    busy = true
    needs2fa = false
    message = "Connecting securely… first launch may take a moment"
    loginProcess.command = ["uv", "run", helperPath, "login"]
    loginProcess.running = true
  }

  function send2fa() {
    if (!loginProcess.running || codeField.text.trim() === "") return
    loginProcess.write(JSON.stringify({code: codeField.text.trim()}) + "\n")
    codeField.text = ""
    message = "Verifying code…"
  }

  function setArmed(value) {
    if (busy) return
    busy = true
    message = value ? "Arming…" : "Disarming…"
    actionProcess.command = ["uv", "run", helperPath, value ? "arm" : "disarm"]
    actionProcess.running = true
  }

  function disconnectBlink() {
    if (busy) return
    busy = true
    actionProcess.command = ["uv", "run", helperPath, "logout"]
    actionProcess.running = true
  }

  function startLive(cameraName) {
    stopLive()
    liveCamera = String(cameraName)
    liveUrl = ""
    message = "Starting " + liveCamera + " live view…"
    liveProcess.command = ["uv", "run", helperPath, "live", liveCamera]
    liveProcess.running = true
  }

  function stopLive() {
    livePlayer.stop()
    liveUrl = ""
    liveCamera = ""
    if (liveProcess.running) liveProcess.running = false
  }

  KeyboardPanel {
    id: popup
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: popup.fittedContentWidth(Style.space(420))
    contentHeight: popup.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: emailField.activeFocus || passwordField.activeFocus || codeField.activeFocus
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
          id: content
          width: parent.width
          spacing: Style.space(10)

          Row {
            width: parent.width
            spacing: Style.space(10)
            Text { text: "󰄀"; color: root.contentForeground; font.family: root.contentFontFamily; font.pixelSize: 34 }
            Column {
              width: parent.width - 60
              Text { text: "BLINK CAMERAS"; color: root.contentForeground; font.family: root.contentFontFamily; font.pixelSize: Style.font.subtitle; font.bold: true }
              Text { text: root.connected ? (root.armed ? "SYSTEM ARMED" : "SYSTEM DISARMED") : "NOT CONNECTED"; color: root.connected && root.armed ? Color.accent : root.contentForeground; font.family: root.contentFontFamily; font.pixelSize: Style.font.caption }
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: !root.connected

            Text { width: parent.width; text: "Connect your Amazon Blink account. Your password is used only for this login and is never saved."; wrapMode: Text.WordWrap; color: root.contentForeground; font.family: root.contentFontFamily; font.pixelSize: Style.font.body }
            TextField { id: emailField; width: parent.width; placeholderText: "Blink email"; enabled: !root.busy && !root.needs2fa }
            TextField { id: passwordField; width: parent.width; placeholderText: "Blink password"; password: true; enabled: !root.busy && !root.needs2fa; onAccepted: root.connectBlink() }
            TextField { id: codeField; width: parent.width; placeholderText: "2FA code"; visible: root.needs2fa; enabled: root.needs2fa; onAccepted: root.send2fa() }

            Button {
              width: parent.width
              text: root.needs2fa ? "Verify code" : (root.busy ? "Connecting…" : "Connect Blink")
              enabled: root.needs2fa ? codeField.text.trim() !== "" : (!root.busy && emailField.text.trim() !== "" && passwordField.text !== "")
              onClicked: root.needs2fa ? root.send2fa() : root.connectBlink()
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: root.connected

            Rectangle {
              width: parent.width
              height: width * 9 / 16
              visible: root.liveCamera !== ""
              color: "black"
              radius: Style.cornerRadius
              clip: true

              VideoOutput {
                id: liveVideo
                anchors.fill: parent
                fillMode: VideoOutput.PreserveAspectFit
              }

              Text {
                anchors.centerIn: parent
                visible: root.liveUrl === ""
                text: "Connecting to " + root.liveCamera + "…"
                color: "white"
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.body
              }

              MouseArea {
                anchors.fill: parent
                onClicked: root.stopLive()
                cursorShape: Qt.PointingHandCursor
              }
            }

            MediaPlayer {
              id: livePlayer
              source: root.liveUrl
              videoOutput: liveVideo
              audioOutput: AudioOutput { muted: true }
              onErrorOccurred: function(error, errorString) {
                root.message = "Live view: " + errorString
              }
            }

            Row {
              width: parent.width
              spacing: Style.space(8)
              Button { width: (parent.width - 8) / 2; text: root.armed ? "Disarm all" : "Arm all"; enabled: !root.busy; onClicked: root.setArmed(!root.armed) }
              Button { width: (parent.width - 8) / 2; text: root.busy ? "Refreshing…" : "Refresh"; enabled: !root.busy; onClicked: root.refresh() }
            }

            Repeater {
              model: root.cameras
              Rectangle {
                required property var modelData
                width: content.width
                height: cameraRow.implicitHeight + Style.space(16)
                radius: Style.cornerRadius
                color: Style.controlFill(false, false, root.contentForeground, Color.accent)
                Row {
                  id: cameraRow
                  anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: Style.space(8) }
                  spacing: Style.space(10)
                  Text { text: modelData.motion ? "󰍹" : "󰄀"; color: modelData.motion ? Color.accent : root.contentForeground; font.family: root.contentFontFamily; font.pixelSize: 24 }
                  Column {
                    width: parent.width - 128
                    Text { text: modelData.name; color: root.contentForeground; font.family: root.contentFontFamily; font.bold: true; font.pixelSize: Style.font.body }
                    Text {
                      text: "Battery " + (modelData.battery || "unknown") + (modelData.temperatureC === null || modelData.temperatureC === undefined ? "" : "  •  " + modelData.temperatureC + "°C")
                      color: Qt.darker(root.contentForeground, 1.2); font.family: root.contentFontFamily; font.pixelSize: Style.font.caption
                    }
                  }
                  Button {
                    width: 76
                    text: root.liveCamera === modelData.name ? "Stop" : "Live"
                    enabled: !root.busy
                    onClicked: root.liveCamera === modelData.name ? root.stopLive() : root.startLive(modelData.name)
                  }
                }
              }
            }

            Button { width: parent.width; text: "Disconnect Blink"; enabled: !root.busy; onClicked: root.disconnectBlink() }
          }

          Text {
            width: parent.width
            visible: root.message !== ""
            text: root.message
            wrapMode: Text.WordWrap
            color: root.contentForeground
            font.family: root.contentFontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }

  Process {
    id: loginProcess
    running: false
    command: []
    stdinEnabled: true
    property string pendingCredentials: ""
    onStarted: {
      pendingCredentials = JSON.stringify({username: emailField.text.trim(), password: passwordField.text})
      write(pendingCredentials + "\n")
      pendingCredentials = ""
      passwordField.text = ""
    }
    stdout: SplitParser {
      onRead: function(line) {
        try {
          var data = JSON.parse(String(line))
          if (data.event === "needs_2fa") {
            root.needs2fa = true
            root.busy = false
            root.message = "Enter the verification code Blink just sent you"
            Qt.callLater(function() { codeField.forceActiveFocus() })
          } else if (data.event === "connected") {
            root.needs2fa = false
            root.busy = false
            root.message = "Connected"
            root.applyStatus(data.status)
            if (root.hostWidget) root.hostWidget.applyStatus(JSON.stringify(data.status))
          } else if (data.event === "error") {
            root.message = data.error || "Blink login failed"
          }
        } catch (error) { root.message = "Could not understand Blink login response" }
      }
    }
    stderr: StdioCollector { id: loginError; waitForEnd: true }
    onExited: function(exitCode) {
      root.busy = false
      if (exitCode !== 0 && !root.needs2fa && root.message === "") root.message = String(loginError.text || "Blink login failed")
    }
  }

  Process {
    id: actionProcess
    running: false
    command: []
    stdout: StdioCollector { id: actionOutput; waitForEnd: true }
    stderr: StdioCollector { id: actionError; waitForEnd: true }
    onExited: function(exitCode) {
      root.busy = false
      var output = String(actionOutput.text || "")
      if (output) {
        try {
          var data = JSON.parse(output)
          root.applyStatus(data)
          if (root.hostWidget) root.hostWidget.applyStatus(output)
          root.message = data.error || ""
        } catch (error) { root.message = "Invalid Blink response" }
      } else if (exitCode !== 0) root.message = String(actionError.text || "Blink action failed")
    }
  }

  Process {
    id: liveProcess
    running: false
    command: []
    stdout: SplitParser {
      onRead: function(line) {
        try {
          var data = JSON.parse(String(line))
          if (data.event === "live_ready") {
            root.liveUrl = data.url || ""
            root.message = "Live: " + data.camera + " · click video to stop"
            livePlayer.play()
          } else if (data.event === "live_ended") {
            root.message = "Live session ended"
            root.stopLive()
          } else if (data.event === "error") {
            root.message = data.error || "Live view failed"
            root.stopLive()
          }
        } catch (error) { root.message = "Invalid live-view response" }
      }
    }
    stderr: StdioCollector { id: liveError; waitForEnd: true }
    onExited: function(exitCode) {
      livePlayer.stop()
      root.liveUrl = ""
      if (exitCode !== 0 && root.message.indexOf("Live view:") !== 0)
        root.message = String(liveError.text || "Live view stopped")
    }
  }
}
