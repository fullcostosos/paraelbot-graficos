# XAU/USD 15m — análisis 2025-10-17 a 2026-10-17

- Velas: 33735 | alertas detectadas: 1028 | evaluadas: 1006 (en 223 setups) | viernes tarde excluidas: 22 | pendientes: 0
- ⚠ = menos de 30 casos (poco fiable). Spread usado: 0.3. Horizonte: 12 h.

## Resultado general

Éxito = baja 1.5 ATR desde la alerta antes de tocar tu SL (sobre el máximo + 0.25 ATR).

```
Medida                        Todas       1ª de cada setup
Éxito (ref.)                  35% n=1006  40% n=223       
Rellena ≥50% sin romper máx.  15%         22%             
```

## Tu SL (sobre el máximo de la subida)

- Riesgo mediano: 5.6 pts (0.7 ATR); el 25% más cercano 3.2 pts; el 75%, 9.3 pts.
- En las que sí cumplieron, el precio subió en contra como máximo (ATR): mediana 0.3, p75 0.6, p90 1.1, máx 5.3. Si el SL va bastante más lejos que el p90, hay margen para acercarlo.

## SL × TP: % de aciertos

```
           TP 1ATR  TP 1.5ATR  TP 2ATR  TP 3ATR  TP r50  TP r100
SL máx     42%      35%        30%      23%      19%     7%     
SL acum    42%      35%        30%      22%      19%     7%     
SL 1ATR    47%      40%        34%      26%      20%     8%     
SL 1.5ATR  59%      51%        44%      33%      26%     9%     
```

## SL × TP: ganancia promedio por operación (en R; 1R = lo que arriesgas)

```
           TP 1ATR  TP 1.5ATR  TP 2ATR  TP 3ATR  TP r50  TP r100
SL máx     +0.01    +0.08      +0.14    +0.18    +0.11   +0.18  
SL acum    +0.01    +0.08      +0.14    +0.18    +0.11   +0.17  
SL 1ATR    -0.06    -0.00      +0.03    +0.08    -0.01   +0.08  
SL 1.5ATR  -0.02    +0.02      +0.03    +0.04    -0.04   +0.01  
```

r50/r100 = rellenar 50% / 100% de la subida. Lo que importa es la ganancia en R, no solo el % de aciertos.

## ¿Mejor que vender al azar?

```
Combinación          Alertas %  R prom.  Azar %  R prom.
SL 1ATR / TP 1ATR    47%        -0.06    35%     -0.23  
SL 1ATR / TP 2ATR    34%        +0.03    24%     -0.20  
SL 1ATR / TP 3ATR    26%        +0.08    18%     -0.18  
SL 1.5ATR / TP 1ATR  59%        -0.02    43%     -0.20  
SL 1.5ATR / TP 2ATR  44%        +0.03    31%     -0.19  
SL 1.5ATR / TP 3ATR  33%        +0.04    23%     -0.18  
```
Si las alertas no superan al azar en estas combinaciones, el patrón por sí solo no aporta ventaja.

## Éxito (ref.) por contexto

Por sesión (solape = dos abiertas):
```
Sesión              n    Éxito
Asia                436  35%  
Fuera               65   25%  
Londres             119  32%  
Londres+Asia        82   37%  
Nueva York          209  32%  
Nueva York+Londres  95   54%  
```

Por día:
```
Día  n    Éxito
Mon  208  38%  
Tue  203  31%  
Wed  230  32%  
Thu  149  46%  
Fri  194  34%  
Sun  19   42%⚠ 
```

Por hora (UTC):
```
Hora        n    Éxito
00-04h UTC  206  41%  
04-08h UTC  261  31%  
08-12h UTC  151  32%  
12-16h UTC  109  53%  
16-20h UTC  164  33%  
20-24h UTC  115  26%  
```

Por mes (¿es estable?):
```
Mes      n    Éxito
2025-10  27   41%⚠ 
2025-11  88   36%  
2025-12  103  33%  
2026-01  139  27%  
2026-02  110  40%  
2026-03  69   38%  
2026-04  66   45%  
2026-05  69   30%  
2026-06  64   44%  
2026-07  66   41%  
2026-08  100  31%  
2026-09  53   38%  
2026-10  52   29%  
```

## Éxito (ref.) por características (tercios: bajo / medio / alto)

Calidad de la subida (eff, alto = limpia) (cortes 0.30 / 0.39):
```
Tramo  n    Éxito
bajo   335  37%  
medio  335  37%  
alto   336  32%  
```

Mechas en la subida (alto = más mechas) (cortes 0.41 / 0.48):
```
Tramo  n    Éxito
bajo   335  34%  
medio  335  33%  
alto   336  39%  
```

Deriva de la acumulación (ATR; alto = sigue subiendo) (cortes 0.78 / 1.71):
```
Tramo  n    Éxito
bajo   335  41%  
medio  335  36%  
alto   336  29%  
```

Tamaño del impulso (ATR) (cortes 7.40 / 9.54):
```
Tramo  n    Éxito
bajo   335  41%  
medio  335  30%  
alto   336  35%  
```

Rango de la acumulación / impulso (cortes 0.27 / 0.36):
```
Tramo  n    Éxito
bajo   335  30%  
medio  335  40%  
alto   336  36%  
```

Velas de la acumulación (cortes 5.00 / 5.00):
```
Tramo  n     Éxito
alto   1006  35%  
```
