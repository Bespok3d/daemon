# Bespok3d daemon

The on-printer service for the [Bespok3d](https://github.com/Bespok3d) plugin manager. It is the one
piece that runs on the printer itself; everything else (the desktop app, the adapter, the plugins)
talks to it.

## What it does

- Installs, updates, reconfigures, and removes plugins from `.b3` packages.
- Reports the printer's capabilities and firmware to the app.
- Refuses any operation that would restart a service while a print is running or paused.
- Self-heals: when a plugin breaks Klipper or Moonraker, it attributes the failure to that plugin and
  deactivates only that one, so the printer is never left unusable (this is also what makes a firmware
  OTA safe: a plugin that breaks against new firmware peels itself off until a fixed version ships).
- Streams live install progress and print state to the app over authenticated websockets.

## How it gets onto the printer

It is "plugin zero": the snapmaker-u1 adapter bootstraps it over SSH at enrollment (deploy the files,
generate a self-signed cert, seed the access-control list, start it), not through the normal plugin
install pipeline. Every request is `Authorization: Bearer <token>` over cert-pinned HTTPS on port
4269. That is why this package's `install` block is empty: the adapter installs it specially.

## Security

Bearer-token auth on every route except the single unauthenticated `POST /access/request` (how a
second computer asks for access, then an already-authorized client approves it). Package signatures
are verified app-side before install, not on the printer: the constrained 512MB board cannot carry
on-printer GPG, so bearer-token auth over cert-pinned HTTPS plus app-side verification is the trust
model.
