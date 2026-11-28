"""Generate findings and claim–evidence rows from report metrics."""

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
        "weekly": "Időszaki összefoglaló",
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
    """Build main findings with claim–evidence links (plain language)."""
    findings: list[dict[str, Any]] = []
    assessment = list(analysis.get("assessment_rows") or [])
    day_row = next((r for r in assessment if r.get("window") == "8h_day"), None)
    night_row = next((r for r in assessment if r.get("window") == "30min_night"), None)
    sens = list(analysis.get("sensitivity_assessment") or [])

    def _sens_for(window_key: str, delta: float = 3.0) -> dict | None:
        matches = [
            r
            for r in sens
            if r.get("window") == window_key and float(r.get("delta_db") or 0) == delta
        ]
        return matches[0] if matches else None

    # Night assessment — preferred lead finding when over
    if night_row and night_row.get("max_laeq") is not None:
        night_sens = _sens_for("30min")
        robust = bool(
            night_sens
            and night_sens.get("n")
            and night_sens.get("over_if_minus", 0) == night_sens.get("n")
        )
        if night_row.get("is_over"):
            detail = (
                f"A legzajosabb éjjeli fél órában {night_row['max_laeq']:.1f} dB "
                f"(irányérték {int(night_limit)} dB, "
                f"{night_row['max_exceedance_db']:+.1f} dB)."
            )
            if analysis.get("quietest_night_window_db") is not None:
                detail += (
                    f" Az éjjeli félórás ablakok közül a leghalkabb is "
                    f"{analysis['quietest_night_window_db']:.1f} dB volt."
                )
            if robust and night_sens:
                detail += (
                    f" Ha a mérés 3 dB-lel túl magas lenne, mind a "
                    f"{night_sens['n']} éjjeli ablak irányérték felett maradna."
                )
            findings.append(
                {
                    "id": "F1",
                    "claim": (
                        "Éjjel a mért zaj a rendelet szerinti irányérték felett van "
                        "— ez a robusztusabb megállapítás."
                        if robust
                        else "Éjjel a mért zaj a rendelet szerinti irányérték felett van."
                    ),
                    "detail": detail,
                    "figure": "Fő rész: éjjeli ábra; éjszakai irányérték-eltérés",
                    "table": "Összefoglaló; melléklet: érzékenység",
                    "annex": "Melléklet B",
                    "source": "megítélési ablak 30 perc, 22–06",
                }
            )
        else:
            findings.append(
                {
                    "id": "F1",
                    "claim": "Éjjel a számított zaj az irányérték alatt / körül maradt.",
                    "detail": (
                        f"Legzajosabb éjjeli fél óra: {night_row['max_laeq']:.1f} dB "
                        f"(irányérték {int(night_limit)} dB)."
                    ),
                    "figure": "Fő rész: éjjeli ábra",
                    "table": "Összefoglaló",
                    "annex": "Melléklet A",
                    "source": "megítélési ablak 30 perc",
                }
            )

    # Day assessment — separate, note marginal robustness
    if day_row and day_row.get("max_laeq") is not None:
        day_sens = _sens_for("8h")
        marginal = bool(
            day_sens
            and day_sens.get("n")
            and day_sens.get("over_if_minus", 0) == 0
            and day_row.get("is_over")
        )
        if day_row.get("is_over"):
            detail = (
                f"A legzajosabb nappali 8 órában {day_row['max_laeq']:.1f} dB "
                f"(irányérték {int(day_limit)} dB, "
                f"{day_row['max_exceedance_db']:+.1f} dB)."
            )
            if marginal and day_sens:
                detail += (
                    " 3 dB mérési bizonytalanság mellett a nappali 8 órás ablakok "
                    f"közül egyik sem maradna irányérték felett "
                    f"(0/{day_sens['n']}) — a nappali eltérés nem robusztus."
                )
            findings.append(
                {
                    "id": "F2",
                    "claim": (
                        "Nappal a mért zaj csak kis mértékben van az irányérték felett "
                        "(nem robusztus 3 dB bizonytalanság mellett)."
                        if marginal
                        else "Nappal a mért zaj a rendelet szerinti irányérték felett van."
                    ),
                    "detail": detail,
                    "figure": "Fő rész: nappali ábra",
                    "table": "Összefoglaló; melléklet: érzékenység",
                    "annex": "Melléklet B",
                    "source": "megítélési ablak 8 óra, 06–22",
                }
            )
        else:
            findings.append(
                {
                    "id": "F2",
                    "claim": "Nappal a számított zaj az irányérték alatt / körül maradt.",
                    "detail": (
                        f"Legzajosabb nappali 8 óra: {day_row['max_laeq']:.1f} dB "
                        f"(irányérték {int(day_limit)} dB)."
                    ),
                    "figure": "Fő rész: nappali ábra",
                    "table": "Összefoglaló",
                    "annex": "Melléklet A",
                    "source": "megítélési ablak 8 óra",
                }
            )

    if not findings and alert.get("over"):
        findings.append(
            {
                "id": "F1",
                "claim": (
                    "A mért időszakban a zaj többször a rendelet szerinti "
                    "irányérték felett volt."
                ),
                "detail": " ".join(alert.get("bits") or []),
                "figure": "Fő rész: nappali/éjjeli ábrák",
                "table": "Összefoglaló",
                "annex": "Melléklet A",
                "source": "percenkénti zajszint",
            }
        )

    # Machine runtime
    if analysis.get("enabled"):
        findings.append(
            {
                "id": "F3",
                "claim": (
                    f"A gép az érvényes mérési idő "
                    f"{analysis.get('on_ratio_pct', 0):.1f}%-ában járt "
                    f"({analysis.get('on_hm', '—')} / "
                    f"{analysis.get('valid_measure_hm', analysis.get('measure_hm', '—'))}; "
                    f"{analysis.get('event_count', 0)} szakasz)."
                ),
                "detail": (
                    f"Lebontás: nappal {analysis.get('on_day_hm', '—')}, "
                    f"éjjel {analysis.get('on_night_hm', '—')} "
                    f"(összesen = a zajtábla „Gép jár” sorai). "
                    "Az üzemállapot hangmintázatból (detektor) következtetett; "
                    "az arány csak az adatot tartalmazó időre vonatkozik."
                ),
                "figure": "Fő rész: üzemelési mintázat",
                "table": "Fő rész — üzemösszefoglaló",
                "annex": "—",
                "source": "detektor + hangminta",
            }
        )

    # Spectrum — cautious
    if analysis.get("spectrum_uri") or analysis.get("dominant_uri"):
        findings.append(
            {
                "id": "F4",
                "claim": (
                    "A „gép jár” szakaszokban a hangkép eltér a többi időszaktól "
                    "(összehasonlítás, nem forrásbizonyíték önmagában)."
                ),
                "detail": (
                    "A különbség részben várható, ha a detektor a hangosabb "
                    "időszakokat jelöli. A spektrum relatív skálán van; "
                    "50 Hz környéke hálózati zümmögés lehet."
                ),
                "figure": "Fő rész: hangkép-ábrák",
                "table": "Gép jár / nem jár zajtábla",
                "annex": "Melléklet C — módszer",
                "source": "FFT + detektált szakaszok",
            }
        )

    # On/off comparison if present
    if analysis.get("on_off_rows"):
        findings.append(
            {
                "id": "F5",
                "claim": (
                    "Gép járáskor és kikapcsoltnak jelölt időszakban a mért "
                    "átlagos zaj és a háttérközeli szint összevethető."
                ),
                "detail": (
                    "Lásd a „Gép jár / nem jár” táblát (nappal és éjjel). "
                    "Ez összzaj, nem a gép egyedüli hozzájárulása."
                ),
                "figure": "—",
                "table": "Gép jár / nem jár",
                "annex": "—",
                "source": "hangminta × detektor",
            }
        )

    return findings[:6]


