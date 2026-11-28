"""Generate lawyer-facing findings and claim–evidence rows from report metrics."""

from __future__ import annotations

from typing import Any


def resolve_summary_type(
    start_utc: str,
    end_utc: str,
    requested: str | None = None,
) -> str:
    """Return weekly | monthly | full from CLI request or period length."""
    if requested and requested != "auto":
        return requested
    import pandas as pd

    start = pd.Timestamp(start_utc)
    end = pd.Timestamp(end_utc)
    days = max((end - start).total_seconds() / 86400.0, 0.0)
    if days <= 8:
        return "weekly"
    if days <= 35:
        return "monthly"
    return "full"


def summary_type_label(summary_type: str) -> str:
    return {
        "weekly": "Heti összefoglaló",
        "monthly": "Havi összefoglaló",
        "full": "Teljes időszaki összefoglaló",
    }.get(summary_type, "Összefoglaló")


def build_findings(
    *,
    alert: dict[str, Any],
    analysis: dict[str, Any],
    day: dict[str, Any] | None,
    night: dict[str, Any] | None,
    day_limit: float,
    night_limit: float,
) -> list[dict[str, Any]]:
    """Build 4–5 main findings with claim–evidence links."""
    findings: list[dict[str, Any]] = []

    # 1) Regulatory exceedance (assessment windows preferred)
    assessment = list(analysis.get("assessment_rows") or [])
    over_assess = [r for r in assessment if r.get("is_over")]
    if over_assess:
        bits = []
        for r in over_assess:
            bits.append(
                f"{r['label']}: {r['max_laeq']:.1f} dB "
                f"(határ {int(r['limit_db'])} dB, "
                f"{r['max_exceedance_db']:+.1f} dB)"
            )
        findings.append(
            {
                "id": "F1",
                "claim": (
                    "A rendelet szerinti megítélési ablakokban a számított LAeq "
                    "a hivatkozott L_TH irányérték felett van "
                    "(mért összzaj, nem L_AM)."
                ),
                "detail": "; ".join(bits),
                "figure": "Fő rész: nappali/éjjeli 1 perces ábrák; § határérték",
                "table": "Összefoglaló összehasonlító doboz; melléklet: érzékenység",
                "annex": "Melléklet B — határérték-ablakok és érzékenység",
                "source": "sound_sample → LAeq; 27/2008 KvVM–EüM 2. § (2)",
            }
        )
    elif alert.get("over"):
        findings.append(
            {
                "id": "F1",
                "claim": (
                    "A mért időszakban a számított LAeq többször a hivatkozott "
                    "L_TH irányérték felett volt."
                ),
                "detail": " ".join(alert.get("bits") or []),
                "figure": "Fő rész: nappali/éjjeli 1 perces ábrák",
                "table": "Összefoglaló: megengedett vs mért",
                "annex": "Melléklet A — nappal / éjjel összesítők",
                "source": "sound_sample → percenkénti LAeq",
            }
        )
    else:
        findings.append(
            {
                "id": "F1",
                "claim": (
                    "Ebben a szeletben a számított átlagok a beállított "
                    "határértékek alatt maradtak."
                ),
                "detail": (
                    f"Nappal határ {int(day_limit)} dB, éjjel {int(night_limit)} dB."
                ),
                "figure": "Fő rész: nappali/éjjeli ábrák",
                "table": "Összefoglaló összehasonlító doboz",
                "annex": "Melléklet B",
                "source": "sound_sample → LAeq",
            }
        )

    # 2) Night levels
    if night and night.get("laeq_db") is not None:
        night_txt = (
            f"Éjjeli átlag {night['laeq_db']:.1f} dB "
            f"(megengedett {int(night_limit)} dB"
        )
        if night.get("exceedance_db") is not None:
            night_txt += f", {night['exceedance_db']:+.1f} dB"
        night_txt += ")."
        findings.append(
            {
                "id": "F2",
                "claim": (
                    "Éjjel (22–06) is a hivatkozott L_TH felett van a számított LAeq."
                    if night.get("over_limit")
                    else "Az éjjeli számított LAeq a hivatkozott L_TH-hoz képest értékelhető."
                ),
                "detail": night_txt,
                "figure": "Fő rész: éjjeli 1 perces ábra; üzemelési mintázat",
                "table": "Összefoglaló: éjjel sor",
                "annex": "Melléklet A — nappal / éjjel",
                "source": "sound_sample, Europe/Budapest 22–06",
            }
        )

    # 3) Machine runtime
    if analysis.get("enabled"):
        findings.append(
            {
                "id": "F3",
                "claim": (
                    f"A gép a mérési idő {analysis.get('on_ratio_pct', 0):.1f}%-ában "
                    f"üzemelt ({analysis.get('on_hours', 0):.1f} óra / "
                    f"{analysis.get('measure_hours', 0):.1f} óra; "
                    f"{analysis.get('event_count', 0)} szakasz)."
                ),
                "detail": (
                    "Az üzemállapot hangmintázatból (detektor) következtetett, "
                    "nem a gép saját naplójából."
                ),
                "figure": "Fő rész: üzemelési mintázat (dátum × óra)",
                "table": "Fő rész — üzemösszefoglaló",
                "annex": "—",
                "source": "offline detektor acoustic_hysteresis + sound/fft",
            }
        )

    # 4) Spectral fingerprint
    if analysis.get("spectrum_uri") or analysis.get("dominant_uri"):
        findings.append(
            {
                "id": "F4",
                "claim": (
                    "Az üzemnek jelölt szakaszokban észlelt hangkép eltér "
                    "a többi időszaktól (spektrum / domináns frekvencia)."
                ),
                "detail": (
                    "Összehasonlító megfigyelés; önmagában nem bizonyít okságot "
                    "és nem helyettesíti a dB–L_TH összevetést."
                ),
                "figure": "Fő rész: spektrum üzem vs nem üzem; domináns Hz",
                "table": "—",
                "annex": "Melléklet C — módszer / detektorparaméterek",
                "source": "fft_band, fft_window + detektált események",
            }
        )

    # 5) Sensitivity / robustness
    sens = list(analysis.get("sensitivity_assessment") or [])
    if sens:
        still = [r for r in sens if r.get("over_if_minus", 0) > 0]
        if still:
            worst = max(still, key=lambda r: abs(float(r.get("delta_db") or 0)))
            findings.append(
                {
                    "id": "F5",
                    "claim": (
                        "A túllépés a mérési bizonytalanság figyelembevételével "
                        "is fennmarad több megítélési ablakban."
                    ),
                    "detail": (
                        f"Példa: ha a mérés {int(worst['delta_db'])} dB-lel túl magas "
                        f"lenne, a(z) {worst['window_label']} ablakok "
                        f"{worst['over_if_minus']}/{worst['n']} "
                        f"({int(worst['pct_if_quieter'])}%) még akkor is "
                        f"határ felett maradna."
                    ),
                    "figure": "—",
                    "table": "Melléklet B — érzékenységi tábla",
                    "annex": "Melléklet B",
                    "source": "assessment ablakok ±1…±3 dB",
                }
            )
        else:
            findings.append(
                {
                    "id": "F5",
                    "claim": (
                        "Az érzékenységi vizsgálat szerint a bizonytalanság "
                        "befolyásolhatja a határ feletti ablakok arányát."
                    ),
                    "detail": "Részletek a melléklet érzékenységi táblájában.",
                    "figure": "—",
                    "table": "Melléklet B — érzékenységi tábla",
                    "annex": "Melléklet B",
                    "source": "assessment ablakok ±1…±3 dB",
                }
            )
    elif day is not None:
        findings.append(
            {
                "id": "F5",
                "claim": (
                    f"Nappali átlag {day.get('laeq_db', '—')} dB "
                    f"(határ {int(day_limit)} dB)."
                ),
                "detail": "Teljes nappali időszak energetikus átlaga.",
                "figure": "Fő rész: nappali ábra",
                "table": "Összefoglaló",
                "annex": "Melléklet A",
                "source": "sound_sample 06–22",
            }
        )

    return findings[:5]


