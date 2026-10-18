"""Alertas de posible VENTA: impulso alcista fuerte + acumulación en la parte alta (velas 15m).

Uso:
    python3 detector.py            -> revisa y avisa (lo corre GitHub Actions cada 15 min)
    python3 detector.py test       -> manda un mensaje de prueba (email y/o Telegram)
    python3 detector.py backtest   -> alertas de los últimos ~7 días (rápido)
    python3 detector.py historico  -> análisis de DIAS días (por defecto 365): CSV + resumen
    python3 detector.py estabilidad -> compara 1ª y 2ª mitad del histórico (sin gastar créditos de datos)
    python3 detector.py confirmacion -> analiza la entrada al romper el piso de la acumulación (velas de 5m)
"""
import csv
import bisect
import json
import math
import os
import random
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

SYMBOLS = ["XAU/USD"]  # luego añadimos: "USD/CAD", "BTC/USD", ...
INTERVAL = "15min"
CANDLE_MIN = 15

# ---- Parámetros del patrón ----
ATR_PERIOD = 48
IMPULSE_ATR = 6.0
IMPULSE_LOOKBACK = 24
ACC_MIN, ACC_MAX = 5, 12
ACC_MAX_FRAC = 0.45
HOLD_FRAC = 0.50
NEAR_PEAK_FRAC = 0.25
FREE_ATR = 4.0
PEAK_FRESH = 3

# ---- Resultado, riesgo y filtros ----
HORIZON_H = 12                 # horas que se vigila cada alerta
HORIZON = HORIZON_H * 60 // CANDLE_MIN
SPREAD = {"XAU/USD": 0.30}     # spread aproximado en precio (ajústalo a tu broker)
SL_BUFFER_ATR = 0.25           # colchón sobre el máximo para el SL
REF_TP_ATR = 1.5               # "éxito" de referencia: baja 1.5 ATR antes de tocar el SL sobre el máximo
VIERNES_CORTE_NY = 14          # no se cuentan alertas del viernes desde esta hora de Nueva York (None = sin filtro)
SETUP_GAP = 32                 # alertas a menos de 32 velas (8 h) = mismo setup

# Sesiones generales: (zona horaria, apertura, cierre) en minutos desde medianoche local
SESIONES = {
    "Asia": ("Asia/Tokyo", 9 * 60, 18 * 60),
    "Londres": ("Europe/London", 8 * 60, 16 * 60 + 30),
    "Nueva York": ("America/New_York", 8 * 60, 17 * 60),
}

STATE_FILE = "state.json"
DATA_DIR = os.environ.get("DATA_DIR", "datos")

SL_NAMES = ["máx", "acum", "1ATR", "1.5ATR"]
TP_NAMES = ["1ATR", "1.5ATR", "2ATR", "3ATR", "r50", "r100"]
REF = ("máx", f"{REF_TP_ATR:g}ATR")

FIELDS = [
    "simbolo", "vela_t", "dia", "setup", "viernes_tarde", "sesion", "min_apertura", "horas_fuera",
    "precio", "peak", "base", "acc_hi", "acc_lo", "atr", "impulso", "impulso_atr", "acc_len",
    "acc_frac", "libre_atr", "eff", "mechas", "alcistas", "deriva_atr", "vel_imp_atr",
    "riesgo_pts", "riesgo_atr", "estado", "exito_ref", "exito_r50", "fill_max_pct",
    "mae_ref_atr", "mi_resultado", "comentario",
]


# ------------------------------------------------------------------ datos
def _parse(values):
    out = []
    for v in values:
        t = datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        out.append({"t": t, "o": float(v["open"]), "h": float(v["high"]),
                    "l": float(v["low"]), "c": float(v["close"])})
    return out


def api(symbol, size, end_date=None, interval=None):
    params = {"symbol": symbol, "interval": interval or INTERVAL, "outputsize": size,
              "timezone": "UTC", "apikey": os.environ["TWELVEDATA_KEY"]}
    if end_date:
        params["end_date"] = end_date
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"https://api.twelvedata.com/time_series?{q}", timeout=60) as r:
        data = json.load(r)
    if data.get("status") == "error" or "values" not in data:
        raise RuntimeError(f"Twelve Data ({symbol}): {data.get('message', data)}")
    return _parse(data["values"])


def _quitar_vela_abierta(c, minutos=CANDLE_MIN):
    if c and c[-1]["t"] + timedelta(minutes=minutos) > datetime.now(timezone.utc):
        c.pop()
    return c


def fetch(symbol, size=120):
    c = sorted(api(symbol, size), key=lambda x: x["t"])
    return _quitar_vela_abierta(c)


