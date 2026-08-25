Download the build for your computer.

**Windows** — `PiTrac-Easy-Connect-windows.zip`. Extract the dedicated
`PiTrac Easy-Connect` folder as a unit. Do not copy the executable out of that
folder. Windows may warn that it does not recognise the program; choose
**More info**, then **Run anyway**.

**macOS** — use `PiTrac-Easy-Connect-macos-apple-silicon.zip` for an M1 or
later Mac, or `PiTrac-Easy-Connect-macos-intel.zip` for a real Intel Mac.
Extract and move the complete `.app`, then right-click it and choose **Open**
the first time.

**Linux x86-64** — install WebKitGTK 4.1, extract the dedicated
`PiTrac Easy-Connect` directory, and run the executable inside it. Keep the
directory together.

### Checking what you downloaded

Every release file is covered by GitHub build provenance and `SHA256SUMS.txt`.
For example:

```
gh attestation verify PiTrac-Easy-Connect-windows.zip --repo TylerPardun/pitrac-easy-connect
```

This provenance is not a paid Windows or Apple code-signing certificate, so
the first-launch platform warnings described above still apply.
