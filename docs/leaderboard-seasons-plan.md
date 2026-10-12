# Classifica tavoli + Season — piano e stato (2026-10-12)

Ripensamento del sistema di classifica del tavolo per supportare più modalità di
gioco, e introduzione delle **season** per Location.

> Stato: **nuovo sistema di classifica IN PRODUZIONE** (fasi 0–4b, 2026-10-12).
> **TODO**: fase 5 (season) e fase 6 (pulizia). Vedi §5 "Rilascio in produzione".

## Situazione attuale

- `Player.position` (default `99` = "non compilata") + `Player.score`. Supporta solo
  il tutti contro tutti.
- Unico punto di scrittura: `update_player_position` in `webapp/api/views.py`.
- Gate: `Game.leaderboard_enabled` (default off, acceso a mano dall'admin; **da eliminare**, vedi §1
  "Senza classifica"); finestra di modifica governata da
  `Table.leaderboard_status` (derivato dal lifecycle phase, vedi `docs/table-lifecycle.md`).
- Statistiche Location (`location_views.py`, pagina location): giochi più giocati,
  top winners per gioco, classifica giocatori a **medaglie** (1°/2°/3° + partite) su
  tutto lo storico.

## Principio: la classifica si compila a partita finita

Le squadre non vanno definite prima di giocare: sono un **dato del risultato**, come
il punteggio. Conseguenza: "ruoli nascosti / traditore" non è un caso speciale, è una
partita a squadre; "1 contro tutti" / "pochi contro molti" sono squadre asimmetriche,
senza modellare l'asimmetria.

## 1. Risultato del tavolo

### Modalità di risultato

```
Game.default_result_mode   suggerimento (default: none)
Table.result_mode          valore effettivo, precompilato dal gioco, modificabile
```

Valori (tre modalità + "senza classifica"):

| Modalità            | Struttura                      | Cosa si inserisce                           |
|---------------------|--------------------------------|---------------------------------------------|
| `ffa` (tutti c. tutti) | ogni giocatore è un lato    | posizione per giocatore (pari merito ok) **oppure** "ha vinto il gioco" |
| `teams`             | gruppi di giocatori            | squadra + posizione della squadra           |
| `coop`              | un solo gruppo vs il gioco     | vinto/perso (+ punteggio facoltativo)       |
| `none` (senza classifica) | nessuna                  | niente (es. giochi di ruolo, partite di prova) |

**Niente modalità semi-cooperativa** (decisione 2026-10-12). I semi-coop (Archipelago,
Legendary, Cutthroat Caverns, Dead of Winter) si compilano come `ffa`: se il gioco è
stato battuto è una classifica normale; se ha vinto il gioco si attiva l'interruttore
**"Ha vinto il gioco: avete perso tutti"** e le posizioni non vengono chieste. Il gioco
può suggerire l'interruttore (es. renderlo visibile in evidenza), ma la modalità è `ffa`.

### Senza classifica (`none`) — sostituisce `Game.leaderboard_enabled` (deciso 2026-10-12)

`leaderboard_enabled` serviva **solo** a escludere i giochi senza classifica: viene eliminato e
assorbito dal valore `none` della modalità.

