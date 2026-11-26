# PeakTech 8005 — specifikáció kivonat

*Forrás: userguide PDF `PeakTech_8005_09_2021_DE-EN.pdf` (2021-09, DE/EN).*  
*A PDF jelenleg kép/scan jellegű; az alábbi mezők a meglévő `noise` dokumentációból és a Conrad/Voltcraft SL-451 rokonságból vannak előtöltve. Userguide-ból pontosítandó: osztály, tartomány, pontosság.*

## Ismert / megerősített (mérőrendszer)

| Mező | Érték | Forrás |
| --- | --- | --- |
| Típus | PeakTech 8005 hangszintmérő | eszköz |
| Osztály | Class 2 (állítva a rendszertervekben) | `noise` docs — userguide-ból ellenőrizendő |
| USB | CP210x, 9600 bps | `mqtt-peaktech-contract.md` |
| Keret | `A5 0D` → kijelzett dB (BCD × 0.1) | Mac USB validáció |
| Mintavétel | ≈ 20 Hz (FAST és SLOW) | Mac minták |
| Súlyozás | A / C (státusz tokenek) | firmware parser |
| Időállandó | FAST / SLOW | firmware parser |
| Tartomány parancs | LO / MED / HI / AUTO | MQTT `cmd/level` |
| Táp | 9 V DC | diy rendszerterv |
| AC OUT | frekvenciaanalízis (PCM1808) | diy rendszerterv |

## Userguide-ból kitöltendő

| Mező | Érték | Megjegyzés |
| --- | --- | --- |
| IEC / DIN hivatkozás | *TODO* | pl. IEC 61672 |
| Mérési tartomány (dB) | *TODO* | tipikusan 30–130 dB a rokon SL-451-nél |
| Pontosság / tolerancia | *TODO* | Class 2 tipikusan ±1,4 dB @ 1 kHz — userguide |
| Frekvenciatartomány | *TODO* | |
| Mikrofon | *TODO* | |
| Kalibrálás | *TODO* | |

## Riportbeli megfogalmazás

- A műszer **nem akkreditált laboratóriumi** méréshez hitelesített párhuzamos ellenőrzés nélkül.
- Az LAeq a riportban **számított** érték a kijelzős mintákból, nem a műszer belső integráló LAeq funkciója.
