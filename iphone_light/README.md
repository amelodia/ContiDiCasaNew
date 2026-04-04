# Conti di casa — versione light (iPhone / iOS)

Questa cartella **non modifica** l’applicazione desktop (`main_app.py`, `security_auth.py`, …). Definisce requisiti, percorsi e codice riutilizzabile per un **client iOS** separato (Swift/SwiftUI o altro), più un **CLI di prova** su Mac/Linux.

## Separazione obbligatoria desktop / light

| Programma | Percorso | Note |
|-----------|----------|------|
| **Desktop** | `main_app.py` (avvio: `python3 main_app.py`) | Funzionalità **complete** (tutti i filtri Movimenti, stampa, saldo/memoria cassa su Nuovi dati, ecc.). **Non** inserire qui ramificazioni «solo per iPhone» o versioni semplificate della stessa UI. |
| **Light** | App iOS + `iphone_light/*.py` | Login, crypto, probe CLI; la UI ridotta è nel **client mobile**. Requisiti UX in [`LIGHT_UI_SPEC.md`](LIGHT_UI_SPEC.md). |

Se servono comportamenti diversi tra desktop e mobile, si implementano **nel client iOS** (o in moduli sotto `iphone_light/` usati solo da quel client), **mai** accorciando `main_app.py` per conto del telefono.

## Principi (allineati alla tua richiesta)

1. **Account solo da desktop**  
   Primo accesso, verifica email, profilo e file `conti_utente_<hash>.enc` restano sul **desktop**. Su iPhone: **solo login** con **email e password** già presenti nel DB.

2. **Login senza immagini, senza backdoor**  
   Il desktop usa Pillow + JPEG e la sequenza Ctrl+Z / Ctrl+X (backdoor). La versione light deve offrire **solo** campi email/password e pulsante Accedi — nessun bypass amministrativo da UI.

3. **Nessun «accesso non registrato»**  
   Sul mobile ha senso solo l’utente con password impostata sul desktop (stesso `user_profile` / PBKDF2 di `security_auth.py`).

4. **Database su Dropbox**  
   I file restano quelli esistenti:
   - `conti_di_casa.key` (chiave Fernet)
   - `conti_di_casa.enc` e/o `conti_utente_<hash>.enc` nella stessa cartella sincronizzata (es. `…/Dropbox/.../data/` sul Mac)

5. **Nessun backup locale aggiuntivo**  
   Sul desktop `save_encrypted_db_dual` scrive anche in Application Support. Su iPhone: **solo** riscrittura del file `.enc` operativo (come in `iphone_light/crypto_db.save_encrypted_db_single`).

## Dove sta il DB nell’«albero» dell’iPhone

Dropbox su iOS non espone lo stesso path del Mac. In pratica:

1. Installare l’app **Dropbox** e accedere allo stesso account del desktop.
2. Aprire l’app **File** di Apple → sezione **Dropbox** (provider).
3. Navigare nella **stessa cartella** in cui sul Mac hai messo `data/conti_di_casa.enc` e `data/conti_di_casa.key` (o la cartella che sincronizzi per il progetto).

L’app iOS dovrà:

- far scegliere all’utente i file **.enc** e **.key** (document picker / `UIDocumentPickerViewController`), **oppure**
- usare le **API Dropbox** (OAuth) con path noto (es. `/Apps/ContiDiCasa/...`) — da definire in fase di progetto.

Il nome `conti_utente_<hash>.enc` è determinato dall’email (primi 20 caratteri hex di SHA-256 dell’email in minuscolo), come in `per_user_encrypted_db_path` in `main_app.py` / `iphone_light/crypto_db.py`.

## Crittografia (parità con il desktop)

- **Fernet** (`cryptography` in Python; su iOS librerie equivalenti che implementano Fernet AES-128-CBC + HMAC).
- Stesso file chiave e stesso payload JSON cifrato.

## Moduli Python in questa cartella

| File | Ruolo |
|------|--------|
| `crypto_db.py` | Carica/salva `.enc` con Fernet; salvataggio **singolo** (no backup). |
| `light_auth.py` | `load_db_for_email`, `try_login` usando `security_auth.verify_password` e `AppSession`. |
| `probe_cli.py` | Test da terminale senza Tk (vedi sotto). |

## CLI di prova (Mac, dalla root del repo)

```bash
python3 -m iphone_light.probe_cli --enc data/conti_di_casa.enc --key data/conti_di_casa.key
```

Opzione `--dry-save`: dopo un login riuscito, riscrive **solo** il file `.enc` effettivamente usato (principale o per-utente), senza copia in Application Support.

## Prossimi passi per un’app iPhone reale

- Progetto **Xcode** (SwiftUI): schermata login + document picker per `.enc` / `.key` (o integrazione Dropbox SDK).
- Replicare `try_login` in Swift (PBKDF2-SHA256, 120000 iterazioni, stesso sale e hash del profilo).
- UI ridotta: consultazione movimenti/saldi (read-only all’inizio) prima di abilitare modifiche e salvataggi.
