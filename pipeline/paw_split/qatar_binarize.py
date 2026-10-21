"""Black text ink of an app page image (coloured frame and verse rings dropped) -> ink-NNN.pbm."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, QATAR_APP_ASSETS, workdir  # noqa: E402
workdir('qatar-attach')

import sys

import cv2
import numpy as np

PAGE = int(sys.argv[1])
APP = QATAR_APP_ASSETS
img = cv2.imread(f'{APP}/pages/page-{PAGE:03d}.webp', cv2.IMREAD_COLOR)   # read in place, no copy
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
t, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
ink = (gray < t) & (hsv[..., 1] < 90)
cv2.imwrite(f'ink-{PAGE:03d}.pbm', np.where(ink, 0, 255).astype(np.uint8))
print('page', PAGE, 'size', img.shape[:2], 'otsu', t)
