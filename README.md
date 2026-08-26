# Blink Cameras for Omarchy

An Omarchy Quattro bar widget for Amazon Blink cameras. It shows armed state,
camera battery and temperature, provides arm/disarm controls, and starts an
on-demand live view inside the popup. Live sessions stop when the popup closes
and are capped at five minutes to avoid leaving a camera streaming unnoticed.

## Install

Once this repository is published, install it directly through Omarchy Plugins
or with:

```sh
omarchy plugin add https://github.com/OWNER/omarchy-blink.git --enable
```

There is no manual Python setup. The plugin uses `uv` and its inline script
metadata to fetch and cache the pinned BlinkPy dependency on first use.

Click the bar icon, enter your Blink email and password, then enter the 2FA code
Blink sends you. The password is sent to the local helper over stdin and is
discarded after login. Refresh tokens are stored with user-only permissions at
`~/.local/state/omarchy-blink/credentials.json`.

## Privacy and security

- This project is not affiliated with Amazon, Blink, or Immedia.
- It uses BlinkPy, an unofficial client for Blink's private cloud API.
- The password never appears in process arguments and is not retained.
- Authentication data never lives inside the plugin or its Git repository.
- Selecting **Disconnect Blink** removes locally stored authentication data.
- The refresh interval is limited to at least 60 seconds to avoid excessive API calls.

## Requirements

- Omarchy 4 / Quattro shell
- `uv`
- Internet access to Blink and, on first use, Python package indexes

## Development

```sh
omarchy plugin validate .
qmllint -I /usr/share/omarchy/shell BarWidget.qml Panel.qml
uv run blink_helper.py status
```

## License

MIT
