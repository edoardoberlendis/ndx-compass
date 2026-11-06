"""Registro delle esclusioni dei diari prospettici (Fase 8A), SOLO LETTURA.

Una registrazione ufficiale ma temporalmente incoerente (per esempio scritta dopo la finestra della sua seduta) resta nel
diario esattamente com'è: origine, ora e versione non si toccano. Il file diary_exclusions.json (versionato in Git,
additivo) la elenca con il motivo, la data e la versione della decisione. Da qui la escludono, solo in lettura:
risultati prospettici, statistiche, dataset di validazione, confronti con la seduta precedente e alert.

Ogni registrazione è identificata da diario + seduta + versione del modello + ora di registrazione: le altre
registrazioni della stessa data restano ammissibili. Mai una registrazione sostitutiva retroattiva."""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(ROOT, "diary_exclusions.json")
DIARIES = {"opportunity": "runs", "investment": "inv_runs", "valuation": "val_runs", "etf": "etf_runs", "decision": "dec_runs"}
_cache = {"mtime": None, "data": None}


def load(path=None):
    """The registry ({"items": [...]}); an absent file means no exclusion."""
    p = path or FILE
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return {"schema": 1, "items": []}
    if path is None and _cache["mtime"] == mt:
        return _cache["data"]
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    for it in data.get("items", []):
        if it.get("diary") not in DIARIES:
            raise ValueError(f"esclusione con diario sconosciuto: {it.get('diary')}")
        for k in ("id", "session", "version", "computedAt", "reason", "decidedAt", "decisionVersion"):
            if not it.get(k):
                raise ValueError(f"esclusione {it.get('id')}: campo «{k}» mancante")
    if path is None:
        _cache.update(mtime=mt, data=data)
    return data


def items(diary=None):
    return [i for i in load().get("items", []) if diary is None or i["diary"] == diary]


def key(session, version, computed_at):
    return f"{session}|{version}|{computed_at}"


def is_excluded(diary, session, version, computed_at):
    return key(session, version, computed_at) in {key(i["session"], i["version"], i["computedAt"]) for i in items(diary)}


def sql(diary, alias="r"):
    """SQL condition (on a runs table with alias `alias`) that leaves out the excluded records of `diary`; "1" if none."""
    keys = sorted({key(i["session"], i["version"], i["computedAt"]) for i in items(diary)})
    if not keys:
        return "1"
    lits = ",".join("'" + k.replace("'", "''") + "'" for k in keys)
    return f"({alias}.session || '|' || {alias}.model_version || '|' || {alias}.computed_at) NOT IN ({lits})"
