"""The shared 0x03-framed JSON codec used by both printer-service clients."""
import json

from core.printer_comms import frame


def test_encode_appends_the_etx_terminator() -> None:
    raw = frame.encode({"method": "info", "id": 1})

    assert raw.endswith(frame.ETX)
    assert json.loads(raw[:-1].decode()) == {"method": "info", "id": 1}
