# Tisztázások (1. lépés)

*Frissítve: 2026-11-26. Célközönség: ügyvéd. Állapot: részben kitöltve.*

## Adatbázis (Synology Postgres)

| Elem | Érték |
| --- | --- |
| Host | `192.168.1.70:5433` |
| Database | `noise` |
| Credential forrás | Működő: `../noise/apps/noise_web/.env` `DATABASE_URL` (a `database/.env` URL jelszava elavult volt) |
| Sémák | `noise_monitor`, `noise_report` |

### Fő táblák (riport szempontjából)

| Tábla | Időbélyeg | Tartalom |
| --- | --- | --- |
| `noise_monitor.sound_sample` | `measured_at` TIMESTAMPTZ | `level_db`, weighting/mode, quality_flags |
| `noise_monitor.fft_window` | `measured_at` | `spectrum_db REAL[]`, `metadata` JSONB (`dominant_hz`, …) |
| `noise_monitor.fft_band` | `measured_at` | 1/3 oktáv: `band_label`, `f_low_hz`/`f_high_hz`, `level_db` |
| `noise_report.minute_stat` | `measured_at` (perc) | `laeq_db`, L10/L50/L90, Lmax/Lmin, coverage |
| `noise_monitor.manual_observations` | `observed_at` | `heard` / `not_heard` |
| `noise_monitor.machine_events` | start/end | detektor események (referencia; offline újraszámolás a cél) |

Időzóna a riportban: **Europe/Budapest**; az extract intervallum félig nyitott `[start, end)`, UTC-ben tárolt időbélyegekkel.

Mintavétel: PeakTech `A5 0D` ≈ **20 Hz** → várható ~1200 minta/perc.

## Mérési időszak és célközönség

- Célközönség: **ügyvéd** (eldöntve).
- Archívumban elérhető időszak (ellenőrizve 2026-11-26): **2026-11-23 → 2026-11-26** (UTC hangminták). Riportpélda: `2026-11-25T12:00`–`13:00` helyi.
- Formai/tartalmi elvárások ügyvéddel: *TODO — egyeztetés.*

## Határértékek

Részletek: [`limits_27_2008.md`](limits_27_2008.md).  
Forrás: [27/2008. (XII. 3.) KvVM–EüM](https://net.jogtar.hu/jogszabaly?docid=a0800027.kvv) — üzemi zaj, **1. melléklet 1. pont**.

| Napszak | Helyi idő | Megítélési idő (2. § (2)) | L<sub>TH</sub> (kisvárosias lakó)* |
| --- | --- | --- | --- |
| Nappal | 06:00–22:00 | legnagyobb zajterhelésű folyamatos **8 óra** | **50 dB** |
| Éjszaka | 22:00–06:00 | legnagyobb zajterhelésű **fél óra** | **40 dB** |

\* Területi sor **megerősítve**: kisvárosias / kertvárosias lakóterület → 50 / 40 dB.  
A rendelet **L<sub>AM</sub>** megítélési szintet ír elő (korrekciókkal); a riport LAeq-je ehhez képest **semleges, nem jogi minősítés**.

## PeakTech 8005

Részletek: [`peaktech_8005.md`](peaktech_8005.md).  
Userguide: `/Users/andras/PycharmProjects/PeakTech_8005_09_2021_DE-EN.pdf`.

Módszertani megkötés (már rögzítve a mérőrendszerben): a PeakTech **nem natív integráló LAeq-mérő**; a riport energetikus LAeq-je a kijelzős dB mintákból számított saját metrika (`peaktech_display_energetic_v1`).
