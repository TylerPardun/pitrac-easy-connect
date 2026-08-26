Download the build for your computer.

**Windows** — download and run
`PiTrac-Easy-Connect-windows-setup.exe`. The installer puts the complete app
in its supported per-user location and adds Desktop and Start-menu shortcuts.
Do **not** download `PiTrac-Easy-Connect-windows.zip`; it is an internal payload
for automatic updates, not the installer. Windows may warn that it does not
recognise the program; choose **More info**, then **Run anyway**.

**macOS** — use `PiTrac-Easy-Connect-macos-apple-silicon.zip` for an M1 or
later Mac, or `PiTrac-Easy-Connect-macos-intel.zip` for a real Intel Mac.
Extract and move the complete `.app`, then right-click it and choose **Open**
the first time.

### Checking what you downloaded

Every release file is covered by GitHub build provenance and `SHA256SUMS.txt`.
For example:

```
gh attestation verify PiTrac-Easy-Connect-windows-setup.exe --repo TylerPardun/pitrac-easy-connect
```

This provenance is not a paid Windows or Apple code-signing certificate, so
the first-launch platform warnings described above still apply.
