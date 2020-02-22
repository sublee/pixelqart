import base64
import io
import os
from concurrent.futures import ThreadPoolExecutor
from random import getrandbits, randrange
from threading import Event
from urllib.parse import parse_qs, quote, urlparse

import requests
from PIL import Image
from pyzbar.pyzbar import decode


def upload_image(filename: str) -> str:
    with open(filename, 'rb') as f:
        r = requests.post('https://research.swtch.com/qr/draw?upload=1',
                          files={'image': f}, allow_redirects=False)
    assert r.status_code == 302
    qs = parse_qs(urlparse(r.headers['Location']).query)
    return qs['i'][0]


def search_qrcode(href: str,
                  uploaded_image_id: str,
                  necessary: Image.Image,
                  filename: str,
                  found: Event,
                  ) -> None:
    """Finds a QR Code including a pixel-art. A found QR Code must include the
    necessary part.
    """
    while True:
        # https://github.com/rsc/swtch/blob/master/qrweb/play.go#L145
        url = ('https://research.swtch.com/qr/draw?x=0&y=0&c=0&'
               f'i={uploaded_image_id}&'
               'v=6&'  # QR Code version (v6 generates 41x41)
               'r=1&'  # Random Pixels
               'd=0&'  # Data Pixels Only
               't=0&'  # Dither (not implemented)
               'z=0&'  # Scale of source image
               f'u={quote(href, safe="")}&'
               f'm={randrange(8)}&'    # Mask pattern (0-7)
               f'o={randrange(4)}&'    # Rotation (0-3)
               f's={getrandbits(32)}'  # Random seed (int64)
               )

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
            canvas.save(filename)
            print(filename, url)
            found.set()
            break

        if found.is_set():
            # Another thread has found.
            break


def main(href: str,
         desired_filename: str,
         necessary_filename: str,
         concurrency: int,
         ) -> None:
    os.makedirs('found/', exist_ok=True)

    desired = Image.open(desired_filename)
    necessary = Image.open(necessary_filename)
    assert desired.size == (41, 41), desired.size
    assert necessary.size == (41, 41), necessary.size

    desired.close()
    uploaded_image_id = upload_image(desired_filename)

    found = Event()
    ex = ThreadPoolExecutor()
    for i in range(concurrency):
        ex.submit(search_qrcode,
                  href, uploaded_image_id, necessary,
                  filename=f'found/{i}.png', found=found)

    try:
        found.wait()
    except KeyboardInterrupt:
        print('shutting down...')
    finally:
        found.set()
        ex.shutdown()
        necessary.close()


if __name__ == '__main__':
    main('https://subl.ee/', 'desired.png', 'necessary.png', concurrency=16)
