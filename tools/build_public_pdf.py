"""Build the public copy of the CV PDF from the master LaTeX in Box.

The public copy drops the phone number from the header; the Box master is not changed.
Output: extra/Zavala_Victor_cv.pdf, served at https://vzavala.github.io/ZavalaCV/Zavala_Victor_cv.pdf

    python3 tools/build_public_pdf.py
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

CV_DIR = Path.home() / "Library/CloudStorage/Box-Box/ZAVALA_ADMIN/CV/Zavala_CV_tex/CURRENT"
OUT = Path(__file__).resolve().parent.parent / "extra" / "Zavala_Victor_cv.pdf"

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tex = (CV_DIR / "Zavala_Victor_cv.tex").read_text()
    tex, n = re.subn(r",\s*Phone:\s*[\d\s().-]+?(?=\s*\\\\)", "", tex)
    if n != 1:
        raise SystemExit("Phone number not found in the header; check the .tex before publishing")
    (tmp / "Zavala_Victor_cv.tex").write_text(tex)
    shutil.copy(CV_DIR / "MyPublicationsvz.bib", tmp)
    for f in CV_DIR.glob("*.sty"):
        shutil.copy(f, tmp)
    subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "-quiet", "Zavala_Victor_cv.tex"],
                   cwd=tmp, check=True, stdout=subprocess.DEVNULL)
    OUT.parent.mkdir(exist_ok=True)
    shutil.copy(tmp / "Zavala_Victor_cv.pdf", OUT)
print("wrote", OUT)
