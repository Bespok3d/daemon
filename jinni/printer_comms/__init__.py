"""Communication with the printer's own running services.

The jinni is the daemon's device-side half, and talking to the OTHER software running on the printer
is part of the device's realm. This room holds those clients: `klippy` and `moonraker` reach
Klipper's and Moonraker's auth-free Unix sockets over the shared 0x03-framed JSON protocol in
`frame`. Consumers import the submodule they need (`from jinni.printer_comms import klippy`).
"""
