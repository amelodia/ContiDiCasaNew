# CursorAppMacCdc
Progetto CursorMAC CdC

## ImportLegacy (prima funzione)

Script Python per importare il database legacy annuale VB6 in un database unico JSON.

### Cosa legge
- `*dat.aco` (record fissi da 121 byte)
- `*cat.aco` (categorie)
- `*coc.aco` (conti)
- `*not.aco` (nota esplicativa per ogni categoria)

### Comportamento valuta
- anni `1990-2001`: sorgente in lire
- anni `2002+`: sorgente in euro
- il nuovo database salva sempre `amount_eur`, ma mantiene anche `amount_lire_original`
- per la visualizzazione, i record ante 2002 espongono `display_currency=LIRE`

### Regola Dotazione iniziale
- le registrazioni con categoria `Dotazione iniziale` sono escluse dal 1991 in poi
- l'unica eccezione importata e mantenuta e il 1990

### Vincoli nuova app (immissione)
- nuove registrazioni solo in euro
- limiti importo: da `-999999999,99` a `+999999999,99`
- parser importo: `.` e `,` sono entrambi accettati come separatore decimale in input
- formattazione importo: stile italiano (`1.234,56`)
- lunghezze massime:
  - categoria: `20`
  - nota categoria: `100`
  - conto: `16`
  - assegno: `8`
  - nota registrazione: `100`

### Import legacy conti con asterischi
- gli asterischi adiacenti ai conti sono preservati:
  - `account_primary_flags`, `account_secondary_flags`
  - `account_primary_with_flags`, `account_secondary_with_flags`

### Esecuzione

```bash
python3 import_legacy.py \
  --cdc-root "/Users/macand/Library/CloudStorage/Dropbox/CdC" \
  --output "data/unified_legacy_import.json"
```

### Integrazione nel programma principale

`ImportLegacy` e ora anche integrabile come modulo Python:

```python
from import_legacy import run_import_legacy

result = run_import_legacy(
    "/Users/macand/Library/CloudStorage/Dropbox/CdC",
    "data/unified_legacy_import.json",
)
```

### Avvio app desktop (prima UI)

```bash
python3 main_app.py
```

All'apertura:
- esegue `ImportLegacy`
- mostra le registrazioni importate
- mostra i saldi dei conti dell'ultimo anno

### Struttura pagine

Le pagine disponibili sono:
- Movimenti e correzioni (default all'avvio)
- Nuovi dati
- Verifica
- Statistiche
- Budget
- Opzioni
- Aiuto

### Opzioni (prima implementazione)

- ricarica import legacy con sovrascrittura del database nuova app
- scelta cartella sorgente legacy
- scelta file dati nuova app (`.enc`)
- scelta file chiave cifratura (`.key`)

Nota: per la cifratura file serve il pacchetto Python `cryptography`.
