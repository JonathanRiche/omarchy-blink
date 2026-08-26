# Contributing

Thanks for improving Blink Cameras for Omarchy.

## Before opening a pull request

1. Keep credentials, tokens, camera images, and personal camera names out of commits.
2. Preserve the minimum 60-second automatic refresh interval.
3. Validate and lint the plugin:

   ```sh
   omarchy plugin validate .
   qmllint -I /usr/share/omarchy/shell BarWidget.qml Panel.qml
   uvx ruff check blink_helper.py
   uvx ruff format --check blink_helper.py
   ```

4. Test disconnected startup, login/2FA, refresh, arm/disarm, live view, panel
   closure during live view, and logout where relevant.
5. Explain user-visible changes and hardware tested in the pull request.

Use GitHub Issues for reproducible bugs and feature proposals. Report security
problems privately as described in [SECURITY.md](SECURITY.md).
