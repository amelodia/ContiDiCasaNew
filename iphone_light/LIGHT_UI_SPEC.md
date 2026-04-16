# Specifica UI «light» (client iPhone / iOS)

Questo documento descrive il comportamento **semplificato** previsto per il **client mobile**.  
Non va implementato in `main_app.py`: l’app **desktop** resta quella completa.

## Percorsi di codice

| Ambiente | Dove si lavora |
|----------|----------------|
| **Desktop** (Tk, Mac/Windows) | Solo `main_app.py` e moduli condivisi (`security_auth.py`, …) — funzionalità complete. |
| **Light** (iPhone) | App nativa (es. SwiftUI) + moduli in `iphone_light/` (`light_auth.py`, `crypto_db.py`, …). |

**Regola:** nessuna semplificazione “light” dentro `main_app.py` salvo decisione esplicita di introdurre un *flag* documentato (sconsigliato: meglio due codepath o due app).

---

## Pagina Movimenti (light)

- Ricerca **solo per intervallo temporale fisso**: **ultimi 12 mesi**, **date future comprese**, ordine **dalla più recente alla più vecchia**.
- **Nessuna** ricerca per numero di registrazione, **nessuna** scelta manuale dell’intervallo date (oltre al fisso sopra).
- **Nessun** filtro su importo, assegno o nota testuale.
- Filtri previsti: **Categoria** e **Conto** (con azioni tipo Cerca / Pulisci coerenti).
- **Saldi**: sempre disponibili; opzionale pulsante **Mostra / Nascondi saldi**.
- I saldi in app provengono **solo** dal blocco JSON **`light_saldi`** nel `*_light.enc` (file **nella stessa cartella** del `.enc` completo sul desktop, senza sottocartelle). Il desktop li calcola con `compute_light_saldi_snapshot` / `saldi_footer_amount_vectors` in `main_app.py` (stessi numeri del footer **Saldi**: assoluti, alla data, spese future, **spese per carte di credito** sul conto di riferimento, disponibilità; righe `credit_card`; totali non-carta). Se manca, l’app mostra «Dati mancanti» e non calcola saldi dai movimenti nel light. Dopo ogni salvataggio desktop il sidecar si rigenera. All’accesso iOS con file completo, `recomputeLightSaldiFromFullDb` allinea il light. Al salvataggio iOS (futuro), `applyNewRecordToLightSaldi` aggiorna i saldi base; le colonne CC derivate restano coerenti dopo sync/ricomputo completo.
- **Carte di credito (light)**: in «Nuove registrazioni» l’elenco conti indica carta e **conto di riferimento** (solo informativo). **Nessuna** funzione di verifica estratto su iPhone (né PDF né memoria verifica).
- **Nessuna stampa** (né ricerca né saldi).

## Pagina nuove registrazioni (light)

- **Nessun** “Immetti saldo di cassa” e **nessuna** “Memoria di cassa” (né tasti né campi dedicati).

## Riferimento implementativo desktop

Per allineare logica dati (filtri date, ordinamento, esclusione dotazioni, ecc.) usare come riferimento il codice in `main_app.py` sul branch desktop, **senza** rimuovere funzioni da quel file per conto del mobile.