GLOSSARY: list[dict[str, str]] = [
    {
        "term": "LAeq",
        "def": (
            "A-súlyozott egyenértékű hangnyomásszint: a változó zaj energetikus "
            "átlaga egy időszakra, dB-ben. A riportban a PeakTech kijelzős "
            "mintáiból számított érték."
        ),
    },
    {
        "term": "L90",
        "def": (
            "Az az A-súlyozott szint, amelyet az idő 90%-ában meghalad a jel "
            "(gyakran a háttérzaj közelítője). A riport percentilisekből számol."
        ),
    },
    {
        "term": "dBA",
        "def": (
            "A-súlyozott decibel: a fül érzékenységéhez igazított hangossági skála."
        ),
    },
    {
        "term": "1/3 oktávsáv",
        "def": (
            "A hang spektrumának frekvenciasávokra bontása; üzemnek jelölt vs. "
            "egyéb időszakok összehasonlítására."
        ),
    },
    {
        "term": "Tónusos zaj",
        "def": (
            "Olyan zaj, amelyben egy vagy több tiszta hang / keskeny sáv kiemelkedik. "
            "A spektrum és a domináns frekvencia ábrák ezt vizsgálják."
        ),
    },
    {
        "term": "Megítélési idő",
        "def": (
            "A 27/2008. KvVM–EüM szerint nappal a legzajosabb folyamatos 8 óra, "
            "éjjel a legzajosabb fél óra — ehhez viszonyítjuk a határt."
        ),
    },
]


LIMITATIONS: list[dict[str, str]] = [
    {
        "objection": "Hitelesítetlen / nem akkreditált műszer",
        "answer": (
            "A PeakTech 8005 Class 2 besorolása gyártói állítás, nem ellenőrzött; "
            "ebben a naplóban nincs hitelesített kalibrációs napló. A számok "
            "kijelzős mintákból számított LAeq-k. Az érzékenységi tábla (±1…±3 dB) "
            "az összevetés érzékenységét mutatja."
        ),
    },
    {
        "objection": "Következtetett üzemállapot (nem a gép naplója)",
        "answer": (
            "Az üzem/nem üzem hangmintázat alapján, detektorral és "
            "opcionálisan kézi megfigyelésekkel van dokumentálva. "
            "Ez nem a gyártó üzemnaplója, hanem akusztikai észlelés."
        ),
    },
    {
        "objection": "Mérőpont megválasztása",
        "answer": (
            "A mérés az érintett (elszenvedő) fél oldalán készült. "
            "Ez a napló a rögzített mérési lánc adatait foglalja össze."
        ),
    },
    {
        "objection": "Háttérzaj / más források",
        "answer": (
            "A spektrum és a domináns frekvencia üzem vs. nem üzem összevetése "
            "összehasonlító megfigyelés; önmagában nem bizonyít okságot. "
            "A L90 és a kikapcsolt szakaszok a háttér közelítésére szolgálnak."
        ),
    },
]
