"""PNG tEXt metadata embedding — equivalent of goclaw agent.EmbedPNGPrompt.

Embeds the prompt as a tEXt chunk with keyword "Description" so the
generated image carries its own provenance. tEXt chunk format (PNG spec):
  4 bytes length (big-endian, of data section)
  4 bytes type "tEXt"
  N bytes data: keyword + 0x00 + text (Latin-1)
  4 bytes CRC-32 of (type + data)

Inserted before the IEND chunk. Returns original bytes unchanged on any
malformed/non-PNG input.
"""

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def embed_prompt(data: bytes, prompt: str) -> bytes:
    """Insert a tEXt chunk with the prompt before IEND. Idempotent on errors."""
    if not prompt or not data or not data.startswith(PNG_SIGNATURE):
        return data

    try:
        # Walk chunks to find IEND offset.
        idx = len(PNG_SIGNATURE)
        iend_offset = -1
        while idx < len(data):
            if idx + 8 > len(data):
                return data
            (length,) = struct.unpack(">I", data[idx:idx + 4])
            chunk_type = data[idx + 4:idx + 8]
            if chunk_type == b"IEND":
                iend_offset = idx
                break
            # Skip: 4 length + 4 type + length data + 4 CRC
            idx += 12 + length

        if iend_offset < 0:
            return data

        keyword = b"Description"
        # tEXt is Latin-1 only per spec; encode best-effort.
        text = prompt.encode("latin-1", errors="replace")
        chunk_data = keyword + b"\x00" + text
        crc = zlib.crc32(b"tEXt" + chunk_data) & 0xFFFFFFFF
        chunk = (
            struct.pack(">I", len(chunk_data))
            + b"tEXt"
            + chunk_data
            + struct.pack(">I", crc)
        )
        return data[:iend_offset] + chunk + data[iend_offset:]
    except Exception:
        return data
