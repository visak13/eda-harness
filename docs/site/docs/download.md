# Download

{{ brand.product_name }} runs on Windows 10/11, macOS (Apple Silicon and Intel) and Ubuntu 24.04+ / Debian 13.
The macOS disk image is for Apple Silicon; on an Intel Mac, install with `install.sh` (cmd).
Pick the desktop app (GUI) or the command line (cmd): both install the same services and keep your board data in
your user profile, so a reinstall or an update never touches it.

<!-- heronry:downloads -->

## The installers are unsigned

The first release is **unsigned**, so your operating system warns you once. Here is what to click.

=== "Windows"

    1. Open `Heronry Desktop-<version>.msi`.
    2. SmartScreen shows **Windows protected your PC**: click **More info**, then **Run anyway**.
    3. Finish the installer. It installs for you only (no admin rights) and puts `{{ brand.cli_name }}` on your PATH.
    4. Start **{{ brand.desktop_app_name }}** from the Start menu. The setup wizard opens in its window.

    A downloaded script can also be unblocked with `Unblock-File .\install.ps1` before you run it.

=== "macOS"

    1. Open the DMG and drag **{{ brand.desktop_app_name }}** to Applications.
    2. Open it once. macOS says it cannot verify the developer: click **Done**.
    3. Go to **System Settings → Privacy & Security**, scroll to **Security** and click **Open Anyway**.
       (macOS 15 Sequoia removed the old Control-click → Open shortcut.)
    4. Open {{ brand.desktop_app_name }} again and confirm **Open**. The setup wizard opens in its window.

=== "Linux"

    1. `sudo apt install ./heronry_*.deb` — apt pulls in the GTK, WebKit and AppIndicator packages it needs.
    2. Start **{{ brand.desktop_app_name }}** from your app menu. The setup wizard opens in its window.

There is no AppImage or Flatpak build: the desktop window needs the system's WebKit, and a sandboxed app could
not reach the agent command-line tools your seats run.

## Check a download

Every release carries a `SHA256SUMS` file and build-provenance attestations.

```sh
sha256sum -c SHA256SUMS --ignore-missing
gh attestation verify <file> -R {{ brand.repo_slug }}
```

The first proves the file is the one the release lists; the second proves this repository's release workflow
built it. Neither replaces code signing, so the warnings above still appear.

## Next

Follow the [setup guide](setup/index.md), or read how [updates](docs/updates.md) work.
