#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_es.py — met à jour es_recent.json (La Primitiva) pour LOTO AI ES.

SELAE (loteriasyapuestas.es) est derrière Akamai qui bloque TOUTES les IP
datacenter (403) — y compris les runners GitHub. Contournement documenté :
r.jina.ai avec X-Return-Format: text renvoie le JSON brut de l'API.

Sorties :
  es_recent.json  {"updated", "next": {"date","jackpot_eur"}, "draws":[...12 derniers]}

ÉCHEC BRUYANT (leçon UK) : toute anomalie => exit 1, le workflow échoue
visiblement au lieu de publier un flux vide/corrompu.
"""
import json
import re
import subprocess
import sys
from datetime import date, timedelta, datetime, timezone

BASE = "https://www.loteriasyapuestas.es/servicios"
COMBO_RE = re.compile(
    r"^\s*(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})\s*"
    r"C\((\d{1,2})\)\s*R\((\d?)\)\s*$")


def jina_get(url, tries=4):
    for attempt in range(tries):
        r = subprocess.run(
            ["curl", "-s", "--max-time", "60",
             "-H", "X-Return-Format: text",
             f"https://r.jina.ai/{url}"],
            capture_output=True, text=True, timeout=80)
        body = r.stdout.strip()
        if body.startswith("[") or body.startswith("{"):
            return json.loads(body)
        print(f"  jina essai {attempt + 1}: réponse non-JSON ({body[:80]!r})", file=sys.stderr)
    raise SystemExit(f"jina: échec après {tries} essais pour {url}")


def fetch_recent(days=45):
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=days)
    url = (f"{BASE}/buscadorSorteos?game_id=LAPR&celebrados=true"
           f"&fechaInicioInclusiva={start:%Y%m%d}&fechaFinInclusiva={end:%Y%m%d}")
    rows = jina_get(url)
    if not isinstance(rows, list) or not rows:
        raise SystemExit("buscadorSorteos: réponse vide")
    draws = []
    for row in rows:
        combo = row.get("combinacion") or ""
        m = COMBO_RE.match(combo)
        if not m:
            raise SystemExit(f"combinacion illisible: {combo!r}")
        nums = sorted(int(m.group(i)) for i in range(1, 7))
        c, r_str = int(m.group(7)), m.group(8)
        d = str(row.get("fecha_sorteo", ""))[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise SystemExit(f"fecha_sorteo illisible: {row.get('fecha_sorteo')!r}")
        if len(set(nums)) != 6 or not all(1 <= n <= 49 for n in nums):
            raise SystemExit(f"mains invalides: {nums}")
        if not (1 <= c <= 49) or c in nums:
            raise SystemExit(f"complementario invalide: C{c} vs {nums}")
        if not r_str:
            raise SystemExit(f"reintegro absent sur un tirage moderne: {combo!r}")
        draws.append({"date": d, "numbers": nums, "c": c, "r": int(r_str)})
    draws.sort(key=lambda x: x["date"], reverse=True)
    if len(draws) < 6:
        raise SystemExit(f"seulement {len(draws)} tirages sur {days} j — anormal pour 3/semaine")
    return draws[:12]


def fetch_next():
    rows = jina_get(f"{BASE}/proximosv3?game_id=LAPR&num=1")
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    d = str(row.get("fecha", ""))[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        return None
    out = {"date": d}
    bote = row.get("premio_bote")
    if bote and str(bote).isdigit() and int(bote) > 0:
        out["jackpot_eur"] = int(bote)
    return out


draws = fetch_recent()
nxt = fetch_next()
payload = {
    "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "draws": draws,
}
if nxt:
    payload["next"] = nxt
with open("es_recent.json", "w") as f:
    json.dump(payload, f, ensure_ascii=False, indent=1)
print(f"OK: {len(draws)} tirages, dernier {draws[0]['date']} {draws[0]['numbers']} "
      f"C{draws[0]['c']} R{draws[0]['r']}; next={nxt}", file=sys.stderr)