def fetch_historial(symbol, dias, interval=None, minutos=CANDLE_MIN):
    todas = {}
    end = None
    for _ in range(60):
        try:
            lote = api(symbol, 5000, end, interval)
        except RuntimeError as e:
            if todas:
                print(f"Aviso: el historial se corta aquí ({e})")
                break
            raise
        nuevos = [x for x in lote if x["t"] not in todas]
        if not lote or not nuevos:
            break
        for x in lote:
            todas[x["t"]] = x
        mas_viejo = min(x["t"] for x in lote)
        if (datetime.now(timezone.utc) - mas_viejo).days >= dias:
            break
        end = (mas_viejo - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        time.sleep(8)  # el plan gratis permite 8 llamadas por minuto
    corte = datetime.now(timezone.utc) - timedelta(days=dias)
    c = sorted((x for x in todas.values() if x["t"] >= corte), key=lambda x: x["t"])
    return _quitar_vela_abierta(c, minutos)


# ------------------------------------------------------------------ patrón
def atr(c, period=ATR_PERIOD):
    c = c[-(period + 1):]
    if len(c) < period + 1:
        return None
    trs = [max(c[i]["h"] - c[i]["l"],
               abs(c[i]["h"] - c[i - 1]["c"]),
               abs(c[i]["l"] - c[i - 1]["c"])) for i in range(1, len(c))]
    return sum(trs) / period


def detect(c):
    """Devuelve un dict con la señal si el final de `c` cumple el patrón, o None."""
    a = atr(c)
    if not a:
        return None
    n = len(c)
    for acc in range(ACC_MIN, ACC_MAX + 1):
        if n < acc + IMPULSE_LOOKBACK:
            break
        win = c[n - acc:]
        pre = c[n - acc - IMPULSE_LOOKBACK:n - acc]
        zone = pre + win
        peak_i = max(range(len(zone)), key=lambda i: zone[i]["h"])
        if peak_i == 0 or peak_i < len(pre) - PEAK_FRESH:
            continue
        peak = zone[peak_i]["h"]
        base_i = min(range(peak_i), key=lambda i: zone[i]["l"])
        base = zone[base_i]["l"]
        impulse = peak - base
        acc_hi = max(x["h"] for x in win)
        acc_lo = min(x["l"] for x in win)
        price = c[-1]["c"]
        if not (impulse >= IMPULSE_ATR * a
                and acc_hi - acc_lo <= ACC_MAX_FRAC * impulse
                and acc_lo >= base + HOLD_FRAC * impulse
                and peak - acc_hi <= NEAR_PEAK_FRAC * impulse
                and acc_lo - base >= FREE_ATR * a
                and price >= acc_lo):
            continue
        # --- características de calidad (para el análisis) ---
        imp = zone[base_i:peak_i + 1]
        rangos = [x["h"] - x["l"] for x in imp]
        suma_r = sum(rangos) or 1e-9
        cuerpos = [abs(x["c"] - x["o"]) for x in imp]
        cl = [x["c"] for x in win]
        k = len(cl)
        mx, my = (k - 1) / 2, sum(cl) / k
        var = sum((i - mx) ** 2 for i in range(k)) or 1e-9
        pend = sum((i - mx) * (cl[i] - my) for i in range(k)) / var
        return {
            "key": zone[peak_i]["t"].isoformat(), "vela_t": c[-1]["t"],
            "acc": acc, "atr": a, "impulse": impulse, "base": base, "peak": peak,
            "acc_hi": acc_hi, "acc_lo": acc_lo, "price": price,
            "acc_body_lo": min(min(x["o"], x["c"]) for x in win),
            "frac": (acc_hi - acc_lo) / impulse,
            "eff": impulse / suma_r,
            "mechas": (suma_r - sum(cuerpos)) / suma_r,
            "alcistas": sum(1 for x in imp if x["c"] > x["o"]) / len(imp),
            "deriva": pend * (k - 1) / a,
            "vel_imp": impulse / len(imp) / a,
            "libre_atr": (acc_lo - base) / a,
        }
    return None


# ------------------------------------------------------------------ sesiones y filtros
def sesion_info(t):
    dentro, fuera = [], []
    for nombre, (tz, ap, ci) in SESIONES.items():
        loc = t.astimezone(ZoneInfo(tz))
        m = loc.hour * 60 + loc.minute
        if ap <= m < ci:
            dentro.append((m - ap, nombre))
        else:
            fuera.append((m - ci) % 1440)
    if dentro:
        dentro.sort()
        return {"sesion": "+".join(n for _, n in dentro), "min_apertura": dentro[0][0], "horas_fuera": 0.0}
    return {"sesion": "Fuera", "min_apertura": "", "horas_fuera": round(min(fuera) / 60, 1)}


def viernes_tarde(t):
    if VIERNES_CORTE_NY is None:
        return False
    ny = t.astimezone(ZoneInfo("America/New_York"))
    return ny.weekday() == 4 and ny.hour >= VIERNES_CORTE_NY


def enriquecer(s):
    t = s["vela_t"] + timedelta(minutes=CANDLE_MIN)  # hora en que se cerró la vela (momento de la alerta)
    s["ses"] = sesion_info(t)
    s["tarde"] = viernes_tarde(t)
    s["sl"] = s["peak"] + SL_BUFFER_ATR * s["atr"]
    return s


# ------------------------------------------------------------------ resultados
def simular(fut, entry, sl, tp, spread):
    """Venta: devuelve (resultado, R, velas) o None. Si SL y TP caen en la misma vela, gana el SL."""
    if not fut or sl <= entry or tp >= entry:
        return None
    riesgo = sl - entry
    for k, x in enumerate(fut):
        if x["h"] + spread >= sl:
            return ("SL", -1.0, k)
        if x["l"] + spread <= tp:
            return ("TP", (entry - tp) / riesgo, k)
    return ("T", (entry - (fut[-1]["c"] + spread)) / riesgo, len(fut))


def evaluar(s, fut, spread):
    entry, a, peak, imp = s["price"], s["atr"], s["peak"], s["impulse"]
    sls = {"máx": peak + SL_BUFFER_ATR * a, "acum": s["acc_hi"] + SL_BUFFER_ATR * a,
           "1ATR": entry + a, "1.5ATR": entry + 1.5 * a}
    tps = {"1ATR": entry - a, "1.5ATR": entry - 1.5 * a, "2ATR": entry - 2 * a,
           "3ATR": entry - 3 * a, "r50": peak - 0.5 * imp, "r100": s["base"]}
    combos = {(sn, tn): simular(fut, entry, sl, tp, spread)
              for sn, sl in sls.items() for tn, tp in tps.items()}
    ref = combos[REF]
    minl = entry
    for x in fut:
        if x["h"] > peak:
            break
        minl = min(minl, x["l"])
    fill = max(0.0, (peak - minl) / imp)
    mae = None
    if ref and ref[0] == "TP":
        mae = (max(x["h"] for x in fut[:ref[2] + 1]) - entry) / a
    return {
        "exito_ref": 1 if (ref and ref[0] == "TP") else 0,
        "exito_r50": 1 if fill >= 0.5 else 0,
        "fill_max_pct": round(fill * 100, 1),
        "mae_ref_atr": None if mae is None else round(mae, 2),
        "riesgo_pts": round(sls["máx"] - entry, 2),
        "riesgo_atr": round((sls["máx"] - entry) / a, 2),
        "combos": combos,
    }


def futuro(c, idx, vela_t):
    """Velas posteriores a c[idx] dentro del horizonte de vigilancia."""
    limite = vela_t + timedelta(minutes=CANDLE_MIN + HORIZON_H * 60)
    return [x for x in c[idx + 1: idx + 1 + HORIZON] if x["t"] < limite]


def generar_alertas(c):
    alertas, vistos = [], set()
    ini = ATR_PERIOD + IMPULSE_LOOKBACK + ACC_MAX + 2
    for i in range(ini, len(c) + 1):
        s = detect(c[max(0, i - 120):i])
        if s and s["key"] not in vistos:
            vistos.add(s["key"])
            enriquecer(s)
            s["i"] = i - 1  # índice de la vela de la alerta en c
            alertas.append(s)
    prev, setup = None, 0
    for s in alertas:
        if prev is None or s["i"] - prev > SETUP_GAP:
            setup += 1
        s["setup"] = setup
        prev = s["i"]
    return alertas


def fila_csv(sym, s, ev):
    t = s["vela_t"]
    f = {
        "simbolo": sym, "vela_t": t.strftime("%Y-%m-%d %H:%M"), "dia": t.strftime("%a"),
        "setup": s.get("setup", ""), "viernes_tarde": int(s["tarde"]),
        "sesion": s["ses"]["sesion"], "min_apertura": s["ses"]["min_apertura"],
        "horas_fuera": s["ses"]["horas_fuera"], "precio": round(s["price"], 3),
        "peak": round(s["peak"], 3), "base": round(s["base"], 3),
        "acc_hi": round(s["acc_hi"], 3), "acc_lo": round(s["acc_lo"], 3),
        "atr": round(s["atr"], 3), "impulso": round(s["impulse"], 3),
        "impulso_atr": round(s["impulse"] / s["atr"], 2), "acc_len": s["acc"],
        "acc_frac": round(s["frac"], 3), "libre_atr": round(s["libre_atr"], 2),
        "eff": round(s["eff"], 3), "mechas": round(s["mechas"], 3),
        "alcistas": round(s["alcistas"], 3), "deriva_atr": round(s["deriva"], 2),
        "vel_imp_atr": round(s["vel_imp"], 3),
        "riesgo_pts": round(s["sl"] - s["price"], 2),
        "riesgo_atr": round((s["sl"] - s["price"]) / s["atr"], 2),
        "estado": "pendiente", "exito_ref": "", "exito_r50": "", "fill_max_pct": "",
        "mae_ref_atr": "", "mi_resultado": "", "comentario": "",
    }
    if ev is not None:
        f.update({"estado": "ok", "exito_ref": ev["exito_ref"], "exito_r50": ev["exito_r50"],
                  "fill_max_pct": ev["fill_max_pct"],
                  "mae_ref_atr": "" if ev["mae_ref_atr"] is None else ev["mae_ref_atr"]})
    return f


# ------------------------------------------------------------------ resumen
def _med(v):
    v = sorted(v)
    return v[len(v) // 2] if v else 0.0


def _q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))] if v else 0.0