- **Default di `Game.default_result_mode` = `none`**: si usa in caso di dubbio.
- Gioco con suggerimento `none` (es. gioco di ruolo): il tavolo nasce senza classifica, la sezione
  mostra "Questa partita non prevede una classifica". Autore/manager/superadmin possono
  **"Attiva la classifica"** (parte da `ffa`, con l'avviso ambra della modalità non suggerita).
- Gioco con classifica: un singolo tavolo può scegliere `none` (es. partita di prova/spiegazione)
  con il link **"Questa partita non prevede una classifica"** sotto il selettore (non è un quarto
  pulsante). La scelta si applica subito, senza dati da inserire.
- Cambiare modalità resta un permesso di autore/manager/superadmin: un giocatore non può attivare
  né disattivare la classifica.
- Statistiche: i tavoli `none` contano in "tavoli giocati" e "giochi più giocati", **non** nelle
  classifiche di season.

### Suggerimento automatico da BGG (nuovi import)

All'import da BGG (`services/bgg.py`) si propone `default_result_mode` dai dati BGG:

| Dato BGG                                         | Suggerimento |
|--------------------------------------------------|--------------|
| tipo `rpgitem` (gioco di ruolo)                  | `none`       |
| meccanica "Cooperative Game"                     | `coop`       |
| meccanica "Team-Based Game"                      | `teams`      |
| meccanica "Semi-Cooperative Game"                | `ffa`        |
| tipo `boardgame` senza le meccaniche sopra        | `ffa`        |
| dati mancanti / fetch fallito                    | `none`       |

Note:
- Le meccaniche si riconoscono **per nome** (link `boardgamemechanic` della risposta `/thing`);
  verificare nomi/id reali contro l'API in fase di sviluppo.
- Priorità in caso di più meccaniche: Semi-Cooperative → `ffa` prima di Cooperative (molti semi-coop
  hanno anche il tag Cooperative); poi Cooperative → `coop`; poi Team-Based → `teams`.
- **Coerenza con "none in caso di dubbio"**: BGG non ha un tag "competitivo", quindi `ffa` si deduce
  sempre per esclusione. Applicare alla lettera "nel dubbio none" renderebbe `none` quasi tutti i
  giochi da tavolo, cioè la situazione di oggi. Per questo un `boardgame` BGG senza tag coop/squadre
  diventa `ffa`, e `none` resta per i giochi di ruolo, i dati mancanti e i giochi creati a mano.
- È solo un suggerimento: correggibile dall'admin e sul singolo tavolo.
- Sotto l'editor della classifica, card "Vuoi segnalarci un errore o una modalità suggerita migliore
  per questo gioco? Contattaci": link a `contacts?topic=result-mode&game=<slug>`, che precompila il
  messaggio (IT/EN) con il nome del gioco. Il testo è costruito lato server, mai preso dall'URL.

### Campi

```
Game.default_result_mode   ffa / teams / coop / none   (default none)
Table.result_mode      ffa / teams / coop / none
Table.game_outcome     esito dei giocatori CONTRO IL GIOCO: won / lost / null
                       coop → obbligatorio (won/lost)
                       ffa  → null di norma; lost = "ha vinto il gioco, avete perso tutti"
                       teams → sempre null
Table.coop_score       int null, solo coop (es. Hanabi 0–25)
                       (deciso 2026-10-12: resta sul tavolo, non ripetuto su Player.score)

Player.team            etichetta/numero gruppo, vuoto in ffa e coop
Player.position        posizione valida per le medaglie (vedi sotto)
                       in teams = posizione DELLA SQUADRA, ripetuta su ogni membro
                       null = non compilata / nessuna medaglia  (pulizia: oggi 99)
Player.score           invariato (diventa inseribile da UI, facoltativo)
```

### `position` è sempre "posizione per le medaglie"

Niente campo separato: è la **UI di compilazione** a scrivere `position` già corretta
per ogni modalità, così oro/argento/bronzo restano `position=1/2/3` e le query
esistenti non cambiano.

| Caso                         | Cosa chiede la UI                      | `position` scritta                         |
|------------------------------|----------------------------------------|--------------------------------------------|
| `ffa`                        | posizione per giocatore                | come inserita (pari merito ok)             |
| `ffa` + ha vinto il gioco    | solo l'interruttore                    | null a tutti                               |
| `teams`                      | squadra + posizione della squadra      | posizione della squadra su ogni membro     |
| `coop` vinto                 | solo vinto/perso                       | 1 a tutti (**vittoria coop = oro**)        |
| `coop` perso                 | solo vinto/perso                       | null a tutti                               |

Costo accettato: quando vince il gioco non si registra l'ordine dei giocatori (non conta comunque).

### Esito normalizzato (salvato su `Player`)

Campo **derivato e persistito**, così le aggregazioni restano lato DB (`Count(filter=...)`):

```
Player.outcome    won / lost / draw / null (non compilata)
```

| Caso                      | `outcome`                                                          |
|---------------------------|--------------------------------------------------------------------|
| `ffa`                     | position 1 → won (pari merito al 1° = tutti won); altri → lost; tutti pari → draw |
| `ffa` + ha vinto il gioco | tutti lost                                                         |
| `teams`                   | squadra in pos. 1 → won; altre → lost (tutte pari → draw)          |
| `coop`                    | `game_outcome` per tutti                                           |

Ricalcolo in **un solo punto**: `Table.recompute_outcomes()`, chiamato in transazione
ogni volta che cambia posizione/squadra/`result_mode`/`game_outcome`.

## 2. Season

```
Season
  location     FK Location
  name         "Autunno 2026"
  start_date
  end_date     null finché attiva
  vincolo:     al massimo una season con end_date null per location (partial unique)
  vincolo:     intervalli di date non sovrapposti per location (validazione)

Table.season   FK Season, null
```

### Assegnazione tavolo → season (opzione A)

- Conta la **data del tavolo** (`table.date`), non la data di compilazione della classifica.
- Il FK `Table.season` è salvato (query + stabilità), valorizzato dalla data.
- Tavoli che contano: `event IS NULL` (no tavoli di eventi), esclusi i tornei, e
  `result_mode != none`.
- **Buchi permessi**: si può chiudere una season senza aprirne un'altra (es. pausa
  estiva). I tavoli nel buco hanno `season = null` e contano solo nello storico.
