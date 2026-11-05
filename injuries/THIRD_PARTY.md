# Third-party packages (injuries/)

Direct dependencies used by `injury_reports.py` and `pst_mirror.py` (requests). Licences read from each package's installed metadata on 2026-11-05.

| Package | Version | Licence | URL |
|---|---|---|---|
| pdfplumber | 0.11.10 | MIT | https://github.com/jsvine/pdfplumber |
| requests | 2.34.2 | Apache-2.0 | https://github.com/psf/requests |
| pytest | 9.2.0 | MIT | https://github.com/pytest-dev/pytest |

pdfplumber pulls in pdfminer.six (MIT, https://github.com/pdfminer/pdfminer.six), pypdfium2 (BSD-3-Clause or Apache-2.0, https://github.com/pypdfium2-team/pypdfium2) and Pillow (MIT-CMU, https://github.com/python-pillow/Pillow).

`nbainjuries` (MIT, https://github.com/mxufc29/nbainjuries) was evaluated and not used: it parses through tabula-py, which needs a Java runtime that this machine lacks.

requests pulls in urllib3 (MIT), idna (BSD-3-Clause), charset-normalizer (MIT) and certifi (MPL-2.0). None of these ship with the repository; the venv is gitignored.
