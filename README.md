# Victor M. Zavala — CV Navigator

A browsable version of my curriculum vitae, split into short pages by section.

**View it online:** https://vzavala.github.io/ZavalaCV/

## Updating

The pages are generated from the LaTeX CV (`Zavala_Victor_cv.tex` and `MyPublicationsvz.bib`); the full PDF is linked from Box. After editing and compiling the CV:

```bash
python tools/build_site.py          # regenerate the pages from the CV
jupyter-book build .                # optional: preview locally in _build/html
git add -A && git commit -m "Update CV" && git push
```

Pushing to `main` rebuilds and deploys the site with GitHub Actions.