- **Date modificabili**: modificare start/end di una season riassegna i FK dei tavoli
  interessati (ricalcolo).

### Prima season e "Stagione Zero"

- Location senza season: tutto resta com'è (statistiche su tutto lo storico).
- Alla creazione della **prima** season viene creata automaticamente una season passata
  di default **"Stagione Zero"** (*Season Zero*), da data del primo tavolo a
  `start_date nuova − 1 giorno`, e i tavoli precedenti vi vengono associati.

### Permessi

- Season attiva: comportamento attuale (finestra `leaderboard_status`).
- Season chiuse: classifica modificabile **solo da superadmin e manager della Location**.
- Creazione/chiusura/modifica season: manager della Location (area `/manage/`).

### Ospiti

Gli ospiti (`GuestProfile`) entrano in classifica, aggregati per `guest_profile_id`.
Limite accettato: lo stesso amico portato da due utenti diversi = due identità.
Futuro: profilo ospite **riscattabile** da un utente registrato (merge delle partite).

## 3. Statistiche nella pagina Location

| Blocco                                  | Perimetro                                  |
|-----------------------------------------|--------------------------------------------|
| Giochi più giocati, gamers totali, tavoli giocati | **tutto lo storico**              |
| Classifica giocatori (medaglie)         | **season attiva** + selettore per le precedenti |
| Classifica per gioco (top winners)      | **season attiva** + selettore (v1)          |

Location senza season: classifiche su tutto lo storico, come oggi.

**Ordinamento classifica giocatori** (deciso): oro → argento → bronzo → **partite giocate
(più partite = più in alto)**, come oggi.

### Notifiche

Ai **follower della Location** (`LocationFollower`), stesso canale/pattern di `new_table`:

```
NotificationType.SEASON_STARTED   apertura di una season
NotificationType.SEASON_ENDED     chiusura di una season (link alla classifica finale)
```

**Una sola notifica per azione del manager.** Aprire una season quando ce n'è già una attiva
chiude la precedente, ma si invia **solo `SEASON_STARTED`**, con un riferimento alla season
appena conclusa e un link alla sua classifica finale (es. "È iniziata *Inverno 2027*. *Autunno 2026*
è terminata: guarda la classifica finale"). `SEASON_ENDED` parte solo quando una season viene
chiusa **senza** aprirne un'altra (inizio di un buco, es. pausa estiva).

La creazione automatica della "Stagione Zero" **non** notifica.

## 4. UI di compilazione (in produzione dalla fase 4a)

Approccio **A + D**: drag & drop esteso, nella stessa sezione della pagina tavolo.

- **Selettore modalità** in cima (Tutti contro tutti / Squadre / Cooperativo; pulsanti a larghezza proporzionale al testo, così stanno su una riga anche a 320px), precompilato dal gioco.
  Cambiarlo dopo il salvataggio azzera la classifica, previa conferma.
  La modalità resta **libera** (nessun vincolo per gioco): se si sceglie una modalità diversa da
  quella suggerita compare un **avviso ambra** ben visibile con il pulsante "Usa <suggerita>".
- **Tutti contro tutti**: lista trascinabile (SortableJS come oggi) + pulsante **"="** su ogni riga
  (pari merito con chi sta sopra, ranking 1-1-3) + **punteggio facoltativo** per riga con
  **"Ordina per punteggio"** (crea i pari merito in automatico; opzione "vince il più basso") +
  interruttore **"Ha vinto il gioco: avete perso tutti"**.
- **Squadre**: 1) etichette A/B/+ per giocatore (scorciatoia "1 contro tutti"); 2) blocchi squadra
  trascinabili per l'ordine d'arrivo, con "=" e punteggio facoltativo per squadra.
  Validazione: tutti assegnati, almeno 2 squadre.
