# noisereport

Önálló, offline riport-pipeline hőszivattyú zajméréshez.  
Csak **olvasó** kapcsolat a meglévő Synology PostgreSQL archívumhoz; a mutatók a hash-elt Parquet pillanatképen számolódnak.

Kapcsolódó mérőrendszer: [`../noise`](../noise).

## Környezet

```bash
cd /Users/andras/PycharmProjects/noisereport
# DATABASE_URL: másold a működő ../noise/apps/noise_web/.env-ből
cp .env.example .env   # majd állítsd be a DATABASE_URL-t
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

# WeasyPrint (macOS): brew install pango
# DYLD_FALLBACK_LIBRARY_PATH: a build_report / src.report induláskor beállítja (.venv + Homebrew)

pytest
python -m src.db
```

## Futtatási lehetőségek

### 1. Terminál (CLI)

Előtte (egyszer): `source .venv/bin/activate`. A WeasyPrint dylib pathot a kód induláskor beállítja.

```bash
# Extract (DB → Parquet snapshot)
python extract.py --start 2026-11-23T08:00 --end 2026-11-26T16:00

# QC a snapshoton
python qc.py snapshots/<snap>

# PDF meglévő snapshotból
python build_report.py --snapshot snapshots/<snap> --layout full
python build_report.py --snapshot snapshots/<snap> --layout thin

# Extract + PDF egy lépésben (DB kell)
python build_report.py --start 2026-11-23T08:00 --end 2026-11-26T16:00 --layout full
```

| Flag | Értékek | Megjegyzés |
|------|---------|------------|
| `--snapshot` | `snapshots/...` | Meglévő pillanatkép; nincs DB-hívás |
| `--start` / `--end` | helyi idő | Extract, ha nincs `--snapshot` |
| `--layout` | `thin` \| `full` | Vékony napi / teljes (ügyvédi) PDF; default: `config.yaml` → `full` |
| `--type` | `auto` \| `weekly` \| `monthly` \| `full` | Csak full layout összefoglaló kerete |

Kimenet: `output/report_<snap>/report.pdf` (+ HTML).

### 2. PyCharm Run/Debug

Kész konfigurációk a projektben:

| Konfig | Mit csinál |
|--------|------------|
| **build_report full** | Teljes PDF a Parameters-ben megadott snapshotból |
| **build_report thin** | Vékony PDF ugyanezzel |

**Hol a Parameters?**  
Run → *Edit Configurations…* → bal oldalon válaszd a konfigot → **jobb oldalon** a *Parameters* mező.  
Példa:

```text
--snapshot snapshots/20261123T070000Z_20261126T150000Z --layout full
```

Más időszakra cseréld a `snapshots/...` mappanevet. Az interpreter a `.venv`; `DYLD_FALLBACK_LIBRARY_PATH` a konfig Environment variables-ében és a kódban is be van állítva.

- **Interpreter:** Settings → Project → Python Interpreter → `.venv` (nem kell `source .venv`).
- **Terminal a PyCharmban:** Settings → Tools → Terminal → *Activate virtualenv*.

## Állapot

- [x] Scaffold + smoke pytest
- [x] Extract + SHA-256 (reprodukálható)
- [x] QC
- [x] LAeq / percentilisek + tesztek
- [x] Vékony napi PDF
- [x] Offline üzemészlelés (`detect.py`, profil `config/detector_1.1.0.yaml`)
- [x] Rendszeresség / spektrum / határérték (PDF elemző fejezetek)

## Források

- PeakTech 8005 userguide: `../PeakTech_8005_09_2021_DE-EN.pdf`
- DB credential (működő): `../noise/apps/noise_web/.env`
- Séma: `../noise/database/schema.sql`
