"""Generate the app icon for both platforms from one drawing.

Kept as code rather than a checked-in binary so the mark can be adjusted and
every size regenerates consistently. The design has to survive being 16 pixels
wide in a taskbar, so it is a ball and its flight and nothing else.
"""

import pathlib
import sys

from PIL import Image, ImageDraw

GROUND = (12, 18, 16, 255)      # the same near-black the app uses
BALL = (223, 248, 109, 255)     # PiTrac lime
ARC = (93, 220, 147, 255)       # PiTrac green
SIZE = 1024


def draw(size: int = SIZE) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas = ImageDraw.Draw(image)
    unit = size / 1024

    # A rounded square, so it sits correctly in both docks.
    canvas.rounded_rectangle(
        [(0, 0), (size - 1, size - 1)], radius=int(200 * unit), fill=GROUND
    )

    # The flight: a rising arc, thinning as it climbs, drawn as a run of dots so
    # it stays clean at every size instead of relying on line joins.
    points = 30
    for index in range(points):
        t = index / (points - 1)
        x = 205 * unit + t * 470 * unit
        y = 800 * unit - (t * 430 * unit) + (t * t * 105 * unit)
        radius = (34 - 15 * t) * unit
        alpha = int(120 + 120 * t)
        canvas.ellipse(
            [(x - radius, y - radius), (x + radius, y + radius)],
            fill=ARC[:3] + (alpha,),
        )

    # The ball, at the end of the flight.
    centre_x, centre_y, ball = 716 * unit, 316 * unit, 114 * unit
    canvas.ellipse(
        [(centre_x - ball, centre_y - ball), (centre_x + ball, centre_y + ball)], fill=BALL
    )
    # Two dimples, enough to read as a golf ball without turning to mush small.
    for offset_x, offset_y, dimple in ((-36, -26, 18), (30, 22, 15)):
        canvas.ellipse(
            [
                (centre_x + offset_x * unit - dimple * unit, centre_y + offset_y * unit - dimple * unit),
                (centre_x + offset_x * unit + dimple * unit, centre_y + offset_y * unit + dimple * unit),
            ],
            fill=(190, 214, 88, 255),
        )
    return image


def main(out: pathlib.Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    master = draw()
    master.save(out / "icon.png")

    # Windows .ico carries several sizes in one file.
    master.save(
        out / "PiTrac.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    # macOS wants an iconset directory, which iconutil turns into .icns.
    iconset = out / "PiTrac.iconset"
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        master.resize((size, size), Image.LANCZOS).save(iconset / "icon_{0}x{0}.png".format(size))
        master.resize((size * 2, size * 2), Image.LANCZOS).save(
            iconset / "icon_{0}x{0}@2x.png".format(size)
        )
    print("wrote {} and {}".format(out / "PiTrac.ico", iconset))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "packaging/icon")))
