# noisereport

Felperesi **mérési napló** hőszivattyú-zajhoz: az elszenvedő fél saját mérései, ügyvédi tájékoztatásra.

- Nem szakértői vélemény, nem akkreditált jegyzőkönyv.
- A számok PeakTech kijelzős mintákból számított energetikus **LAeq** értékek; a rendelet **L_TH** irányértékével vannak összevetve (nem hitelesített L_AM).
- Offline pipeline: DB → Parquet pillanatkép → QC / mutatók / detektor → PDF.

Kapcsolódó mérőrendszer: a szomszédos `noise` monorepo (PostgreSQL archívum).

## Követelmények

- Python 3.12+, [`uv`](https://github.com/astral-sh/uv)
- macOS: WeasyPrinthez `brew install pango` (a `DYLD_FALLBACK_LIBRARY_PATH`-ot a kód induláskor beállítja)
- Olvasó `DATABASE_URL` a meglévő Postgreshez (csak SELECT; lásd `.env.example`)

## Telepítés

```bash
cd noisereport
cp .env.example .env   # állítsd be a DATABASE_URL-t
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
pytest
python -m src.db       # kapcsolat smoke-teszt
```

## Futtatás

Előtte: `source .venv/bin/activate`.

```bash
# 1) Extract: DB → snapshots/<start>_<end>/
python extract.py --start 2026-11-23T08:00 --end 2026-11-26T16:00

# 2) QC (opcionális)
python qc.py snapshots/<snap>

# 3) PDF meglévő snapshotból
python build_report.py --snapshot snapshots/<snap> --layout full
python build_report.py --snapshot snapshots/<snap> --layout thin

# Extract + PDF egy lépésben
python build_report.py --start 2026-11-23T08:00 --end 2026-11-26T16:00 --layout full
```

| Flag | Értékek | Megjegyzés |
|------|---------|------------|
| `--snapshot` | `snapshots/...` | Meglévő pillanatkép; nincs DB |
| `--start` / `--end` | helyi idő (Europe/Budapest) | Extract, ha nincs `--snapshot` |
| `--layout` | `thin` \| `full` | Rövid / részletes PDF (`config.yaml` default: `full`) |
| `--type` | `auto` \| `weekly` \| `monthly` \| `full` | Csak full: összefoglaló keret |

Kimenet: `output/report_<snap>/report.pdf` (+ HTML, ábrák).

**Extract:** alapból `sound_sample`, `fft_*`, `manual_observations`, `environment_sample` (nem húz `minute_stat` / `gps_fix`). Párhuzamos fetch (max 3), rendezés kliensen, per-tábla `query=` / `write=` időlog.

### PyCharm

| Konfig | Szerep |
|--------|--------|
| **build_report full** | Részletes PDF |
| **build_report thin** | Rövid PDF |

Run → *Edit Configurations…* → bal oldalon a konfig → jobb oldalon **Parameters**, pl.:

```text
--snapshot snapshots/20261123T070000Z_20261126T150000Z --layout full
```

Interpreter: projekt `.venv`. A WeasyPrint dylib path a kódban és a Run Environment variables-ben is be van állítva.

## Pipeline

```text
extract.py  →  snapshots/…/*.parquet + manifest (SHA-256)
build_report.py  →  mutatók, detektor, megítélési ablakok (8h nappal / 30min éjjel), PDF
```

Megítélési ablak: csak olyan 8 órás / 30 perces szakasz számít, amely **egészben** a nappali (06–22) vagy éjjeli (22–06) időszakba esik.

Konfig: [`config.yaml`](config.yaml) (határok, site, műszer, extract táblák).  
Detektorprofil: [`config/detector_1.1.0.yaml`](config/detector_1.1.0.yaml).

## Docs

| Fájl | Tartalom |
|------|----------|
| [`docs/limits_27_2008.md`](docs/limits_27_2008.md) | 27/2008 KvVM–EüM határ / megítélési idő |
| [`docs/clarifications.md`](docs/clarifications.md) | Adatmodell / metrika megkötések |
| [`docs/peaktech_8005.md`](docs/peaktech_8005.md) | Műszerjegyzetek |

Séma (mérőrendszer): `noise/database/schema.sql`.