def _tasa(w, n):
    if not n:
        return "–"
    p = w / n
    return f"{100 * p:.0f}%" + ("⚠" if n < 30 else "")


def _tabla(cab, filas):
    cols = list(zip(cab, *filas))
    an = [max(len(str(x)) for x in col) for col in cols]
    lin = ["  ".join(str(x).ljust(w) for x, w in zip(cab, an))]
    lin += ["  ".join(str(x).ljust(w) for x, w in zip(r, an)) for r in filas]
    return "```\n" + "\n".join(lin) + "\n```"


def _grupos(items, clave, orden=None):
    g = defaultdict(lambda: [0, 0])
    for it in items:
        k = clave(it)
        if k is None:
            continue
        g[k][0] += 1
        g[k][1] += it["ev"]["exito_ref"]
    ks = orden or sorted(g)
    return [[str(k), g[k][0], _tasa(g[k][1], g[k][0])] for k in ks if k in g]


def _combo_stats(items, sn, tn):
    rs = [it["ev"]["combos"][(sn, tn)] for it in items if it["ev"]["combos"][(sn, tn)]]
    if not rs:
        return 0, 0, 0.0
    return len(rs), sum(1 for r in rs if r[0] == "TP"), sum(r[1] for r in rs) / len(rs)


def aleatorio(c, spread, n=3000):
    rnd = random.Random(7)
    idx = list(range(120, len(c) - HORIZON - 1))
    res = defaultdict(list)
    for j in rnd.sample(idx, min(n, len(idx))):
        a = atr(c[max(0, j - 100):j + 1])
        if not a:
            continue
        entry = c[j]["c"]
        fut = futuro(c, j, c[j]["t"])
        for sn, sd in (("1ATR", 1.0), ("1.5ATR", 1.5)):
            for tn, td in (("1ATR", 1.0), ("1.5ATR", 1.5), ("2ATR", 2.0), ("3ATR", 3.0)):
                r = simular(fut, entry, entry + sd * a, entry - td * a, spread)
                if r:
                    res[(sn, tn)].append(r)
    return res


