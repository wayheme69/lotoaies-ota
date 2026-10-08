#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
es_results.py — flux de la v4 de LOTO AI ES : es_results.json (08/10/2026)

  primitiva    : 30 derniers sorteos (6 números, complementario, reintegro) + premio réel
                 par acertante en Espagne pour chaque catégorie (« 6+R », « 6 », « 5+C »,
                 « 5 », « 4 », « 3 », « R ») et nombre d'acertantes.
  euromillones : 30 derniers sorteos + premio réel en Espagne par catégorie (13 catégories).

Source unique OFFICIELLE : SELAE /servicios/buscadorSorteos (champ « escrutinio »), via
r.jina.ai (Akamai bloque l'accès direct). Fusion avec le fichier déjà publié : un sorteo dont
le escrutinio arrive plus tard est complété au run suivant. Échec bruyant si le flux est
périmé (> 6 j). Le flux de la v3 (es_recent.json, update_es.py) n'est PAS touché.
"""
import json, os, re, subprocess, sys, time
from datetime import date, datetime, timedelta, timezone

FEED = "es_results.json"
KEEP = 30
MAX_STALE_DAYS = 6
BASE = "https://www.loteriasyapuestas.es/servicios/buscadorSorteos"
P_RE = re.compile(r"^\s*(\d{1,2}) - (\d{1,2}) - (\d{1,2}) - (\d{1,2}) - (\d{1,2}) - (\d{1,2}) C\((\d{1,2})\) R\((\d?)\)\s*$")
P_KEYS = {1: "6+R", 2: "6", 3: "5+C", 4: "5", 5: "4", 6: "3", 7: "R"}
EM_KEYS = ["5+2", "5+1", "5+0", "4+2", "4+1", "3+2", "4+0", "2+2", "3+1", "3+0", "1+2", "2+1", "2+0"]


def jina_get(url, tries=4):
    for i in range(tries):
        r = subprocess.run(["curl", "-s", "--max-time", "90", "-H", "X-Return-Format: text",
                            f"https://r.jina.ai/{url}"], capture_output=True, text=True, timeout=120)
        body = r.stdout.strip()
        if body.startswith("["):
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                pass
        print(f"  jina essai {i + 1}: {body[:80]!r}", file=sys.stderr)
        time.sleep(10 * (i + 1))
    raise SystemExit(f"jina: échec pour {url}")


def money(v):
    try:
        x = float(str(v).replace(".", "").replace(",", "."))
        return x if x > 0 else None
    except ValueError:
        return None


def rows(game, days=110):
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=days)
    return jina_get(f"{BASE}?game_id={game}&celebrados=true"
                    f"&fechaInicioInclusiva={start:%Y%m%d}&fechaFinInclusiva={end:%Y%m%d}")


def primitiva():
    out = []
    for row in rows("LAPR"):
        m = P_RE.match(row.get("combinacion") or "")
        if not m:
            raise SystemExit(f"LAPR combinacion illisible: {row.get('combinacion')!r}")
        nums = sorted(int(m.group(i)) for i in range(1, 7)); c = int(m.group(7)); r = m.group(8)
        d = str(row.get("fecha_sorteo", ""))[:10]
        if len(set(nums)) != 6 or not all(1 <= n <= 49 for n in nums) or not (1 <= c <= 49) or c in nums:
            raise SystemExit(f"LAPR {d}: valeurs invalides {nums} C{c}")
        pay, win = {}, {}
        for e in row.get("escrutinio") or []:
            k = P_KEYS.get(int(e.get("categoria", 0)))
            if not k:
                continue
            win[k] = int(str(e.get("ganadores", "0")).replace(".", "") or 0)
            v = money(e.get("premio"))
            if v is not None:
                pay[k] = v
        out.append({"date": d, "numbers": nums, "c": c, "r": int(r) if r != "" else None,
                    "payouts": pay or None, "winners": win or None})
    return out


def euromillones():
    out = []
    for row in rows("EMIL"):
        parts = [int(x) for x in re.findall(r"\d+", row.get("combinacion") or "")]
        d = str(row.get("fecha_sorteo", ""))[:10]
        if len(parts) != 7:
            raise SystemExit(f"EMIL {d}: combinacion illisible {row.get('combinacion')!r}")
        nums, stars = sorted(parts[:5]), sorted(parts[5:])
        if len(set(nums)) != 5 or not all(1 <= n <= 50 for n in nums) or len(set(stars)) != 2 or not all(1 <= s <= 12 for s in stars):
            raise SystemExit(f"EMIL {d}: valeurs invalides {nums}+{stars}")
        pay, win = {}, {}
        for e in row.get("escrutinio") or []:
            cat = int(e.get("categoria", 0))
            if not 1 <= cat <= 13:
                continue
            k = EM_KEYS[cat - 1]
            win[k] = int(str(e.get("ganadores", "0")).replace(".", "") or 0)
            v = money(e.get("premio"))
            # Bote non gagné : SELAE met 0 → pas de premio
            if v is not None and not (k == "5+2" and win[k] == 0):
                pay[k] = v
        out.append({"date": d, "numbers": nums, "stars": stars, "payouts": pay or None, "winners": win or None})
    return out


def merge(fresh, prev):
    by = {p["date"]: p for p in prev}
    for f in fresh:
        old = by.get(f["date"])
        if old and not f.get("payouts") and old.get("payouts"):
            f["payouts"], f["winners"] = old["payouts"], old["winners"]
        by[f["date"]] = f
    return sorted(by.values(), key=lambda x: x["date"], reverse=True)[:KEEP]


def main():
    prev = {}
    if os.path.exists(FEED):
        try:
            prev = json.load(open(FEED))
        except Exception as e:
            print("flux existant illisible:", e, file=sys.stderr)
    p = merge(primitiva(), prev.get("primitiva", []))
    time.sleep(4)
    e = merge(euromillones(), prev.get("euromillones", []))
    for name, lst in (("primitiva", p), ("euromillones", e)):
        if len(lst) < 10:
            raise SystemExit(f"FAIL: {name} seulement {len(lst)} sorteos")
        age = (date.today() - date.fromisoformat(lst[0]["date"])).days
        print(f"{name}: {len(lst)} sorteos, dernier {lst[0]['date']} ({age} j)", file=sys.stderr)
        if age > MAX_STALE_DAYS:
            raise SystemExit(f"FAIL: {name} périmé")
    new = {"primitiva": p, "euromillones": e}
    if new == {k: prev.get(k) for k in new}:
        print("Aucune nouvelle donnée.", file=sys.stderr); return
    json.dump({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), **new},
              open(FEED, "w"), ensure_ascii=False, indent=1)
    print("OK", file=sys.stderr)


if __name__ == "__main__":
    main()
