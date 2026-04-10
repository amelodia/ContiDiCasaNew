# Conti di casa — app iOS da collegare a `iphone_light`

Sorgenti Swift che replicano **Fernet** (file `.enc` / `.key`) e **login** (PBKDF2 come `security_auth.py`), allineati a `iphone_light/light_auth.py` e `crypto_db.py`.

## Requisiti

- **Xcode** recente (consigliato 15+)
- **iOS 17+** sul telefono (per `.fileImporter` in SwiftUI)
- Account e password già configurati sul **desktop**
- File **`.enc`** e **`.key`** raggiungibili da **File** (es. cartella Dropbox sincronizzata)

## Opzione A — Progetto già esistente (es. **ContiTest**)

Se hai già un’app con schermata bianca, di solito manca il contenuto in `ContentView` o i file non sono nel *target*.

1. Apri il progetto **ContiTest** in Xcode.
2. Nel navigatore, tasto destro sulla cartella del gruppo app → **Add Files to "ContiTest"…**
3. Aggiungi la cartella **`ContiLightCore`** (tutti gli `.swift` dentro `iphone_light/ios/ContiLightCore/`).
   - Spunta **Copy items if needed** (opzionale ma consigliato se la copia resta nel progetto).
   - Spunta il **target** della tua app (es. ContiTest).
4. Aggiungi **`ContentView.swift`** da `iphone_light/ios/ContiLightApp/` allo stesso target.
5. **Non** aggiungere `ContiLightApp.swift` se l’app ha già un file con `@main` (es. `ContiTestApp.swift`); altrimenti avresti **due** `@main` e l’errore di compilazione.
6. Apri il file **`ContiTestApp.swift`** (o come si chiama il tuo `@main`) e assicurati che sia:

   ```swift
   WindowGroup {
       ContentView()
   }
   ```

7. Seleziona il **target** → **General** → **Minimum Deployments** → imposta **iOS 17.0** (o superiore).
8. **Build** (⌘B) poi **Run** sul telefono.

## Opzione B — Nuovo progetto da zero

1. **File → New → Project** → **iOS** → **App** → nome es. `ContiLight`, Interface **SwiftUI**, Language **Swift**.
2. Aggiungi al target gli `.swift` di **`ContiLightCore`** e **`ContentView.swift`** come sopra.
3. Sostituisci il contenuto del file `App` generato da Xcode con quello di **`ContiLightApp.swift`**, oppure elimina `ContiLightApp.swift` e nel file `App` di Xcode usa `ContentView()` nel `WindowGroup` (come nell’opzione A).
4. Deployment **iOS 17+**, poi Run.

## Struttura file

| Cartella / file | Ruolo |
|-----------------|--------|
| `ContiLightCore/Base64URL.swift` | Base64 URL-safe (chiave Fernet) |
| `ContiLightCore/FernetDecrypt.swift` | Decrittazione token `.enc` |
| `ContiLightCore/FernetEncrypt.swift` | Crittazione Fernet (salvataggio allineato al desktop) |
| `ContiLightCore/PBKDF2.swift` | PBKDF2-HMAC-SHA256, 120000 iterazioni |
| `ContiLightCore/ContiDatabase.swift` | Caricamento DB, file per-utente, `tryLogin` |
| `ContiLightApp/ContentView.swift` | UI: scelta file, email, password, messaggio |
| `ContiLightApp/ContiLightBiometricLogin.swift` | Face ID / Touch ID: Keychain + `LocalAuthentication` (opzionale) |
| `ContiLightApp/ContiLightUIKitStringPick.swift` | Filtri / Nuove registrazioni: scelta da lista con `UITableView` (tap reattivo) |
| `ContiLightApp/ContiLightApp.swift` | `@main` (solo se non ne hai già uno) |
| `ContiLightApp/Assets.xcassets/` | **App Icon** (da `euro.jpg` scalato a 1024) + immagine **EuroBrand** in login; aggiungi la cartella al target e in **General → App Icons** scegli `AppIcon`. |

## Uso nell’app

1. **Cartella dati** — la stessa cartella del desktop con **`conti_di_casa.key`**, il file **`conti_utente_<hash>_light.enc`** (per l’email usata) e, se serve per riferimento, il `.enc` completo `conti_utente_<hash>.enc`. L’app usa il file **light** per login e movimenti.
2. **`.key`** — tipicamente `conti_di_casa.key` nella cartella scelta.
3. **Email** e **password** come sul desktop.
4. **Accedi** — se tutto è corretto, compare un messaggio con esito e numero indicativo di registrazioni.

## Risoluzione “build failed”

- **Tutti** i file sotto `ContiLightApp/` vanno nel target: `ContentView.swift`, **`MovimentiSchedaViews.swift`**, e la cartella **`Assets.xcassets`** (trascina in Xcode e spunta il target). Se manca `MovimentiSchedaViews.swift`, compaiono errori del tipo *Cannot find `MovimentiSchedaRoute` in scope*.
- **Deployment**: imposta **iOS 17.0** (o superiore); il codice usa API SwiftUI `onChange` in forma iOS 17+.
- **App Icon**: il set `AppIcon` usa **`AppIcon-1024.png`** (non JPEG); se cambi immagine, mantieni PNG 1024×1024 e aggiorna `Contents.json` in `AppIcon.appiconset`.

## Risoluzione “pagina bianca”

- Il `WindowGroup` deve mostrare **`ContentView()`** (o una vista che non sia vuota).
- Tutti gli `.swift` di **ContiLightCore** devono avere la spunta sul **target** dell’app in **Target Membership** (Inspector a destra).

## Face ID / Touch ID

Se aggiungi `ContiLightBiometricLogin.swift` al target, in **Info** del target imposta **Privacy - Face ID Usage Description** (`NSFaceIDUsageDescription`), ad esempio: *«Conti di casa usa Face ID per sbloccare la password salvata in modo sicuro sul dispositivo.»* Senza questa chiave, il primo accesso biometrico può andare in crash.

## Note

- Nessun pacchetto Swift esterno: solo **CryptoKit** + **CommonCrypto** (SDK Apple).
- La UI è volutamente minima (prova login + file); la **LIGHT_UI_SPEC** descrive le schermate complete da implementare in seguito.
