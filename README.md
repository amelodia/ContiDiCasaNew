# Conti di casa

Applicazione desktop macOS/Python per la gestione dei conti di casa, con database cifrato, saldi consolidati e file light sincronizzabile con il client iPhone.

Il repository nasce dalla migrazione dello storico VB6, ma oggi la fonte operativa e definitiva è il database cifrato corrente (`.enc`). L'import legacy resta nel codice come strumento tecnico/storico, non come funzione ordinaria da usare nell'app.

## Stato attuale

- App desktop completa in `main_app.py`.
- Database cifrato per utente: `conti_utente_<hash>.enc`.
- Chiave Fernet: `conti_di_casa.key`.
- File light iPhone: `conti_utente_<hash>_light.enc`, nella stessa cartella del database completo.
- Backup locale Mac a ogni salvataggio in `~/Library/Application Support/ContiDiCasa/<stem>_backup.enc`.
- Saldi desktop, stampa saldi e app iPhone allineati sulla presentazione a 5 righe.
- Import legacy disabilitato nell'uso normale: il DB cifrato corrente e i suoi backup sono il riferimento per ripristini e continuita.

## Avvio desktop

Da sorgente:

```bash
python3 main_app.py
```

Creazione dell'app macOS:

```bash
scripts/build_macos_app.sh
```

L'app generata si trova in:

```text
dist/ContiDiCasa.app
```

Su macOS, se l'app non e firmata, al primo avvio puo servire aprirla con tasto Ctrl sull'icona e poi **Apri**.

## File dati

Nella cartella dati scelta dall'utente devono stare insieme:

| File | Ruolo |
|------|-------|
| `conti_di_casa.key` | Chiave di cifratura Fernet. |
| `conti_utente_<hash>.enc` | Database completo cifrato dell'utente. |
| `conti_utente_<hash>_light.enc` | Sidecar light per iPhone, rigenerato dal desktop a ogni salvataggio. |

Il file light non sta piu in una sottocartella dedicata: deve stare accanto al `.enc` completo.

Se si usa Dropbox o un'altra cartella sincronizzata, i percorsi del database e della chiave si impostano dalla pagina **Opzioni** dell'app desktop.

## Vincoli di immissione

Le nuove registrazioni sono in euro, con due decimali.

Limiti principali dei campi:

| Campo | Limite |
|-------|--------|
| Nome categoria | 20 caratteri |
| Nota categoria | 100 caratteri |
| Nome conto | 16 caratteri |
| Assegno | 12 caratteri |
| Nota registrazione | 100 caratteri |

Limiti numerici e di struttura:

- importo ammesso: da `-999999999,99` a `+999999999,99`;
- categorie: massimo 100;
- conti: massimo 20;
- i nomi delle categorie sono salvati in maiuscolo, mantenendo l'eventuale segno iniziale `+` o `-`;
- i nomi dei conti sono salvati in maiuscolo; nella creazione di un nuovo conto sono ammesse solo lettere;
- le note di categoria e le note registrazione hanno la prima lettera forzata in maiuscolo;
- il parser accetta `.` e `,` come separatore decimale in input;
- la visualizzazione usa il formato italiano, per esempio `1.234,56`.

## Saldi

La presentazione dei saldi usa 5 righe:

1. Saldi assoluti
2. Di cui, impegni futuri
3. Disponibilita oggi = saldi assoluti - impegni futuri
4. Impegni per carte
5. Disponibilita assoluta = saldi assoluti + impegni per carte

La formula e centralizzata in `balance_engine.py` e riusata da:

- footer saldi desktop;
- stampa saldi;
- generazione del blocco `light_saldi`;
- app iPhone/Swift.

I totali dei saldi escludono i conti carta quando previsto, cosi i conti non piu in uso presenti nello storico non interferiscono con i conti correnti.

## Storico e regole legacy

Le registrazioni storiche restano nel database e possono ancora incidere sui saldi quando vengono annullate o modificate nei casi ammessi.

Regole principali:

- il calcolo dei saldi parte dalla base consolidata e applica le variazioni successive;
- le registrazioni pre-2026 non vengono ricalcolate da zero per ricostruire la base storica;
- le modifiche ammesse su registrazioni pre-2026 continuano a produrre l'effetto contabile corretto;
- sulle registrazioni pre-2022 sono possibili solo modifiche di categoria e note;
- per le registrazioni pre-2022 non e consentito entrare in, o uscire da, `Girata conto/conto`.

Tutti gli importi sono in euro con due decimali. Non sono previsti decimali ulteriori.

## Versione iPhone light

La versione iPhone e separata dalla desktop:

- specifica: `iphone_light/LIGHT_UI_SPEC.md`;
- documentazione tecnica: `iphone_light/README.md`;
- sorgenti Swift: `iphone_light/ios/`;
- moduli Python di supporto/prova: `iphone_light/*.py`.

Il desktop resta l'app completa. Le semplificazioni mobile vanno realizzate nella parte iPhone, non togliendo funzioni al desktop.

## Test

Esecuzione:

```bash
python3 -m unittest discover
python3 -m compileall -q .
```

I test coprono le parti piu delicate: importi euro, saldi consolidati, regole storiche, carte di credito e sidecar light.

## Struttura essenziale

| Percorso | Descrizione |
|----------|-------------|
| `main_app.py` | App desktop Tk. |
| `balance_engine.py` | Logica condivisa dei saldi. |
| `light_enc_sidecar.py` | Creazione e merge del file light. |
| `security_auth.py` | Login, profilo utente e sicurezza. |
| `periodiche.py` | Registrazioni periodiche. |
| `import_legacy.py` | Import storico VB6, conservato come modulo tecnico. |
| `iphone_light/` | Client light iPhone e strumenti di prova. |
| `tests/` | Test automatici. |
| `scripts/build_macos_app.sh` | Build macOS `.app`. |

## Note per sviluppo prudente

- Non usare l'import legacy come scorciatoia per correggere il database operativo.
- Prima di modifiche sui saldi, eseguire i test automatici.
- Tenere separati gli interventi desktop da quelli iPhone.
- Evitare modifiche che cambino retroattivamente lo storico pre-2022, salvo regole esplicite gia previste.
