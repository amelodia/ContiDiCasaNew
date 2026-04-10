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

L’output JSON predefinito è in **`legacy_import/`** (non in `data/`), così nella cartella dati restano solo file operativi (`.key`, `.enc` completo e `*_light.enc`).

```bash
python3 import_legacy.py \
  --cdc-root "/Users/macand/Library/CloudStorage/Dropbox/CdC" \
  --output "legacy_import/unified_legacy_import.json"
```

### Integrazione nel programma principale

`ImportLegacy` è integrabile come modulo Python:

```python
from import_legacy import run_import_legacy

result = run_import_legacy(
    "/Users/macand/Library/CloudStorage/Dropbox/CdC",
    "legacy_import/unified_legacy_import.json",
)
```

### Avvio app desktop (prima UI)

```bash
python3 main_app.py
```

### Desktop e versione light (iPhone)

- **`main_app.py`** è l’app **desktop** (Tk): deve restare la versione **completa**.  
- La versione **light** per iPhone è un percorso **separato**: cartella **`iphone_light/`** (auth, crypto, CLI) e futura app nativa iOS. Le semplificazioni di interfaccia per il mobile vanno descritte in `iphone_light/LIGHT_UI_SPEC.md` e implementate lì / in Swift, **non** accorciando il desktop.

All’apertura (flusso tipico):
- se non esiste ancora un database cifrato per-utente, esegue **ImportLegacy** (output JSON in `legacy_import/`) e poi la configurazione posta / primo accesso;
- altrimenti carica il `.enc` da `data/` e fonde eventuali righe dal file `*_light.enc`;
- mostra movimenti e saldi nell’interfaccia.

### Struttura pagine

Le pagine disponibili sono:
- Movimenti e correzioni (default all'avvio)
- Nuove registrazioni
- Verifica
- Statistiche
- Budget
- Opzioni
- Aiuto

### Opzioni (prima implementazione)

- ricarica import legacy con sovrascrittura del database nuova app
- scelta cartella sorgente legacy
- scelta file dati nuova app (`.enc` completo, tipicamente `conti_utente_<hash>.enc`)
- scelta file chiave cifratura (`.key`, es. `conti_di_casa.key`)
- **Sposta nella cartella…**: sposta insieme **tre file** nella cartella scelta — `.enc` completo, `*_light.enc` (stesso stem del completo + suffisso `_light`) e `.key` (stessi nomi file)

### Layout cartella dati (Dropbox / sync)

Nella stessa cartella (es. `data/` sul Mac):

| File | Ruolo |
|------|--------|
| `conti_di_casa.key` | Chiave Fernet (o unico `.key` in cartella) |
| `conti_utente_<hash>.enc` | Database completo cifrato per account |
| `conti_utente_<hash>_light.enc` | Sidecar “light” (ultimi 365 giorni + metadati); rigenerato dal desktop a ogni salvataggio |

Il desktop **non** usa più una sottocartella dedicata: il file light sta **accanto** al `.enc` completo.

**Copia di sicurezza locale (solo Mac, Library dell’utente che avvia l’app):** a ogni salvataggio viene scritto anche `~/Library/Application Support/ContiDiCasa/<stem>_backup.enc`, dove `<stem>` è il nome del file dati principale senza `.enc` (allineato al DB operativo, es. `conti_utente_<hash>_backup.enc`). Non è il file in Dropbox: resta sulla macchina dell’utente.

**Ripristino se manca il database su Dropbox:** se nella cartella `data/` del progetto non c’è alcun `conti_utente_*.enc` ma esiste un backup in Library, all’avvio l’app propone di copiarlo in `data/` (nome dedotto dal file `*_backup.enc`), di rigenerare il file `*_light.enc` e di continuare. Da **Opzioni** è disponibile anche **«Ripristina da backup (Library Mac)…»** per copiare il backup sul percorso file dati attualmente impostato (anche fuori da `data/`) e aggiornare il light.

Primo avvio / import: artefatti in **`legacy_import/`** (JSON dell’import e, se serve, bootstrap cifrato prima del file per-utente in `data/`). Non versionare quei file (vedi `.gitignore`).

**Dropbox e path dei file:** se sposti la cartella dati (es. in `…/Dropbox/ContiCursor`), aggiorna in **Opzioni** i percorsi del file dati e della chiave; altrimenti l’app può ancora cercare `data/conti_di_casa.key` nella cartella del progetto. L’attesa «sincronizzazione» su un file **mancante** in Dropbox è limitata a pochi secondi (default 12s), non a minuti. Se il file esiste ed **è invariato da almeno ~45 secondi**, non si attende la finestra di stabilità (avvio quotidiano senza dialog). Variabili: `CONTI_CLOUD_WAIT_EXISTENCE_SECONDS`, `CONTI_DROPBOX_SKIP_STABILITY_IF_UNMODIFIED_SEC`, `CONTI_SKIP_CLOUD_SYNC_WAIT=1`.

**Posta all’avvio:** il wizard si apre solo se mancano ancora host SMTP/IMAP, credenziali o email amministratore. Se sono già salvate nel database, non viene richiesta ogni volta la «Verifica connessione» (puoi usarla da Opzioni quando serve).

Nota: per la cifratura file serve il pacchetto Python `cryptography`. Per SMTP/IMAP con certificati su macOS: `python3 -m pip install certifi` se necessario.
