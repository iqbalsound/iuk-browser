# Translating IUK Browser

All user-visible text goes through `tr("English text")`. Catalogs live in `src/iuk_browser/i18n/<lang>.json` and are
generated from one table: `tools/translations.tsv` (`English | ur | ar | fr | es | de | zh_CN`).

* Fix or improve a translation: edit the cell in `tools/translations.tsv`, run `python tools/make_catalogs.py`, commit
  both files. The script fails if a string is missing or a `{}` placeholder is lost; CI runs the same check.
* Add a string in the code: write `tr("New text")`, then add a row to the table (the check tells you which rows are missing).
* Add a language: add a column, add the code to `LANGS` in `tools/make_catalogs.py` and `src/iuk_browser/i18n.py`
  (and to `RTL` if it is right-to-left).

The six shipped translations were written by an AI model and have **not** been reviewed by native speakers; please
review them (especially the long security messages) before relying on them.