- **Coop**: pulsanti grandi Vinto / Perso + punteggio di gruppo facoltativo.
- `Player.score` diventa **inseribile da UI, facoltativo**.
- Maniglia di trascinamento = icona **grip a 6 puntini** (non le due linee di oggi, che si confondevano
  con il pulsante "=" del pari merito).

### Permessi

| Azione                    | Chi                                                              |
|---------------------------|------------------------------------------------------------------|
| Cambiare modalità         | superadmin, autore del tavolo, manager della location            |
| Aggiornare la classifica  | superadmin, autore del tavolo, manager della location, giocatori del tavolo |

(Per le season chiuse vale la restrizione del §2: solo superadmin e manager.)

### Endpoint

Nuovo endpoint unico **"salva risultato"** al posto di `update_player_position`: riceve tutto
insieme e chiama `recompute_outcomes()` una sola volta in transazione.

```json
{ "result_mode": "teams", "game_outcome": null, "coop_score": null,
  "players": [ { "id": 1, "team": "A", "position": 1, "score": 12 }, … ] }
```

### Prototipo

(RIMOSSA in fase 4b) Pagina **`/dummy-table/`** (include anche "Senza classifica" tra le modalità di default del gioco) (pubblica anche in produzione per farla provare agli utenti, `X-Robots-Tag: noindex`;
`static_page_views.dummy_table`,
template `staticpages/dummy_table.html`): stato tutto lato client, pannello per simulare
ruolo / modalità di default del gioco / numero giocatori / ospite, e anteprima del payload.
Da rimuovere quando la UI viene portata nella pagina tavolo reale.

Comportamenti confermati sul prototipo: trascinare una riga le toglie il "=" (il pari merito
non segue chi viene spostato); cambiare modalità azzera squadre, pari merito ed esito coop ma
conserva punteggi e ordine dei giocatori.

## 5. Rilascio in produzione (deciso 2026-10-12)

Requisito: **massima retrocompatibilità, nessun risultato perso o alterato**. Principio:
**prima si aggiunge, poi si cambia, solo alla fine si toglie**. Ogni fase è un deploy separato,
verificato prima di passare alla successiva.

Punti del codice che oggi dipendono da `position=99` / `leaderboard_enabled` (da tenere allineati):
`table_views.py` (detail + `leaderboard_visible`), `tables/_table_leaderboard.html`,
`table_detail.html` e **`events/event_table_detail.html`** (stesso endpoint), `location_views.py`
(statistiche medaglie), `profile_views.py` (vittorie), `api/views.py` (`update_player_position`),
`signals.py`, `services/tables.py`, `services/bgg.py`, `admin.py`.

### Fase 0 · Rete di sicurezza
- Backup prima di ogni rilascio che tocca il DB: `heroku pg:backups:capture -a boardgamers`.
- **Fotografia dei risultati**: `python manage.py leaderboard_snapshot` (JSON su stdout: ogni
  Player con tavolo, utente/ospite, posizione normalizzata 99→null, punteggio) e
  `--compare FILE` (esce con errore se un risultato manca o è cambiato; i nuovi giocatori
  sono solo informativi). Il confronto va rifatto dopo ogni fase.
- **Prova generale in locale su copia di produzione** (ripristino del backup nel DB locale)
  prima di ogni fase che tocca i dati.

Fotografia di produzione (2026-10-12, `snapshot_phase0.json`, fuori da git): 2090 giocatori,
512 con posizione, 129 tavoli con risultati. Nessun tavolo compilato a metà (tutti i giocatori di un
tavolo hanno posizione oppure nessuno). Due casi anomali da rispettare nel popolamento (fase 2):
- tavolo **60**: solo posizioni 2 e 3, nessun 1° (probabilmente il vincitore è stato rimosso) →
  nessun `won`, posizioni lasciate come sono;
- tavolo **92**: due giocatori al 4° posto (pari merito già presente nei dati) → va rispettato.

### Fase 1 · Solo aggiunte al DB (nessun cambiamento visibile)
Nuovi campi facoltativi/con default + modello `Season`. `position`, 99 e `leaderboard_enabled`
restano intatti; il codice si comporta come oggi.

