import base64
import io
import itertools
import os
import random
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Tuple
from urllib.parse import parse_qs, quote, urlparse

import requests
from PIL import Image
from pyzbar.pyzbar import decode

QRCODE_SIZE = (41, 41)  # QR Code v6
QART_MARGIN = 4


def split_design(filename: str) -> Tuple[Image.Image, Image.Image]:
    NECESSARY_WHITE = (0, 255, 255, 255)  # cyan
    NECESSARY_BLACK = (255, 0, 255, 255)  # magenta

    desired = Image.new('RGBA', QRCODE_SIZE)
    necessary = Image.new('RGBA', QRCODE_SIZE)

    desired_pixels = desired.load()
    necessary_pixels = necessary.load()

    with Image.open(filename) as img:
        assert img.mode == 'RGBA'
        assert img.size == QRCODE_SIZE, img.size

        pixels = img.load()

        for x, y in itertools.product(range(img.size[0]), range(img.size[1])):
            if pixels[x, y] == NECESSARY_WHITE:
                desired_pixels[x, y] = (255, 255, 255, 255)
                necessary_pixels[x, y] = (255, 255, 255, 255)
            elif pixels[x, y] == NECESSARY_BLACK:
                desired_pixels[x, y] = (0, 0, 0, 255)
                necessary_pixels[x, y] = (0, 0, 0, 255)
            else:
                desired_pixels[x, y] = pixels[x, y]

    return desired, necessary


def upload_image(filename: str) -> str:
    with open(filename, 'rb') as f:
        r = requests.post('https://research.swtch.com/qr/draw?upload=1',
                          files={'image': f}, allow_redirects=False)
    assert r.status_code == 302
    qs = parse_qs(urlparse(r.headers['Location']).query)
    return qs['i'][0]


def search_qrcode(name: str,
                  href: str,
                  uploaded_image_id: str,
                  necessary: Image.Image,
                  found: Event,
                  ) -> None:
    """Finds a QR Code including a pixel-art. A found QR Code must include the
    necessary part.
    """
    while True:
        mask = random.randrange(8)
        orient = random.randrange(4)
        seed = random.getrandbits(32)

        # https://github.com/rsc/swtch/blob/master/qrweb/play.go#L145
        url = ('https://research.swtch.com/qr/draw?x=0&y=0&c=0&'
               f'i={uploaded_image_id}&'
               'v=6&'  # QR Code version (v6 generates 41x41)
               'r=1&'  # Random Pixels
               'd=0&'  # Data Pixels Only
               't=0&'  # Dither (not implemented)
               'z=0&'  # Scale of source image
               f'u={quote(href, safe="")}&'
               f'm={mask}&'    # Mask pattern (0-7)
               f'o={orient}&'  # Rotation (0-3)
               f's={seed}'     # Random seed (int64)
               )
        print(f'Trying: {url}')

        # Generate a basic QR Code by QArt: https://research.swtch.com/qr/draw
        r = requests.get(url)
        _, data, *_ = r.content.decode().split('"')
        assert data.startswith('data:image/png;base64,')

        data = data[len('data:image/png;base64,'):]
        qrcode = Image.open(io.BytesIO(base64.b64decode(data)))

        # The essential size of the QR Code is 49x49 (41x41 + margin 4px) but
        # it is scaled up 4 times.
        assert qrcode.size == (196, 196)

        # Paste the necessary part.
        canvas = Image.new('RGBA', (49, 49), (0, 0, 0, 0))
        canvas.paste(qrcode.resize((49, 49)))            # scale down 4 times
        canvas.paste(necessary, (4, 4), mask=necessary)  # (4, 4): margin 4px

        # Try to decode the QR Code with bigger size.
        info = decode(canvas.resize((196, 196)))

        if info:
            # Found!
            filename = f'{name}.m{mask}o{orient}s{seed}.png'
            canvas.save(filename)
            print(f'Found: {filename}, {url}')
            found.set()
            break

        if found.is_set():
            # Another thread has found.
            break


def main(href: str,
         design_filename: str,
         concurrency: int,
         ) -> None:
    name, png = os.path.splitext(os.path.basename(design_filename))
    assert png.lower() == '.png'

    desired, necessary = split_design(design_filename)

    with desired, tempfile.NamedTemporaryFile() as f:
        desired.save(f, format='PNG')
        uploaded_image_id = upload_image(f.name)

    found = Event()
    ex = ThreadPoolExecutor()
    for i in range(concurrency):
        ex.submit(search_qrcode,
                  name, href, uploaded_image_id, necessary, found)

    try:
        found.wait()
    except KeyboardInterrupt:
        print('shutting down...')
    finally:
        found.set()
        ex.shutdown()
        necessary.close()


if __name__ == '__main__':
    main('https://subl.ee?▣', 'griffith2020.png', concurrency=16)
