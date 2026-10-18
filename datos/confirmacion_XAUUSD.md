# XAU/USD — confirmación en 5m al romper el piso de la acumulación

- Periodo: 2025-10-19 a 2026-10-18 | alertas evaluables: 988 en 219 setups (sin viernes tarde ni SL menor a 3 spreads)
- Se vigila hasta 24 velas de 5m tras la alerta; el setup se anula si el precio supera el máximo de la subida antes de confirmar.
- Objetivo y SL medidos desde la entrada. Referencia: SL sobre el máximo y TP 1.5ATR. Spread 0.3, deslizamiento en órdenes pendientes 0.2. Horizonte 12 h.
- 'cierre' = vela de 5m que cierra bajo el nivel (entras al cierre). 'toque' = orden pendiente que se activa al tocar el nivel. El número es cuántos ATR de 15m bajo el piso. 'mecha' = mínimo con mechas; 'cuerpo' = mínimo de los cuerpos.
- Una operación por setup. ⚠ = menos de 30 casos.

## Entrada directa vs confirmada (ventana 12 velas = 60 min)

```
Variante            Setups que confirman  Ops  Acierto  R/op   R total  Ya cayó (ATR)
Directa (todas)     100%                  988  36%      +0.11  +105.5   –            
Directa (1ª/setup)  100%                  219  41%      +0.03  +7.2     –            
mecha cierre 0      53%                   136  57%      -0.09  -12.2    1.2          
mecha toque 0       63%                   169  56%      -0.06  -10.6    1.1          
mecha cierre 0.1    48%                   121  60%      -0.04  -5.3     1.3          
mecha toque 0.1     58%                   153  58%      -0.05  -7.2     1.2          
mecha cierre 0.2    45%                   106  60%      -0.05  -4.8     1.3          
mecha toque 0.2     53%                   136  58%      -0.07  -9.0     1.2          
mecha cierre 0.3    42%                   95   60%      -0.06  -5.9     1.4          
mecha toque 0.3     51%                   125  58%      -0.09  -11.6    1.3          
mecha cierre 0.5    32%                   72   60%      -0.10  -6.8     1.7          
mecha toque 0.5     44%                   102  61%      -0.07  -7.1     1.7          
cuerpo cierre 0     68%                   186  56%      -0.08  -15.5    1.1          
cuerpo toque 0      74%                   227  56%      -0.06  -14.0    1.0          
cuerpo cierre 0.1   61%                   162  56%      -0.10  -15.4    1.1          
cuerpo toque 0.1    71%                   213  57%      -0.06  -12.4    1.0          
cuerpo cierre 0.2   56%                   144  56%      -0.09  -13.5    1.2          
cuerpo toque 0.2    67%                   191  56%      -0.08  -14.8    1.0          
cuerpo cierre 0.3   53%                   133  57%      -0.08  -11.2    1.3          
cuerpo toque 0.3    63%                   169  56%      -0.10  -17.2    1.1          
cuerpo cierre 0.5   42%                   96   55%      -0.12  -11.7    1.4          
cuerpo toque 0.5    53%                   137  55%      -0.13  -17.3    1.4          
```

R total suma todas las operaciones: es la medida justa para comparar, porque confirmar reduce el número de operaciones. 'Ya cayó' = distancia entre el precio de la alerta y tu entrada.

## ¿Cuánto tarda en confirmar? (variante: mecha cierre 0.2)

Tiempo mediano hasta la ruptura: 45 min; el 75% ocurre antes de 75 min; el 90%, antes de 105 min.

```
Ventana             Setups que confirman
6 velas (30 min)    24%                 
10 velas (50 min)   41%                 
12 velas (60 min)   45%                 
18 velas (90 min)   59%                 
24 velas (120 min)  68%                 
```

## Mejor variante: mecha cierre 0.2 — % de aciertos por SL y TP

```
         TP 1ATR  TP 1.5ATR  TP 2ATR  TP 3ATR  TP r50  TP r100
SL máx   68%      60%        54%      39%      61%     28%    
SL acum  68%      60%        54%      39%      61%     28%    
SL rup   58%      53%        49%      35%      52%     25%    
SL 1ATR  37%      31%        26%      17%      35%     9%     
```

## Ganancia promedio por operación (R)

```
         TP 1ATR  TP 1.5ATR  TP 2ATR  TP 3ATR  TP r50  TP r100
SL máx   -0.06    -0.05      -0.03    -0.10    -0.09   -0.06  
SL acum  -0.06    -0.05      -0.03    -0.10    -0.09   -0.06  
SL rup   -0.15    -0.11      -0.06    -0.13    -0.18   -0.10  
SL 1ATR  -0.26    -0.22      -0.19    -0.28    -0.30   -0.35  
```

'rup' = SL sobre los máximos de los últimos 30 min antes de entrar.

## ¿Se mantiene en las dos mitades? (3 mejores)

```
Variante          1ª mitad  R/op   2ª mitad  R/op 
mecha cierre 0.2  59% n=56  -0.08  62% n=50  -0.01
mecha cierre 0.1  59% n=70  -0.07  61% n=51  -0.01
mecha cierre 0.3  59% n=51  -0.10  61% n=44  -0.02
```

Ojo: elegí estas variantes por su resultado en todo el periodo, así que parte de su ventaja puede ser suerte. Lo importante es que se mantengan en ambas mitades.

## ¿Y si entras tarde? (variante: mecha cierre 0.2)

```
Retraso tras el cierre  Ops  Acierto  R/op   R total
0 min                   106  60%      -0.05  -4.8   
5 min                   106  62%      -0.00  -0.4   
10 min                  105  60%      -0.03  -2.9   
```

## Por sesión

```
Entrada             Grupo       Ops  Acierto  R/op   R total
Directa (1ª/setup)  NY+Londres  35   51%      +0.26  +9.3   
Directa (1ª/setup)  Resto       184  39%      -0.01  -2.1   
mecha cierre 0.2    NY+Londres  18   72%⚠     +0.23  +4.1   
mecha cierre 0.2    Resto       88   58%      -0.10  -8.9   
```
