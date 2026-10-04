"""Alerta de posible VENTA: impulso alcista fuerte + acumulación en la parte alta (velas 15m).

Uso:
    python3 detector.py            -> revisa y avisa por Telegram si hay señal nueva
    python3 detector.py test       -> manda un mensaje de prueba a Telegram
    python3 detector.py backtest   -> muestra en qué momentos habría saltado la alerta (últimas ~7 días)
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

SYMBOLS = ["XAU/USD"]  # luego añadimos: "USD/CAD", "BTC/USD", ...
INTERVAL = "15min"
CANDLE_MIN = 15

# ---- Parámetros del patrón (se ajustan con el backtest) ----
ATR_PERIOD = 48         # ATR de las últimas 48 velas (12 h)
IMPULSE_ATR = 6.0       # el impulso debe medir al menos 6 ATR
IMPULSE_LOOKBACK = 24   # velas hacia atrás para buscar la base del impulso (6 h)
ACC_MIN, ACC_MAX = 5, 12  # largo de la acumulación, en velas
ACC_MAX_FRAC = 0.45     # rango de la acumulación <= 45% del impulso
HOLD_FRAC = 0.50        # la acumulación se mantiene en la mitad alta del impulso
NEAR_PEAK_FRAC = 0.25   # el techo de la acumulación está cerca del máximo
FREE_ATR = 4.0          # espacio libre (mínimo de acumulación - base) >= 4 ATR
PEAK_FRESH = 3          # el máximo no puede ser más viejo que la acumulación + 3 velas

STATE_FILE = "state.json"


def fetch(symbol, size=120):
    q = urllib.parse.urlencode({
        "symbol": symbol,
        "interval": INTERVAL,
        "outputsize": size,
        "timezone": "UTC",
        "order": "ASC",
        "apikey": os.environ["TWELVEDATA_KEY"],
    })
    with urllib.request.urlopen(f"https://api.twelvedata.com/time_series?{q}", timeout=30) as r:
        data = json.load(r)
    if data.get("status") == "error" or "values" not in data:
        raise RuntimeError(f"Twelve Data ({symbol}): {data.get('message', data)}")
    out = []
    for v in data["values"]:
        t = datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        out.append({"t": t, "o": float(v["open"]), "h": float(v["high"]),
                    "l": float(v["low"]), "c": float(v["close"])})
    out.sort(key=lambda x: x["t"])
    # descartar la vela que todavía se está formando
    if out and out[-1]["t"] + timedelta(minutes=CANDLE_MIN) > datetime.now(timezone.utc):
        out.pop()
    return out


def atr(c, period=ATR_PERIOD):
    trs = [max(c[i]["h"] - c[i]["l"],
               abs(c[i]["h"] - c[i - 1]["c"]),
               abs(c[i]["l"] - c[i - 1]["c"])) for i in range(1, len(c))]
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


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
        base = min(x["l"] for x in zone[:peak_i])
        impulse = peak - base
        acc_hi = max(x["h"] for x in win)
        acc_lo = min(x["l"] for x in win)
        price = c[-1]["c"]
        if (impulse >= IMPULSE_ATR * a
                and acc_hi - acc_lo <= ACC_MAX_FRAC * impulse
                and acc_lo >= base + HOLD_FRAC * impulse
                and peak - acc_hi <= NEAR_PEAK_FRAC * impulse
                and acc_lo - base >= FREE_ATR * a
                and price >= acc_lo):  # todavía no ha roto hacia abajo
            return {
                "key": zone[peak_i]["t"].isoformat(),
                "acc": acc, "atr": a, "impulse": impulse, "base": base,
                "acc_hi": acc_hi, "acc_lo": acc_lo, "price": price,
                "frac": (acc_hi - acc_lo) / impulse,
            }
    return None


def mensaje(sym, s):
    return (
        f"🔔 {sym} 15m — posible VENTA\n"
        f"Impulso: {s['impulse']:.2f} ({s['impulse'] / s['atr']:.1f} ATR)\n"
        f"Acumulación: {s['acc']} velas, rango {s['acc_hi'] - s['acc_lo']:.2f} "
        f"({s['frac'] * 100:.0f}% del impulso)\n"
        f"Zona: {s['acc_lo']:.2f} – {s['acc_hi']:.2f}\n"
        f"Precio: {s['price']:.2f}\n"
        f"Espacio libre hasta la base: {s['acc_lo'] - s['base']:.2f} (base {s['base']:.2f})"
    )


def telegram(text):
    token = os.environ["TELEGRAM_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage",
                           data=data, timeout=30).read()


def backtest(sym):
    c = fetch(sym, 700)
    seen = set()
    start = ATR_PERIOD + IMPULSE_LOOKBACK + ACC_MAX + 1
    for i in range(start, len(c) + 1):
        s = detect(c[:i])
        if s and s["key"] not in seen:
            seen.add(s["key"])
            cierre = c[i - 1]["t"] + timedelta(minutes=CANDLE_MIN)
            print(f"{sym} | alerta tras cerrar vela {cierre:%Y-%m-%d %H:%M} UTC | "
                  f"impulso {s['impulse']:.2f} | zona {s['acc_lo']:.2f}-{s['acc_hi']:.2f} | "
                  f"precio {s['price']:.2f}")
    print(f"{sym}: {len(seen)} señales en {len(c)} velas "
          f"({c[0]['t']:%Y-%m-%d} a {c[-1]['t']:%Y-%m-%d})")


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else "run"
    if modo == "test":
        telegram("✅ Prueba: el bot de alertas está conectado.")
        return
    if modo == "backtest":
        for k, sym in enumerate(SYMBOLS):
            if k:
                time.sleep(8)
            backtest(sym)
        return

    state = load_state()
    fallo = False
    for k, sym in enumerate(SYMBOLS):
        if k:
            time.sleep(8)  # el plan gratis permite 8 llamadas por minuto
        try:
            s = detect(fetch(sym))
        except Exception as e:  # un par que falla no detiene a los demás
            print(f"Error con {sym}: {e}")
            fallo = True
            continue
        if s and state.get(sym) != s["key"]:
            telegram(mensaje(sym, s))
            state[sym] = s["key"]
            print(f"Alerta enviada: {sym}")
        else:
            print(f"{sym}: sin señal nueva")
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    if fallo:
        sys.exit(1)


if __name__ == "__main__":
    main()
