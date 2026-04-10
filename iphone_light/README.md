# Conti di casa — versione light (iPhone / iOS)

Questa cartella definisce requisiti, percorsi e codice per un **client iOS** separato (Swift/SwiftUI), più moduli Python di supporto e **CLI di prova**. Il desktop (`main_app.py`) integra il file sidecar `*_light.enc` tramite `light_enc_sidecar.py` nella root del repo.

## Separazione obbligatoria desktop / light

| Programma | Percorso | Note |
|-----------|----------|------|
| **Desktop** | `main_app.py` (avvio: `python3 main_app.py`) | Funzionalità **complete**. Genera il file sidecar `*_light.enc` **nella stessa cartella** del `.enc` completo (nessuna sottocartella). |
| **Light** | App iOS + `iphone_light/*.py` | Login, crypto, probe CLI; la UI ridotta è nel **client mobile**. Requisiti UX in [`LIGHT_UI_SPEC.md`](LIGHT_UI_SPEC.md). |

Se servono comportamenti diversi tra desktop e mobile, si implementano **nel client iOS** (o in moduli sotto `iphone_light/` usati solo da quel client). La **sincronizzazione** del file sidecar light è gestita dal desktop (`main_app` + `light_enc_sidecar.py`).

## Principi (allineati alla tua richiesta)

1. **Account solo da desktop**  
   Primo accesso, verifica email, profilo e file `conti_utente_<hash>.enc` restano sul **desktop**. Su iPhone: **solo login** con **email e password** già presenti nel DB.

2. **Login senza immagini, senza backdoor**  
   Il desktop usa Pillow + JPEG e la sequenza Ctrl+Z / Ctrl+X (backdoor). La versione light deve offrire **solo** campi email/password e pulsante Accedi — nessun bypass amministrativo da UI.

3. **Nessun «accesso non registrato»**  
   Sul mobile ha senso solo l’utente con password impostata sul desktop (stesso `user_profile` / PBKDF2 di `security_auth.py`).

4. **Database su Dropbox**  
   Nella **stessa cartella** sincronizzata (es. `…/Dropbox/.../data/` sul Mac):

   - `conti_di_casa.key` (chiave Fernet; o unico file `.key` nella cartella)
   - `conti_utente_<hash>.enc` — database **completo** cifrato
   - `conti_utente_<hash>_light.enc` — copia **snella** (ultimi 365 giorni + date future, stessa chiave). **Sul telefono si usa questo** `.enc` per login e movimenti; il desktop lo rigenera a ogni salvataggio e all’avvio **importa** le nuove righe create sul telefono (campo `conti_light_record_id`).

### Sidecar light (desktop)

- Modulo: `light_enc_sidecar.py` nella root del repo (usato da `main_app.save_encrypted_db_dual` e all’avvio).
- Il file light ha nome `{stem}_light.enc` dove `{stem}` è il nome del `.enc` completo senza estensione (es. `conti_utente_abc…` → `conti_utente_abc…_light.enc`), **nella stessa cartella** del completo.
- Ogni nuova registrazione inserita dall’app iOS deve avere **`conti_light_record_id`**: stringa UUID univoca, così il desktop non duplica le righe al merge.
- L’implementazione Swift di **inserimento + salvataggio** sul file `_light.enc` è ancora da completare nella UI; login e lettura possono già usare il file light (JSON molto più piccolo del `.enc` completo).

5. **Nessun backup locale aggiuntivo su iPhone**  
   Sul desktop `save_encrypted_db_dual` scrive anche una copia in **`~/Library/Application Support/ContiDiCasa/<stem>_backup.enc`** (Library dell’utente sul Mac, nome legato al file `.enc` principale). Su iPhone: **solo** riscrittura del file `.enc` operativo (come in `iphone_light/crypto_db.save_encrypted_db_single`).

## Dove sta il DB nell’«albero» dell’iPhone

Dropbox su iOS non espone lo stesso path del Mac. In pratica:

1. Installare l’app **Dropbox** e accedere allo stesso account del desktop.
2. Aprire l’app **File** di Apple → sezione **Dropbox** (provider).
3. Navigare nella **stessa cartella** in cui sul Mac hai messo **`conti_di_casa.key`**, **`conti_utente_<hash>.enc`** e **`conti_utente_<hash>_light.enc`** (tutti nella cartella dati, senza sottocartelle dedicate al light).

L’app iOS (SwiftUI) fa scegliere la **cartella** (bookmark sicuro): dentro ci sono `.key` e `*_light.enc` per l’email corretta.

Il nome `conti_utente_<hash>.enc` è determinato dall’email (primi 20 caratteri hex di SHA-256 dell’email in minuscolo), come in `per_user_encrypted_db_path` in `main_app.py` / `iphone_light/crypto_db.py`.

## Crittografia (parità con il desktop)

- **Fernet** (`cryptography` in Python; su iOS librerie equivalenti che implementano Fernet AES-128-CBC + HMAC).
- Stesso file chiave e stesso payload JSON cifrato.

## App iOS (Swift / Xcode)

I sorgenti Swift allineati a login + Fernet sono in **`ios/`**:

- `ios/ContiLightCore/` — decrittazione e login (stessa logica di `light_auth` / `crypto_db`)
- `ios/ContiLightApp/` — SwiftUI (`ContentView`, movimenti, …)
- **`ios/README_XCODE.md`** — passi per collegare i file a un progetto Xcode

## Moduli Python in questa cartella

| File | Ruolo |
|------|--------|
| `crypto_db.py` | Carica/salva `.enc` con Fernet; salvataggio **singolo** (no backup). |
| `light_auth.py` | `load_db_for_email`, `try_login` usando `security_auth.verify_password` e `AppSession`. |
| `probe_cli.py` | Test da terminale senza Tk (vedi sotto). |

## CLI di prova (Mac, dalla root del repo)

```bash
python3 -m iphone_light.probe_cli \
  --enc data/conti_utente_ESEMPIO20HEXQUI.enc \
  --key data/conti_di_casa.key
```

Sostituisci `ESEMPIO20HEXQUI` con i primi 20 caratteri hex dello hash dell’email, oppure usa il path reale del tuo `.enc` completo. Opzione `--dry-save`: dopo un login riuscito, riscrive **solo** il file `.enc` effettivamente usato, senza copia in Application Support.

## Prossimi passi per un’app iPhone reale

- Progetto **Xcode** (SwiftUI): schermata login + scelta cartella dati (bookmark) per `.key` e `*_light.enc`.
- Replicare `try_login` in Swift (PBKDF2-SHA256, 120000 iterazioni, stesso sale e hash del profilo).
- UI ridotta: consultazione movimenti/saldi (read-only all’inizio) prima di abilitare modifiche e salvataggi.
