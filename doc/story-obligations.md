# Story obligations

What the on-printer daemon owes the user stories.

The stories themselves live in one place, in the app repo, under `Bespok3d-desktop/doc/stories/`. This
page lists only the rows this repo has to deliver. Nothing here is a second copy of a
story: it is the obligation, and the story is the source.

| Story | Owner | What this repo has to deliver |
| --- | --- | --- |
| `Bespok3d-desktop/doc/stories/catalog-and-install/install-plugin.md` (Install a plugin on a printer) | daemon | download the package, verify its signature, unpack it, apply the Klipper config and restart the affected services |
| `Bespok3d-desktop/doc/stories/catalog-and-install/signature-verification.md` (Require GPG signature verification) | daemon | refuse a package whose signature does not verify while the setting is on, and carry the setting across restarts |
| `Bespok3d-desktop/doc/stories/identity-and-trust/assign-key-to-printer.md` (Assign a signing key to a printer) | app | update its access-control list when the owner assigns a different key to the printer |
| `Bespok3d-desktop/doc/stories/printer-lifecycle/add.md` (Add a printer) | adapters | be deployed, started and reachable at the end of enrollment, and refuse a second enrollment of a fingerprint it already holds |
| `Bespok3d-desktop/doc/stories/printer-lifecycle/deactivate-bespok3d.md` (Deactivate Bespok3d on a printer) | app | deactivate every plugin on request and leave the files in place |
| `Bespok3d-desktop/doc/stories/printer-lifecycle/discover.md` (Discover a printer) | app | advertise itself over mDNS so the app can find a managed printer without a port probe |
| `Bespok3d-desktop/doc/stories/printer-lifecycle/enroll-status.md` (Printer enrollment status) | app | answer the health probe on port 4269 so the app can tell managed from online |
| `Bespok3d-desktop/doc/stories/printer-lifecycle/reactivate-bespok3d.md` (Reactivate Bespok3d on a printer) | app | re-apply plugins in dependency order when recovery is called |
| `Bespok3d-desktop/doc/stories/printer-lifecycle/uninstall-bespok3d.md` (Uninstall Bespok3d from a printer) | adapters | uninstall every plugin and remove the config hooks it added |