Implementata nella migrazione `0072_leaderboard_modes_and_seasons` (solo `ADD COLUMN` / `CREATE`).
Le due colonne `NOT NULL` (`Game.default_result_mode`, `Player.team`) usano **`db_default`**: su
Heroku le migrazioni girano prima che il nuovo codice sia attivo, e senza default nel DB il codice
vecchio fallirebbe nell'inserire giocatori/giochi in quella finestra. Provata sulla copia di
produzione: migrate → confronto OK → insert "stile codice vecchio" OK → rollback a 0071 → confronto
OK → riapplicata → confronto OK; pagine tavolo/location/home/giochi rispondono 200.

### Fase 2 · Popolamento nuovi campi (dati vecchi non toccati)
- `Table.result_mode` dei tavoli esistenti **ricavato dai loro dati, non dal gioco**: tavolo con
  posizioni compilate → `ffa` (è stato giocato così), anche se il gioco ora suggerisce coop/squadre.
- `Player.outcome` calcolato dalle posizioni esistenti (99 → null).
- `Game.default_result_mode` caricato da **`webapp/data/game_result_modes.csv`** (versionato, solo
  `slug,mode`, dati pubblici; generato dalla revisione di `leaderboard_modes_prod.csv`, che resta
  fuori da git). Prima del caricamento rivedere le 7 righe "DA VERIFICARE".
- Verifica: `leaderboard_snapshot --compare` = OK.

Implementata con il comando **`leaderboard_backfill`** (`--dry-run` per l'anteprima, tutto in una
transazione, idempotente, non tocca mai `position`/`score`, scrive con `update`/`bulk_update` quindi
niente signal né notifiche) e il metodo **`Table.recompute_outcomes()`** (unica fonte degli esiti,
riusato dalla nuova UI). Controllo di coerenza finale: se un giocatore con posizione resta senza esito
il comando fallisce e annulla tutto. Prova sulla copia di produzione: 658 giochi aggiornati
(536 ffa, 89 coop, 33 teams; 16 restano none), 129 tavoli marcati `ffa`, esiti 128 won / 384 lost
(= 128 primi posti), tavolo 60 tutti lost, tavolo 92 pari merito al 4° rispettato; confronto OK;
seconda esecuzione senza modifiche. Regole squadre/coop/"ha vinto il gioco"/pareggio verificate in
transazione annullata.

**Stato rilascio (2026-10-12)**: fase 0 ✅ (backup + fotografia `snapshot_phase0.json`),
fase 1 ✅ (migrazione 0072 in produzione, confronto OK), fase 2 ✅ (`leaderboard_backfill` eseguito in
produzione con numeri identici alla prova; confronto OK).
Fase 3 ✅ in produzione (backfill rilanciato dopo il deploy, confronto OK).
Fase 4a ✅ in produzione (nuovo editor + endpoint; confronto OK dopo il deploy).
Fase 4b ✅ rilasciata (coop/squadre aperti, `/dummy-table/` rimossa).
Fase 5 ⏳ TODO · Fase 6 ⏳ TODO.

(Risolto) Tra la fase 2 e la 3 il vecchio endpoint scriveva solo `position`: il backfill è stato
rilanciato dopo il deploy della fase 3, e da allora vecchio endpoint e admin restano allineati da soli
(`sync_legacy_result`).

### Fase 3 · Lettura dai nuovi campi, con fallback (implementata)
- "Non compilato" = 99 **oppure** null (`Table.is_position_set`).
- **Visibilità (rivista)**: la classifica si vede se il tavolo **ha già risultati**, oppure il gioco
  aveva `leaderboard_enabled`, oppure la modalità effettiva (`Table.effective_result_mode` = quella
  del tavolo, altrimenti quella del gioco) è **`ffa`** (`services.tables.leaderboard_available`).
  Coop/squadre NON si aprono in questa fase: la UI attuale sa registrare solo classifiche "tutti
  contro tutti" (5 giochi abilitati sono ora coop/teams, con 6 tavoli già compilati: restano
  visibili e identici). Nessuna classifica esistente sparisce.
- Vecchio endpoint e admin: dopo aver scritto le posizioni chiamano `sync_legacy_result` (tavolo
  senza modalità con posizioni → `ffa`, poi `recompute_outcomes`). Così da questa fase i nuovi
  risultati sono già allineati senza bisogno di rilanciare il backfill.