def resumen(sym, c, alertas, items, spread):
    ok = [it for it in items if not it["s"]["tarde"]]
    tarde = len(items) - len(ok)
    pend = len(alertas) - len(items)
    primeras, vistos = [], set()
    for it in ok:
        if it["s"]["setup"] not in vistos:
            vistos.add(it["s"]["setup"])
            primeras.append(it)
    L = [f"# {sym} 15m — análisis {c[0]['t']:%Y-%m-%d} a {c[-1]['t']:%Y-%m-%d}", "",
         f"- Velas: {len(c)} | alertas detectadas: {len(alertas)} | evaluadas: {len(ok)} "
         f"(en {len(vistos)} setups) | viernes tarde excluidas: {tarde} | pendientes: {pend}",
         f"- ⚠ = menos de 30 casos (poco fiable). Spread usado: {spread}. Horizonte: {HORIZON_H} h.", ""]
    if len(ok) < 5:
        L.append("Muy pocas alertas para sacar estadísticas. Prueba con más días o parámetros más flexibles.")
        return "\n".join(L)

    def exito(lst, campo):
        return _tasa(sum(it["ev"][campo] for it in lst), len(lst))

    L += ["## Resultado general", "",
          f"Éxito = baja {REF_TP_ATR:g} ATR desde la alerta antes de tocar tu SL (sobre el máximo + {SL_BUFFER_ATR:g} ATR).", "",
          _tabla(["Medida", "Todas", "1ª de cada setup"],
                 [["Éxito (ref.)", f"{exito(ok, 'exito_ref')} n={len(ok)}", f"{exito(primeras, 'exito_ref')} n={len(primeras)}"],
                  ["Rellena ≥50% sin romper máx.", exito(ok, "exito_r50"), exito(primeras, "exito_r50")]]), ""]

    rp = [it["ev"]["riesgo_pts"] for it in ok]
    ra = [it["ev"]["riesgo_atr"] for it in ok]
    mae = [it["ev"]["mae_ref_atr"] for it in ok if it["ev"]["mae_ref_atr"] is not None]
    L += ["## Tu SL (sobre el máximo de la subida)", "",
          f"- Riesgo mediano: {_med(rp):.1f} pts ({_med(ra):.1f} ATR); el 25% más cercano {_q(rp, .25):.1f} pts; el 75%, {_q(rp, .75):.1f} pts."]
    if mae:
        L.append(f"- En las que sí cumplieron, el precio subió en contra como máximo (ATR): mediana {_med(mae):.1f}, "
                 f"p75 {_q(mae, .75):.1f}, p90 {_q(mae, .9):.1f}, máx {max(mae):.1f}. "
                 f"Si el SL va bastante más lejos que el p90, hay margen para acercarlo.")
    L.append("")

    nombres = {"máx": "SL máx", "acum": "SL acum", "1ATR": "SL 1ATR", "1.5ATR": "SL 1.5ATR"}
    fw, fr = [], []
    for sn in SL_NAMES:
        rw, rr = [nombres[sn]], [nombres[sn]]
        for tn in TP_NAMES:
            n, w, avg = _combo_stats(ok, sn, tn)
            rw.append(_tasa(w, n))
            rr.append(f"{avg:+.2f}" if n else "–")
        fw.append(rw)
        fr.append(rr)
    cab = [""] + [f"TP {t}" for t in TP_NAMES]
    L += ["## SL × TP: % de aciertos", "", _tabla(cab, fw), "",
          "## SL × TP: ganancia promedio por operación (en R; 1R = lo que arriesgas)", "", _tabla(cab, fr), "",
          "r50/r100 = rellenar 50% / 100% de la subida. Lo que importa es la ganancia en R, no solo el % de aciertos.", ""]

    base = aleatorio(c, spread)
    filas = []
    for sn in ("1ATR", "1.5ATR"):
        for tn in ("1ATR", "2ATR", "3ATR"):
            n, w, avg = _combo_stats(ok, sn, tn)
            rs = base.get((sn, tn), [])
            bw = sum(1 for r in rs if r[0] == "TP")
            bavg = sum(r[1] for r in rs) / len(rs) if rs else 0.0
            filas.append([f"SL {sn} / TP {tn}", _tasa(w, n), f"{avg:+.2f}", _tasa(bw, len(rs)), f"{bavg:+.2f}"])
    L += ["## ¿Mejor que vender al azar?", "",
          _tabla(["Combinación", "Alertas %", "R prom.", "Azar %", "R prom."], filas),
          "Si las alertas no superan al azar en estas combinaciones, el patrón por sí solo no aporta ventaja.", ""]

    ordenes = ["Asia", "Londres", "Nueva York"]
    L += ["## Éxito (ref.) por contexto", ""]
    ses = _grupos(ok, lambda it: it["s"]["ses"]["sesion"])
    L += ["Por sesión (solape = dos abiertas):", _tabla(["Sesión", "n", "Éxito"], ses), ""]
    dias = _grupos(ok, lambda it: it["s"]["vela_t"].strftime("%a"), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sun"])
    L += ["Por día:", _tabla(["Día", "n", "Éxito"], dias), ""]
    bloques = _grupos(ok, lambda it: f"{(it['s']['vela_t'].hour // 4) * 4:02d}-{(it['s']['vela_t'].hour // 4) * 4 + 4:02d}h UTC")
    L += ["Por hora (UTC):", _tabla(["Hora", "n", "Éxito"], bloques), ""]
    meses = _grupos(ok, lambda it: it["s"]["vela_t"].strftime("%Y-%m"))
    L += ["Por mes (¿es estable?):", _tabla(["Mes", "n", "Éxito"], meses), ""]

    feats = [("Calidad de la subida (eff, alto = limpia)", lambda s: s["eff"]),
             ("Mechas en la subida (alto = más mechas)", lambda s: s["mechas"]),
             ("Deriva de la acumulación (ATR; alto = sigue subiendo)", lambda s: s["deriva"]),
             ("Tamaño del impulso (ATR)", lambda s: s["impulse"] / s["atr"]),
             ("Rango de la acumulación / impulso", lambda s: s["frac"]),
             ("Velas de la acumulación", lambda s: s["acc"])]
    L += ["## Éxito (ref.) por características (tercios: bajo / medio / alto)", ""]
    for nombre, fn in feats:
        vals = sorted(fn(it["s"]) for it in ok)
        q1, q2 = vals[len(vals) // 3], vals[2 * len(vals) // 3]
        g = _grupos(ok, lambda it, fn=fn: "bajo" if fn(it["s"]) < q1 else ("medio" if fn(it["s"]) < q2 else "alto"),
                    ["bajo", "medio", "alto"])
        L += [f"{nombre} (cortes {q1:.2f} / {q2:.2f}):", _tabla(["Tramo", "n", "Éxito"], g), ""]
    return "\n".join(L)


def historico(sym, dias):
    c = fetch_historial(sym, dias)
    print(f"{sym}: {len(c)} velas ({c[0]['t']} a {c[-1]['t']})")
    return analizar(sym, c)


def analizar(sym, c):
    spread = SPREAD.get(sym, 0.0)
    alertas = generar_alertas(c)
    items = []
    for s in alertas:
        fut = futuro(c, s["i"], s["vela_t"])
        if s["i"] + HORIZON >= len(c) or not fut:
            continue  # todavía sin desenlace completo
        items.append({"s": s, "ev": evaluar(s, fut, spread)})
    os.makedirs(DATA_DIR, exist_ok=True)
    nombre = sym.replace("/", "")
    with open(os.path.join(DATA_DIR, f"historico_{nombre}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for it in items:
            w.writerow(fila_csv(sym, it["s"], it["ev"]))
    texto = resumen(sym, c, alertas, items, spread)
    with open(os.path.join(DATA_DIR, f"resumen_{nombre}.md"), "w") as f:
        f.write(texto)
    return texto


# ------------------------------------------------------------------ registro en vivo
def _ruta_vivo():
    return os.path.join(DATA_DIR, "alertas_vivo.csv")


def _leer_vivo():
    try:
        with open(_ruta_vivo(), newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def _guardar_vivo(filas):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_ruta_vivo(), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)


def registrar_vivo(sym, s):
    filas = _leer_vivo()
    previas = [r for r in filas if r["simbolo"] == sym]
    setup = 1
    if previas:
        ult = previas[-1]
        t0 = datetime.strptime(ult["vela_t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        setup = int(ult["setup"] or 0) + (0 if s["vela_t"] - t0 <= timedelta(minutes=CANDLE_MIN * SETUP_GAP) else 1)
    s["setup"] = setup
    filas.append(fila_csv(sym, s, None))
    _guardar_vivo(filas)


def actualizar_vivo(sym, c):
    filas = _leer_vivo()
    if not filas:
        return
    ahora = datetime.now(timezone.utc)
    pos = {x["t"]: i for i, x in enumerate(c)}
    cambios = False
    for r in filas:
        if r["simbolo"] != sym or r["estado"] != "pendiente":
            continue
        t = datetime.strptime(r["vela_t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        if ahora < t + timedelta(minutes=CANDLE_MIN + HORIZON_H * 60 + CANDLE_MIN):
            continue
        if t not in pos:
            r["estado"] = "sin_datos"
            cambios = True
            continue
        s = {"price": float(r["precio"]), "peak": float(r["peak"]), "base": float(r["base"]),
             "acc_hi": float(r["acc_hi"]), "atr": float(r["atr"]), "impulse": float(r["impulso"])}
        fut = futuro(c, pos[t], t)
        if not fut:
            continue
        ev = evaluar(s, fut, SPREAD.get(sym, 0.0))
        r.update({"estado": "ok", "exito_ref": ev["exito_ref"], "exito_r50": ev["exito_r50"],
                  "fill_max_pct": ev["fill_max_pct"],
                  "mae_ref_atr": "" if ev["mae_ref_atr"] is None else ev["mae_ref_atr"]})
        cambios = True
    if cambios:
        _guardar_vivo(filas)



# ------------------------------------------------------------------ estabilidad (sin API)
def estabilidad(sym):
    """Lee datos/historico_*.csv y comprueba si los filtros se mantienen en la 1ª y 2ª mitad del periodo."""
    nombre = sym.replace("/", "")
    ruta = os.path.join(DATA_DIR, f"historico_{nombre}.csv")
    with open(ruta, newline="") as f:
        filas = list(csv.DictReader(f))
    rows, poco_riesgo = [], 0
    minimo = 3 * SPREAD.get(sym, 0.0)  # un SL a menos de 3 spreads no es operable
    for r in filas:
        if r["estado"] != "ok" or r["viernes_tarde"] == "1" or r["exito_ref"] == "":
            continue
        if float(r["riesgo_pts"]) < minimo:
            poco_riesgo += 1
            continue
        t = datetime.strptime(r["vela_t"], "%Y-%m-%d %H:%M")
        rows.append({"t": t, "setup": int(r["setup"]), "sesion": r["sesion"], "hora": t.hour,
                     "deriva": float(r["deriva_atr"]), "ok": int(r["exito_ref"]), "r50": int(r["exito_r50"])})
    rows.sort(key=lambda x: x["t"])
    if len(rows) < 60:
        return "Muy pocas alertas en el CSV para comparar mitades."
    vistos = set()
    for x in rows:
        x["primera"] = x["setup"] not in vistos
        vistos.add(x["setup"])
    mitad = rows[0]["t"] + (rows[-1]["t"] - rows[0]["t"]) / 2
    h1 = [x for x in rows if x["t"] < mitad]
    h2 = [x for x in rows if x["t"] >= mitad]
    v1 = sorted(x["deriva"] for x in h1)
    corte = v1[len(v1) // 3]  # el corte se fija solo con la 1ª mitad (sin mirar la 2ª)

    filtros = [
        ("Todas (referencia)", lambda x: True, 0),
        ("Nueva York+Londres", lambda x: x["sesion"] == "Nueva York+Londres", 1),
        ("12 a 16h UTC", lambda x: 12 <= x["hora"] < 16, 1),
        (f"Deriva baja (< {corte:.2f} ATR)", lambda x: x["deriva"] < corte, 1),
        ("NY+Londres y deriva baja", lambda x: x["sesion"] == "Nueva York+Londres" and x["deriva"] < corte, 1),
        ("Fuera de sesión", lambda x: x["sesion"] == "Fuera", -1),
    ]

    def celda(lst):
        n = len(lst)
        if not n:
            return "–", 0.0, 0
        p = sum(x["ok"] for x in lst) / n
        return f"{100 * p:.0f}% (n={n})" + ("⚠" if n < 30 else ""), p, n

    def tabla(sub1, sub2):
        _, b1, _ = celda(sub1)
        _, b2, _ = celda(sub2)
        filas_t = []
        for nombre_f, fn, signo in filtros:
            c1, p1, n1 = celda([x for x in sub1 if fn(x)])
            c2, p2, n2 = celda([x for x in sub2 if fn(x)])
            if signo == 0:
                ver = ""
            elif n1 < 20 or n2 < 20:
                ver = "pocos casos"
            else:
                d1, d2 = signo * (p1 - b1), signo * (p2 - b2)
                if d1 >= 0.05 and d2 >= 0.05:
                    ver = "se mantiene"
                elif d1 >= 0.05 or d2 >= 0.05:
                    ver = "solo en una mitad"
                else:
                    ver = "no se mantiene"
            filas_t.append([nombre_f, c1, c2, ver])
        return _tabla(["Filtro", "1ª mitad", "2ª mitad", "Veredicto"], filas_t)

    L = [f"# {sym} — ¿se mantienen los filtros? (1ª vs 2ª mitad)", "",
         f"- Excluidas por riesgo menor a 3 veces el spread (SL demasiado pegado, no operable): {poco_riesgo}",
         f"- Alertas evaluadas (sin viernes tarde): {len(rows)} | 1ª mitad: {len(h1)} ({h1[0]['t']:%Y-%m-%d} a {mitad:%Y-%m-%d}) | "
         f"2ª mitad: {len(h2)} (hasta {h2[-1]['t']:%Y-%m-%d})",
         "- El corte de 'deriva baja' se calculó solo con la 1ª mitad, para no hacer trampa con la 2ª.",
         "- 'Se mantiene' = mejora al menos 5 puntos sobre 'Todas' en las dos mitades, con 20 casos o más cada una. "
         "'Fuera de sesión' es al revés: debe rendir peor.",
         "- ⚠ = menos de 30 casos.", "",
         "## Todas las alertas", "", tabla(h1, h2), "",
         "## Solo la primera alerta de cada setup (más independientes entre sí)", "",
         tabla([x for x in h1 if x["primera"]], [x for x in h2 if x["primera"]]), ""]
    texto = "\n".join(L)
    with open(os.path.join(DATA_DIR, f"estabilidad_{nombre}.md"), "w") as f:
        f.write(texto)
    return texto


# ------------------------------------------------------------------ confirmación en 5m
W_MAX = 24                 # vigilancia máxima tras la alerta: 24 velas de 5m (2 h)
W_DEFAULT = 12             # ventana de la tabla principal: 12 velas (60 min)
HORIZON5 = HORIZON_H * 60 // 5
SLIPPAGE = {"XAU/USD": 0.20}   # deslizamiento supuesto en órdenes pendientes (en precio)
X_LIST = [0.0, 0.1, 0.2, 0.3, 0.5]   # cuánto pasa bajo el piso, en ATR de 15m
PISOS = ["mecha", "cuerpo"]          # mecha = mínimo con mechas; cuerpo = mínimo de los cuerpos
TIPOS = ["cierre", "toque"]          # cierre = vela de 5m que cierra bajo el nivel; toque = orden pendiente
SL5 = ["máx", "acum", "rup", "1ATR"]  # rup = sobre los máximos de los últimos 30 min
REF5 = ("máx", "1.5ATR")


def agregar_15m(c5):
    g = {}
    for x in c5:
        k = x["t"].replace(minute=(x["t"].minute // 15) * 15)
        g.setdefault(k, []).append(x)
    out = []
    for k in sorted(g):
        v = sorted(g[k], key=lambda x: x["t"])
        if len(v) == 3:
            out.append({"t": k, "o": v[0]["o"], "h": max(y["h"] for y in v),
                        "l": min(y["l"] for y in v), "c": v[-1]["c"]})
    return out


def niveles5(s, entry, c5, brk):
    a = s["atr"]
    sls = {"máx": s["peak"] + SL_BUFFER_ATR * a,
           "acum": s["acc_hi"] + SL_BUFFER_ATR * a,
           "rup": max(x["h"] for x in c5[max(0, brk - 5):brk + 1]) + SL_BUFFER_ATR * a,
           "1ATR": entry + a}
    tps = {"1ATR": entry - a, "1.5ATR": entry - 1.5 * a, "2ATR": entry - 2 * a,
           "3ATR": entry - 3 * a, "r50": s["peak"] - 0.5 * s["impulse"], "r100": s["base"]}
    return sls, tps


def resultado_entrada(c5, tr, cb, spread):
    """R de una operación (cacheado). tr = {s, ei, entry, brk}. cb = (SL, TP)."""
    cache = tr.setdefault("cache", {})
    if cb not in cache:
        ei = tr["ei"]
        t_e = c5[ei]["t"]
        fut = [x for x in c5[ei + 1: ei + 1 + HORIZON5] if x["t"] <= t_e + timedelta(hours=HORIZON_H)]
        sls, tps = niveles5(tr["s"], tr["entry"], c5, tr["brk"])
        cache[cb] = simular(fut, tr["entry"], sls[cb[0]], tps[cb[1]], spread)
    return cache[cb]


def preparar_items(sym, c15, c5):
    spread = SPREAD.get(sym, 0.0)
    times5 = [x["t"] for x in c5]
    items = []
    for s in generar_alertas(c15):
        if s["tarde"] or (s["sl"] - s["price"]) < 3 * spread:
            continue
        t_alerta = s["vela_t"] + timedelta(minutes=CANDLE_MIN)
        j0 = bisect.bisect_left(times5, t_alerta)
        if j0 >= len(c5) or j0 < 8 or c5[j0]["t"] - t_alerta > timedelta(minutes=15):
            continue
        if j0 + W_MAX + HORIZON5 + 2 > len(c5):
            continue  # todavía sin desenlace completo
        s["j0"] = j0
        items.append(s)
    return items


def buscar_ruptura(c5, s, piso, X, tipo, delay, slip):
    j0 = s["j0"]
    nivel = piso - X * s["atr"]
    for k in range(j0, min(j0 + W_MAX, len(c5) - 1)):
        x = c5[k]
        if x["h"] > s["peak"]:
            return None  # el setup se invalida: rompió el máximo antes de confirmar
        if tipo == "cierre":
            if x["c"] <= nivel:
                e = k + delay
                if e >= len(c5) or any(y["h"] > s["peak"] for y in c5[k + 1:e + 1]):
                    return None
                return {"k": k - j0, "ei": e, "entry": c5[e]["c"], "brk": k}
        elif x["l"] <= nivel:
            return {"k": k - j0, "ei": k, "entry": min(nivel, x["o"]) - slip, "brk": k}
    return None


def correr_variante(c5, items, piso, X, tipo, delay, sym):
    slip = SLIPPAGE.get(sym, 0.0)
    trades, vistos = [], set()
    for s in items:
        piso_p = s["acc_lo"] if piso == "mecha" else s["acc_body_lo"]
        r = buscar_ruptura(c5, s, piso_p, X, tipo, delay, slip)
        if r is None:
            continue
        key = (s["setup"], c5[r["ei"]]["t"])
        if key in vistos:
            continue
        vistos.add(key)
        trades.append({"s": s, "ei": r["ei"], "entry": r["entry"], "brk": r["brk"], "k": r["k"]})
    return trades


def directas(items, primera_solo):
    out, vistos = [], set()
    for s in items:
        if primera_solo:
            if s["setup"] in vistos:
                continue
            vistos.add(s["setup"])
        out.append({"s": s, "ei": s["j0"] - 1, "entry": s["price"], "brk": s["j0"] - 1, "k": 0})
    return out


def _est(c5, trs, cb, spread):
    rs = [resultado_entrada(c5, t, cb, spread) for t in trs]
    rs = [r for r in rs if r]
    if not rs:
        return 0, 0, 0.0, 0.0
    tot = sum(r[1] for r in rs)
    return len(rs), sum(1 for r in rs if r[0] == "TP"), tot / len(rs), tot


def analizar_confirmacion(sym, c15, c5):
    spread = SPREAD.get(sym, 0.0)
    items = preparar_items(sym, c15, c5)
    if len(items) < 30:
        return "Muy pocas alertas con velas de 5m para analizar la confirmación."
    setups = len({s["setup"] for s in items})
    mitad = items[0]["vela_t"] + (items[-1]["vela_t"] - items[0]["vela_t"]) / 2

    # --- variantes (ventana W_MAX; luego se filtra por ventana)
    variantes = {}
    for piso in PISOS:
        for X in X_LIST:
            for tipo in TIPOS:
                variantes[(piso, X, tipo)] = correr_variante(c5, items, piso, X, tipo, 0, sym)

    def en_ventana(trs, W):
        return [t for t in trs if t["k"] < W]

    def nombre(v):
        return f"{v[0]} {v[2]} {v[1]:g}"

    dir_todas, dir_1 = directas(items, False), directas(items, True)

    L = [f"# {sym} — confirmación en 5m al romper el piso de la acumulación", "",
         f"- Periodo: {c5[0]['t']:%Y-%m-%d} a {c5[-1]['t']:%Y-%m-%d} | alertas evaluables: {len(items)} en {setups} setups "
         f"(sin viernes tarde ni SL menor a 3 spreads)",
         f"- Se vigila hasta {W_MAX} velas de 5m tras la alerta; el setup se anula si el precio supera el máximo de la subida antes de confirmar.",
         f"- Objetivo y SL medidos desde la entrada. Referencia: SL sobre el máximo y TP {REF5[1]}. Spread {spread}, "
         f"deslizamiento en órdenes pendientes {SLIPPAGE.get(sym, 0.0)}. Horizonte {HORIZON_H} h.",
         "- 'cierre' = vela de 5m que cierra bajo el nivel (entras al cierre). 'toque' = orden pendiente que se activa al tocar el nivel. "
         "El número es cuántos ATR de 15m bajo el piso. 'mecha' = mínimo con mechas; 'cuerpo' = mínimo de los cuerpos.",
         "- Una operación por setup. ⚠ = menos de 30 casos.", ""]

    # --- tabla principal
    filas = []
    for etiqueta, trs in (("Directa (todas)", dir_todas), ("Directa (1ª/setup)", dir_1)):
        n, w, avg, tot = _est(c5, trs, REF5, spread)
        filas.append([etiqueta, "100%", n, _tasa(w, n), f"{avg:+.2f}", f"{tot:+.1f}", "–"])
    ranking = []
    for v, trs in variantes.items():
        ts = en_ventana(trs, W_DEFAULT)
        n, w, avg, tot = _est(c5, ts, REF5, spread)
        conf = len({t["s"]["setup"] for t in ts})
        cayo = _med([(t["s"]["price"] - t["entry"]) / t["s"]["atr"] for t in ts]) if ts else 0.0
        filas.append([nombre(v), f"{100 * conf / setups:.0f}%", n, _tasa(w, n), f"{avg:+.2f}", f"{tot:+.1f}", f"{cayo:.1f}"])
        if n >= 30:
            ranking.append((tot, v))
    L += [f"## Entrada directa vs confirmada (ventana {W_DEFAULT} velas = {W_DEFAULT * 5} min)", "",
          _tabla(["Variante", "Setups que confirman", "Ops", "Acierto", "R/op", "R total", "Ya cayó (ATR)"], filas), "",
          "R total suma todas las operaciones: es la medida justa para comparar, porque confirmar reduce el número de operaciones. "
          "'Ya cayó' = distancia entre el precio de la alerta y tu entrada.", ""]
    ranking.sort(reverse=True)
    if not ranking:
        L.append("Ninguna variante llegó a 30 operaciones.")
        return "\n".join(L)
    top = [v for _, v in ranking[:3]]
    mejor = top[0]

    # --- tiempo hasta la ruptura
    trs = variantes[mejor]
    ks = [(t["k"] + 1) * 5 for t in trs]
    cob = []
    for W in (6, 10, 12, 18, 24):
        c = len({t["s"]["setup"] for t in trs if t["k"] < W})
        cob.append([f"{W} velas ({W * 5} min)", f"{100 * c / setups:.0f}%"])
    L += [f"## ¿Cuánto tarda en confirmar? (variante: {nombre(mejor)})", "",
          f"Tiempo mediano hasta la ruptura: {_med(ks)} min; el 75% ocurre antes de {_q(ks, .75):.0f} min; el 90%, antes de {_q(ks, .9):.0f} min.", "",
          _tabla(["Ventana", "Setups que confirman"], cob), ""]

    # --- cuadrícula SL x TP de la mejor
    ts = en_ventana(variantes[mejor], W_DEFAULT)
    fw, fr = [], []
    for sn in SL5:
        rw, rr = [f"SL {sn}"], [f"SL {sn}"]
        for tn in TP_NAMES:
            n, w, avg, tot = _est(c5, ts, (sn, tn), spread)
            rw.append(_tasa(w, n))
            rr.append(f"{avg:+.2f}" if n else "–")
        fw.append(rw)
        fr.append(rr)
    cab = [""] + [f"TP {t}" for t in TP_NAMES]
    L += [f"## Mejor variante: {nombre(mejor)} — % de aciertos por SL y TP", "", _tabla(cab, fw), "",
          "## Ganancia promedio por operación (R)", "", _tabla(cab, fr), "",
          "'rup' = SL sobre los máximos de los últimos 30 min antes de entrar.", ""]

    # --- estabilidad de las 3 mejores
    fe = []
    for v in top:
        ts = en_ventana(variantes[v], W_DEFAULT)
        a = [t for t in ts if t["s"]["vela_t"] < mitad]
        b = [t for t in ts if t["s"]["vela_t"] >= mitad]
        na, wa, ra, ta = _est(c5, a, REF5, spread)
        nb, wb, rb, tb = _est(c5, b, REF5, spread)
        fe.append([nombre(v), f"{_tasa(wa, na)} n={na}", f"{ra:+.2f}", f"{_tasa(wb, nb)} n={nb}", f"{rb:+.2f}"])
    L += ["## ¿Se mantiene en las dos mitades? (3 mejores)", "",
          _tabla(["Variante", "1ª mitad", "R/op", "2ª mitad", "R/op"], fe), "",
          "Ojo: elegí estas variantes por su resultado en todo el periodo, así que parte de su ventaja puede ser suerte. "
          "Lo importante es que se mantengan en ambas mitades.", ""]

    # --- sensibilidad al retraso (solo 'cierre')
    cierres = [v for _, v in ranking if v[2] == "cierre"]
    if cierres:
        v = cierres[0]
        fd = []
        for d in (0, 1, 2):
            tr = correr_variante(c5, items, v[0], v[1], "cierre", d, sym)
            tr = en_ventana(tr, W_DEFAULT)
            n, w, avg, tot = _est(c5, tr, REF5, spread)
            fd.append([f"{d * 5} min", n, _tasa(w, n), f"{avg:+.2f}", f"{tot:+.1f}"])
        L += [f"## ¿Y si entras tarde? (variante: {nombre(v)})", "",
              _tabla(["Retraso tras el cierre", "Ops", "Acierto", "R/op", "R total"], fd), ""]

    # --- sesión
    fs = []
    for etiqueta, trs_ in (("Directa (1ª/setup)", dir_1), (nombre(mejor), en_ventana(variantes[mejor], W_DEFAULT))):
        for grupo, fn in (("NY+Londres", lambda t: t["s"]["ses"]["sesion"] == "Nueva York+Londres"),
                          ("Resto", lambda t: t["s"]["ses"]["sesion"] != "Nueva York+Londres")):
            sub = [t for t in trs_ if fn(t)]
            n, w, avg, tot = _est(c5, sub, REF5, spread)
            fs.append([etiqueta, grupo, n, _tasa(w, n), f"{avg:+.2f}", f"{tot:+.1f}"])
    L += ["## Por sesión", "", _tabla(["Entrada", "Grupo", "Ops", "Acierto", "R/op", "R total"], fs), ""]

    # --- CSV con las operaciones
    os.makedirs(DATA_DIR, exist_ok=True)
    nombre_f = sym.replace("/", "")
    with open(os.path.join(DATA_DIR, f"confirmacion_{nombre_f}.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variante", "setup", "alerta_t", "entrada_t", "entrada", "min_hasta_ruptura",
                    "sesion", "resultado", "R"])
        for v, trs_ in variantes.items():
            for t in en_ventana(trs_, W_DEFAULT):
                r = resultado_entrada(c5, t, REF5, spread)
                if r:
                    w.writerow([nombre(v), t["s"]["setup"], t["s"]["vela_t"].strftime("%Y-%m-%d %H:%M"),
                                c5[t["ei"]]["t"].strftime("%Y-%m-%d %H:%M"), round(t["entry"], 3),
                                (t["k"] + 1) * 5, t["s"]["ses"]["sesion"], r[0], round(r[1], 3)])
    texto = "\n".join(L)
    with open(os.path.join(DATA_DIR, f"confirmacion_{nombre_f}.md"), "w") as f:
        f.write(texto)
    return texto


def confirmacion(sym, dias):
    c15 = fetch_historial(sym, dias)
    print(f"{sym}: {len(c15)} velas de 15m")
    time.sleep(8)
    c5 = fetch_historial(sym, dias, "5min", 5)
    print(f"{sym}: {len(c5)} velas de 5m ({c5[0]['t']} a {c5[-1]['t']})")
    return analizar_confirmacion(sym, c15, c5)

# ------------------------------------------------------------------ avisos
def mensaje(sym, s):
    ses = s["ses"]
    ctx = (f"Fuera de sesión ({ses['horas_fuera']} h tras el último cierre)" if ses["sesion"] == "Fuera"
           else f"Sesión {ses['sesion']} ({ses['min_apertura']} min desde la apertura)")
    riesgo = s["sl"] - s["price"]
    return (
        f"{sym} 15m — posible VENTA\n"
        f"{ctx}\n"
        f"Impulso: {s['impulse']:.2f} ({s['impulse'] / s['atr']:.1f} ATR)\n"
        f"Acumulación: {s['acc']} velas, rango {s['acc_hi'] - s['acc_lo']:.2f} "
        f"({s['frac'] * 100:.0f}% del impulso)\n"
        f"Zona: {s['acc_lo']:.2f} – {s['acc_hi']:.2f}\n"
        f"Precio: {s['price']:.2f}\n"
        f"SL sobre el máximo: {s['sl']:.2f} (riesgo {riesgo:.2f} pts, {riesgo / s['atr']:.1f} ATR)\n"
        f"Espacio libre hasta la base: {s['acc_lo'] - s['base']:.2f} (base {s['base']:.2f})\n"
        f"Calidad de la subida: limpieza {s['eff']:.2f}, mechas {s['mechas'] * 100:.0f}%"
    )


def telegram(text):
    token = os.environ["TELEGRAM_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    data = urllib.parse.urlencode({"chat_id": chat, "text": text[:3900]}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage",
                               data=data, timeout=30).read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram {e.code}: {e.read().decode(errors='replace')}") from None


def enviar_email(asunto, text):
    user = os.environ["EMAIL_USER"]
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = user
    msg["To"] = os.environ.get("EMAIL_TO") or user
    msg.set_content(text)
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    with smtplib.SMTP_SSL(host, 465, context=ssl.create_default_context(), timeout=30) as srv:
        srv.login(user, os.environ["EMAIL_PASS"])
        srv.send_message(msg)


def notificar(asunto, text):
    """Manda por email y/o Telegram, según los Secrets que existan."""
    enviados, errores = 0, []
    if os.environ.get("EMAIL_USER"):
        try:
            enviar_email(asunto, text)
            enviados += 1
        except Exception as e:
            errores.append(f"Email: {e}")
    if os.environ.get("TELEGRAM_TOKEN"):
        try:
            telegram(f"{asunto}\n{text}")
            enviados += 1
        except Exception as e:
            errores.append(f"Telegram: {e}")
    for e in errores:
        print("Error al notificar ->", e)
    if not enviados:
        raise RuntimeError("No se pudo enviar por ningún canal")


# ------------------------------------------------------------------ modos
def backtest(sym):
    c = fetch(sym, 700)
    for s in generar_alertas(c):
        cierre = s["vela_t"] + timedelta(minutes=CANDLE_MIN)
        etiqueta = " (viernes tarde, se ignora)" if s["tarde"] else ""
        print(f"{sym} | alerta {cierre:%Y-%m-%d %H:%M} UTC | {s['ses']['sesion']} | "
              f"impulso {s['impulse']:.2f} | zona {s['acc_lo']:.2f}-{s['acc_hi']:.2f} | "
              f"precio {s['price']:.2f}{etiqueta}")
    print(f"{sym}: {c[0]['t']:%Y-%m-%d} a {c[-1]['t']:%Y-%m-%d}")


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else "run"
    if modo == "test":
        notificar("✅ Prueba del bot de alertas", "Si lees esto, las notificaciones funcionan.")
        return
    if modo == "confirmacion":
        dias = int(os.environ.get("DIAS") or 365)
        for sym in SYMBOLS:
            texto = confirmacion(sym, dias)
            print(texto)
            notificar(f"📊 Confirmación 5m {sym} ({dias} días)", texto)
        return
    if modo == "estabilidad":
        for sym in SYMBOLS:
            texto = estabilidad(sym)
            print(texto)
            notificar(f"📊 Estabilidad {sym}", texto)
        return
    if modo in ("backtest", "historico"):
        dias = int(os.environ.get("DIAS") or 365)
        for k, sym in enumerate(SYMBOLS):
            if k:
                time.sleep(8)
            if modo == "backtest":
                backtest(sym)
            else:
                texto = historico(sym, dias)
                print(texto)
                notificar(f"📊 Análisis {sym} ({dias} días)", texto)
        return

    state = load_state()
    fallo = False
    for k, sym in enumerate(SYMBOLS):
        if k:
            time.sleep(8)  # el plan gratis permite 8 llamadas por minuto
        try:
            c = fetch(sym)
            s = detect(c)
            if s:
                enriquecer(s)
            if s and state.get(sym) != s["key"]:
                if s["tarde"]:
                    print(f"{sym}: señal de viernes tarde, no se avisa")
                else:
                    notificar(f"🔔 {sym} 15m — posible VENTA", mensaje(sym, s))
                    print(f"Alerta enviada: {sym}")
                    try:
                        registrar_vivo(sym, s)
                    except Exception as e:
                        print(f"No se pudo registrar la alerta: {e}")
                state[sym] = s["key"]
            else:
                print(f"{sym}: sin señal nueva")
            try:
                actualizar_vivo(sym, c)
            except Exception as e:
                print(f"No se pudieron actualizar desenlaces: {e}")
        except Exception as e:  # un par que falla no detiene a los demás
            print(f"Error con {sym}: {e}")
            fallo = True
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    if fallo:
        sys.exit(1)


if __name__ == "__main__":
    main()
