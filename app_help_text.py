"""Testo della scheda «Aiuto» (manuale utente Conti di casa, desktop)."""

CDC_HELP_BODY = """
INTRODUZIONE
L’applicazione serve a tenere la contabilità familiare o personale: registrazioni (entrate/uscite), categorie, conti, saldi e verifica rispetto agli estratti conto in PDF. I dati sono salvati in un database cifrato sul disco (file .enc) insieme a un file chiave (.key): conserva copie di sicurezza e non condividere la chiave.

AVVIO, DROPBOX E FILE
Prima dell’apertura del database cifrato il programma può attendere che i file nella cartella sincronizzata (es. Dropbox) risultino stabili, per evitare di leggere un file incompleto. Se il computer è stato avviato da pochi minuti, può comparire una richiesta di conferma sull’aggiornamento di Dropbox prima del caricamento.
Nella stessa cartella dati devono stare il file .key, il file .enc completo dell’utente e, se usi l’app mobile «light», il file *_light.enc nella stessa cartella (non in sottocartelle dedicate). L’import da archivi legacy scrive in legacy_import/ (non dentro la cartella dati principale se così configurato). Dopo uno spostamento della cartella aggiorna i percorsi in Opzioni.

ACCESSO
All’avvio inserisci email e password del profilo (o le credenziali previste dalla tua installazione). L’interfaccia di login usa un’immagine JPEG incorporata; è richiesto Pillow. Per dettagli su registrazione profilo, posta e primo accesso vedi la scheda Opzioni.

PIANO CONTI (REGOLE GENERALI)
Nel piano devono sempre esistere: la categoria «Girata conto/conto», la categoria «Consumi ordinari», il conto «Cassa» e il conto «VIRTUALE». Non sono eliminabili né svuotabili dalle opzioni. I nomi di «Consumi ordinari» e «Girata conto/conto» non si modificano dalla scheda Categorie.

SCHEDA «MOVIMENTI E CORREZIONI»
Qui consulti e correggi le registrazioni già in archivio.
• Filtri: per data, conti, categorie, importi, testo in nota o assegno, ecc. Il preset «ultimi N mesi» usa come riferimento la data odierna (le date future nel database restano comunque nel periodo se ricadono nell’intervallo).
• Griglia: elenco delle registrazioni risultanti dai filtri; puoi aprire la correzione su una riga.
• Correzione registrazione: la data può essere scelta con il calendario a comparsa, con gli stessi vincoli validi al salvataggio (anno contabile, intervalli consentiti, filtri data se attivi). Per «dal conto» e «al conto» l’elenco è ordinato alfabeticamente ma la preselezione segue il nome conto della registrazione, non la posizione nella lista.
• Importi in euro: cifre e separatori . e , in stile italiano; i tasti + e − (tastiera) agiscono solo sul segno iniziale lasciando il corpo numerico invariato, poi il cursore va in fondo. Dove il saldo non ammette segno, +/− sono ignorati. Incolla e scorciatoie sono gestiti in modo coerente con il resto dell’app.
• Stampa «ricerca»: genera un riepilogo delle registrazioni correntemente filtrate (anteprima / stampa).
• In basso trovi i totali e le colonne dei saldi (inclusi assoluti, disponibilità, carte di credito e righe descrittive come «Di cui, spese future» dove previsto). Il conto VIRTUALE non compare tra i saldi «reali» della pagina.

SCHEDA «NUOVE REGISTRAZIONI»
La pagina ha due sotto-schede: «Nuova registrazione» (singola immissione) e «Registrazioni periodiche» (elenchi e creazione di registrazioni ricorrenti gestite dal programma). Passa dall’una all’altra con i pulsanti in alto nella stessa area.
Immissione di nuove registrazioni contabili: compila data, categorie, conti, importo, nota e eventuale assegno secondo le regole del tipo di operazione.
• Girata conto/conto: il secondo conto non può essere un conto carta di credito (né in immissione singola né nelle registrazioni periodiche in girata). Per una girata con secondo conto Cassa, il campo Nota può essere preimpostato con «Aut », la data breve e uno spazio finale, per agevolare la digitazione, salvo quando il primo conto è Cassa o un conto carta di credito (in quel caso si usa il modello «Giroconto» come negli altri casi); al focus, se il testo è quello modello «Aut gg/mm», il cursore si posiziona dopo lo spazio finale. Per giroconti verso/da VIRTUALE la nota non viene preimpostata a «Giroconto».
• Dopo ogni inserimento andato a buon fine restano preimpostati data, categoria e conto dell’ultima registrazione mentre resti sulla pagina di immissione; uscendo dalla scheda «Nuove registrazioni» i default tornano allo stato iniziale (es. oggi, Consumi ordinari, Cassa). «Concludi immissione» senza importo compilato passa ai Movimenti senza ulteriori conferme; con importo compilato vale la conferma d’inserimento come per «Conferma immissione». Cambiando pagina dalla barra in alto con importo compilato viene richiesta la stessa conferma prima di uscire.
• Conto VIRTUALE: compare nel menu conti solo se la categoria è «Girata conto/conto», in ultima posizione. Non si possono impostare entrambi i conti della girata su VIRTUALE: in quel caso l’altro conto torna a Cassa. Le registrazioni che coinvolgono solo il virtuale hanno regole dedicate (conferma doppia, non modificabili e non eliminabili). In «fase scarico» resti sulla pagina di immissione finché il saldo virtuale non torna a zero; le categorie ammesse escludono la Girata; il conto è solo VIRTUALE; le registrazioni di scarico non alterano i saldi reali ma compaiono nei Movimenti e nelle analisi per categoria.
• Memoria virtuale: la prima girata con VIRTUALE incide sul conto non virtuale coinvolto; le successive in fase scarico aggiornano solo il saldo virtuale e le categorie.

SCHEDA «VERIFICA»
Confronto tra movimenti registrati ed estratto conto in PDF per il conto scelto. Avvio sessione, immissione manuale o automatica delle voci, chiusura con salvataggi previsti. Non uscire dalla scheda Verifica con una sessione ancora aperta: usa «Chiudi verifica» (o l’equivalente) prima di cambiare pagina.
«Stampa risultati» (alla fine della verifica) salva il riepilogo come file PDF nella stessa cartella radice degli estratti impostata in Opzioni, con nome del tipo «Verifica conto <nome conto> data aaaa_mm_gg.pdf». Se la cartella non è impostata o non è valida, viene offerto un file temporaneo e un messaggio ricorda il nome suggerito.
Per i PDF degli estratti, in Opzioni si imposta una cartella radice unica; nella scheda Conti i «Nomi dei file pdf per le verifiche automatiche» identificano il prefisso del file (mese o trimestre) usato dalla ricerca automatica.

SCHEDA «STATISTICHE» E «BUDGET»
• Prospetti **per categoria** (tabellone budget annuale per categoria, statistiche per categoria, somme coerenti con quel modello): si usano **tutte** le registrazioni **salvo** quelle **annullate**, i duplicati import da escludere (stessa logica dei saldi), le **dotazioni iniziali** (categoria codice 0) e le registrazioni di categoria **«Girata conto/conto»**. Contano gli importi **amount_eur** con la **data della registrazione** (`date_iso`): rientrano quindi anche spese imputate a **carta di credito** e movimenti sul **conto VIRTUALE** (es. scarichi in fase memoria virtuale), perché riflettono l’**attribuzione di categoria** e la data di impegno contabile lato categorie.
• Prospetti **per conto** (statistiche sui conti, flussi mensili/annui esposti lì) e **sintesi di budget** (totali mensili «movimenti» affiancati ai saldi reali): non si accumulano movimenti sulle colonne **carta di credito** né sul conto **VIRTUALE**; sulle **girate conto/conto** si contano solo gli effetti sui conti che **non** sono né carta né VIRTUALE (movimenti effettivi sui conti ordinari). Qui la logica è quella del **saldo e dei flussi reali** sui conti prescelti; la **data** usata è sempre quella della registrazione, ma una spesa registrata in categoria su carta può coincidere nel tempo con l’addebito sul conto corrente solo in un momento diverso (altro mese).
• Dagli anni in cui nel piano sono presenti **conti carta** e/o il **conto VIRTUALE**, i **totali mensili per categoria** e i **totali mensili lato conti** (non carta, non virtuale) possono **non coincidere**: è atteso. Negli anni precedenti, senza quella distinzione operativa, i due aggregati restano **allineati** sullo stesso insieme di movimenti (salvo le esclusioni per categoria indicate sopra).
• Il tabellone budget confronta ancora, **per ogni categoria**, movimenti (regole per categoria) e budget; la riga dei totali e la sintesi usano dove indicato le regole **per conto** per i totali mensili «movimenti» da affiancare ai saldi.

SCHEDA «OPZIONI»
• Collegamenti per aprire le schede Categorie e Conti (il piano conti compare come schede aggiuntive nella barra in alto solo quando attivato da qui o dal flusso previsto).
• Posta e sicurezza: configurazione SMTP/IMAP, verifica, notifiche amministrative, ripetizione primo accesso o reset (operazioni irreversibili: leggi sempre i messaggi di conferma).
• Percorsi del file dati cifrato e della chiave, backup, ripristino, import legacy da cartelle predefinite o personalizzate.
• Altre preferenze utente (intestazioni stampa, cartelle verifica, ecc.) secondo quanto mostrato nella pagina.

SCHEDE «CATEGORIE» E «CONTI»
Elenco unificato del piano (tutti gli anni del database). Categorie: codice, nome, nota; correzioni riga per riga con conferma; aggiunta nuove categorie nei limiti numerici del programma; vincoli sui nomi «bloccati» e sulla nota della Girata. Conti: saldi, nomi dei file pdf per le verifiche automatiche (salvataggio con «Salva nomi base pdf»), congelamento quando il conto è fermo e a saldo zero (le registrazioni restano in archivio e in ricerca; il conto esce da Saldi e da nuove registrazioni); Cassa e VIRTUALE non si congelano da qui. Uscendo dalla scheda Conti con modifiche ai nomi base PDF non salvate può comparire un avviso.

IMPORT LEGACY
Da Opzioni (o percorsi indicati nella documentazione di progetto) puoi importare dati da formati precedenti: in caso di annullamento dell’import guidato, le modifiche non devono essere applicate.

APP «LIGHT» (MOBILE)
Esiste un’applicazione iOS leggera che lavora su un estratto cifrato (*_light.enc): le regole di allineamento con il database completo sono descritte nella documentazione di quell’app; sul desktop restano validi file e cartella condivisi sopra citati.

SUGGERIMENTI
Tieni aggiornati i percorsi in Opzioni dopo spostamenti di cartella; esegui backup periodici del .enc e del .key; dopo modifiche importanti verifica i saldi e un campione di movimenti in Movimenti.
""".strip()