GLOSSARY: list[dict[str, str]] = [
    {
        "term": "LAeq",
        "def": (
            "Energetikus átlagos zajszint (A-súlyozott). Ebben a naplóban a "
            "műszer kijelzős mintáiból számított érték, nem hitelesített laboratóriumi LAeq."
        ),
    },
    {
        "term": "L_TH / irányérték",
        "def": (
            "A 27/2008. KvVM–EüM rendelet szerinti zajterhelési irányérték "
            "(pl. nappal 50 / éjjel 40 dB lakóterületen). Nem azonos a hivatalos L_AM "
            "megítélési szinttel."
        ),
    },
    {
        "term": "dB (A)",
        "def": (
            "A-súlyozott decibel: a fül érzékenységéhez igazított hangossági skála."
        ),
    },
    {
        "term": "1/3 oktávsáv",
        "def": (
            "A hang spektrumának frekvenciasávokra bontása; gép jár vs nem jár "
            "összehasonlítására (relatív szint)."
        ),
    },
    {
        "term": "Megítélési idő",
        "def": (
            "A rendelet szerint nappal a legzajosabb folyamatos 8 óra, "
            "éjjel a legzajosabb fél óra — ehhez viszonyítjuk az irányértéket."
        ),
    },
]


LIMITATIONS: list[dict[str, str]] = [
    {
        "objection": "Hitelesítetlen / nem akkreditált műszer",
        "answer": (
            "A PeakTech 8005 Class 2 besorolása gyártói állítás, nem ellenőrzött; "
            "ebben a naplóban nincs hitelesített kalibrációs napló. A számok "
            "kijelzős mintákból számított átlagok. Az érzékenységi tábla (±1…±3 dB) "
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
            "A gép jár / nem jár tábla és a hangkép-összehasonlítás "
            "összehasonlító megfigyelés; önmagában nem bizonyít okságot. "
            "A háttérközeli szint (L90) közelítés."
        ),
    },
]