- Import BGG: `suggest_result_mode` (rpgitem → none; Semi-Cooperative → ffa; Cooperative → coop;
  Team-Based → teams; altrimenti ffa).
- Admin: `default_result_mode` modificabile in lista giochi; `result_mode` filtrabile; `team` /
  `outcome` (sola lettura) sui giocatori.
- **Verifiche sulla copia di produzione**: sezione classifica renderizzata (anonimo + giocatore)
  con codice vecchio e nuovo su 413 combinazioni → **tutti i tavoli con risultati identici**; le
  uniche differenze (30) sono tavoli di giochi `ffa` prima non abilitati, che ora mostrano la
  classifica come i giochi abilitati. Endpoint su un tavolo nuovo: `ffa` + esiti corretti + una
  notifica; suggerimenti BGG identici alla regola rivista; confronto fotografia OK.
- Dopo il deploy: rilanciare `leaderboard_backfill` una volta (allinea i risultati compilati tra
  il deploy della fase 2 e questo), poi confronto.
- **Cambiamento visibile da comunicare**: i giochi "tutti contro tutti" prima senza classifica
  (Catan, Scythe…) iniziano a mostrarla; sui tavoli passati compare "Classifica non ancora creata"
  (finestra chiusa, nessun dato alterato).

### Fase 4a · Nuova UI di compilazione (implementata)
Visibilità **invariata** rispetto alla fase 3 (coop/squadre non ancora aperti ai giochi senza classifica).
- **Visualizzazione generata dal server** (`tables/_table_leaderboard.html` + `_position_badge.html`):
  medaglie oro/argento/bronzo, squadre, riquadri coop e "ha vinto il gioco", "Pareggio", "Senza
  classifica" con "Attiva la classifica" (solo chi può cambiare modalità). Punti mostrati solo se
  almeno un giocatore del tavolo ha un punteggio ≠ 0 (`Player.score` non è nullable: 0 = non inserito).
- **Editor** (`tables/_table_leaderboard_js.html`, condiviso da pagina tavolo e tavolo evento):
  porta la pagina di prova; testi tradotti IT/EN; dopo il salvataggio ricarica la pagina.
  Segnaposto dei testi in stile `{nome}`: in Django `{{ _("...") }}` raddoppia i `%`.
- **Endpoint** `POST /tables/<slug>/result/` (`SaveTableResultView` → `services.tables.save_table_result`):
  stessi permessi/finestra di oggi (`can_edit_leaderboard`), cambio modalità solo per
  `can_change_result_mode` (autore, staff location/evento, superuser); valida classifica "da
  competizione" (1,1,3…), squadre (tutti assegnati, ≥2, posizione unica per squadra), coop (esito
  obbligatorio; posizioni calcolate dal server: vinto = 1 a tutti); tutti i giocatori devono essere
  presenti; scrive con `bulk_update`/`update` + `recompute_outcomes`; una notifica per destinatario
  solo se qualcosa è cambiato. "Nessuna posizione" resta salvata come 99 fino alla fase 6.
- **Vecchio endpoint**: resta attivo; risponde 409 se il tavolo ha un risultato in un'altra modalità
  (pagine vecchie in cache non possono sovrascrivere squadre/coop).
- **Verifiche sulla copia di produzione**: per tutti i 129 tavoli con risultati la nuova
  visualizzazione mostra esattamente giocatori e posizioni del DB; endpoint provato in tutti i casi
  (pari merito, notifiche, errori, permessi, squadre, coop, ha vinto il gioco, senza classifica,
  409 del vecchio endpoint); editor provato nel browser (server locale su copia, sessione di test,
  tavolo ripristinato dopo); confronto fotografia OK.

### Fase 4b · Apertura coop e squadre + pulizia prototipo (implementata)
- `leaderboard_available` = gioco presente e modalità effettiva ≠ `none` (governa le notifiche);
  `leaderboard_enabled` non è più letto da nessuna parte (si elimina nella fase 6).
- Ogni tavolo con un gioco ha la sezione classifica; i tavoli `none` (salvati così o con gioco che
  suggerisce `none`) mostrano "Questa partita non prevede una classifica" e, a chi può cambiare
  modalità, "Attiva la classifica". `can_edit_leaderboard` non dipende più dalla modalità: per i
  tavoli `none` i giocatori non possono attivarla (il server rifiuta il cambio di modalità).
