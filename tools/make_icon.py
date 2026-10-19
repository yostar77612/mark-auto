"""Generate the MarkAuto multi-size ICO deterministically, offline (stdlib only)."""

from pathlib import Path
import struct
import zlib


SIZES = (16, 24, 32, 48, 64, 128, 256)
POINTS = ((0.23, 0.66), (0.40, 0.49), (0.53, 0.57), (0.77, 0.31))


def _chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def _distance(x, y, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    t = max(0, min(1, ((x - start[0]) * dx + (y - start[1]) * dy) / (dx * dx + dy * dy)))
    return ((x - start[0] - t * dx) ** 2 + (y - start[1] - t * dy) ** 2) ** 0.5


def _png(size):
    rows = bytearray()
    for row in range(size):
        rows.append(0)  # PNG filter: none
        for col in range(size):
            covered = white = 0
            for sy in range(4):
                for sx in range(4):
                    x, y = (col + (sx + 0.5) / 4) / size, (row + (sy + 0.5) / 4) / size
                    # Rounded square inset by 4%, with a 17% corner radius.
                    dx, dy = max(0.21 - x, 0, x - 0.79), max(0.21 - y, 0, y - 0.79)
                    if dx * dx + dy * dy <= 0.17**2:
                        covered += 1
                        white += min(_distance(x, y, a, b) for a, b in zip(POINTS, POINTS[1:])) <= 0.035
            if covered:
                rows.extend(round((base * (covered - white) + 255 * white) / covered) for base in (30, 100, 210))
                rows.append(round(255 * covered / 16))
            else:
                rows.extend((0, 0, 0, 0))
    header = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', header) + _chunk(b'IDAT', zlib.compress(bytes(rows), 9)) + _chunk(b'IEND', b'')


def make_icon():
    images = [_png(size) for size in SIZES]
    offset = 6 + 16 * len(SIZES)
    entries = bytearray()
    for size, data in zip(SIZES, images):
        entries.extend(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    return struct.pack('<HHH', 0, 1, len(SIZES)) + entries + b''.join(images)


if __name__ == '__main__':
    target = Path(__file__).resolve().parents[1] / 'packaging/markauto.ico'
    target.write_bytes(make_icon())
    print(f'Generated {target.name}: {target.stat().st_size} bytes; sizes {SIZES}')
