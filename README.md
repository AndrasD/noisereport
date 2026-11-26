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
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib

pytest
python -m src.db
python extract.py --start 2026-11-25T12:00 --end 2026-11-25T13:00
python qc.py snapshots/<snap>
python build_report.py --snapshot snapshots/<snap>
# vagy: python build_report.py --start ... --end ...
```

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