- Rimossa la pagina `/dummy-table/` (resta il precompilato del form contatti, usato dall'editor).
- Verifiche sulla copia di produzione (rendering 4a vs 4b su 433 combinazioni): **0 tavoli con
  risultati cambiati**; cambiano solo i tavoli vuoti di giochi coop/squadre prima non abilitati
  (ora "Classifica non ancora creata") e di giochi `none` (ora "Questa partita non prevede una
  classifica"); tavoli senza gioco invariati. Tavolo di gioco di ruolo: il giocatore non vede
  "Attiva" e il server gli rifiuta il cambio (403), l'autore sì. Notifiche: sì per ffa/coop/teams,
  no per `none` e senza gioco. Confronto fotografia OK.

### Fase 5 · Season — ⏳ TODO (rilascio separato)
Design nel §2 (Season) e §3 (Statistiche). Già fatto: modello `Season` e `Table.season` (migrazione 0072).
Le Location senza season non cambiano.
- [ ] Servizio di assegnazione tavolo → season **per data del tavolo** (opzione A): solo tavoli della
      Location, `event IS NULL`, esclusi i tornei; riassegnazione quando cambiano le date di una season
      o la data di un tavolo.
- [ ] Prima season di una Location: creazione automatica di **"Stagione Zero"** (dal primo tavolo a
      `start_date − 1`), con assegnazione dei tavoli passati.
- [ ] Vincoli: una sola season attiva per Location (già nel DB), intervalli non sovrapposti, buchi
      permessi; aprire una season chiude la precedente.
- [ ] UI manager (`/locations/<slug>/manage/seasons/` + card in `location_manage_index`): crea,
      chiudi, modifica date (con ricalcolo).
- [ ] Permessi: risultati delle season chiuse modificabili solo da superadmin e manager della Location
      (`can_edit_leaderboard`).
- [ ] Pagina Location: giochi più giocati / gamers / tavoli su tutto lo storico; classifica giocatori
      (oro → argento → bronzo → più partite giocate) e classifica per gioco sulla **season attiva** +
      selettore per le precedenti; esclusi i tavoli `none`; ospiti inclusi.
- [ ] Notifiche ai follower: `SEASON_STARTED` (con link alla classifica finale della precedente se la
      chiude) / `SEASON_ENDED` solo se si chiude senza aprirne un'altra; "Stagione Zero" silenziosa.
- [ ] Traduzioni IT/EN, prova generale sulla copia di produzione, backup + confronto fotografia.

### Fase 6 · Pulizia — ⏳ TODO (settimane dopo, a sistema stabile)
È l'**unica** fase che modifica dati esistenti: per questo va per ultima.
- [ ] Nuovo backup + nuova fotografia (`leaderboard_snapshot`).
- [ ] `Player.position` nullable, dati `99` → `NULL`, default `NULL`; nel codice: `UNSET_POSITION`,
      scrittura del 99 in `save_table_result`, template `== 99`, ordinamenti per posizione
      (il confronto della fotografia normalizza già 99 = null).
- [ ] Eliminare `Game.leaderboard_enabled` (campo, filtro admin, import BGG): non è più letto dalla 4b.
- [ ] Eliminare il vecchio endpoint `update-player-position` (prima controllare nei log che non riceva
      più chiamate da pagine in cache / PWA) e `sync_legacy_result` se non più usato.
- [ ] Prova generale sulla copia + confronto fotografia dopo il deploy.

## Fuori scope

- **Tornei** (`docs/tournaments-plan.md`): restano fuori dalle season.
- Punti normalizzati, ELO, win-rate: scartati per ora, si usa il **conteggio medaglie**.
- Più season attive contemporaneamente per Location.
- Profilo ospite riscattabile (feature futura separata).

## Punti ancora da decidere

Nessuno aperto sul sistema di classifica. Per le season, eventuali dettagli di UI si decidono
all'inizio della fase 5.

Note storiche risolte:
- Migrazione `leaderboard_enabled` → `default_result_mode`: fatta in fase 2 (lista rivista
  `webapp/data/game_result_modes.csv` + `leaderboard_backfill`), senza mappare "spento" → `none`.
- `position=99` → null: pianificata nella fase 6 (`leaderboard_visible` usa già `Table.is_position_set`).
