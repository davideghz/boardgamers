# Tornei — piano di design (bozza, 2026-08-25)

Discussione preliminare per supportare eventi di tipo **torneo**. Primo caso d'uso
reale: torneo **2vs2 di Guards of Atlantis 2 a fine ottobre 2026**.

> Stato: **design in bozza, non implementato.** Da riprendere nella prossima sessione.

## Decisione di fondo: dentro board-gamers

Costruire il torneo **dentro** board-gamers, non come tool esterno. L'affinità di
dominio è reale e soprattutto si riusa gratis l'infrastruttura esistente di cui un
torneo in presenza ha comunque bisogno:

- utenti/profili + `GuestProfile` (giocatori senza account)
- sistema Eventi: `PhysicalTable` (postazioni), `PlayArea`, program page
  (agenda/griglia), `EventDate`, overlap/conflict check
- notifiche, calendario Google, commenti, SEO

Il rischio non è il "dove" ma lo **scope** (i tornei sono un buco senza fondo:
svizzero, tiebreaker, bye, seeding, doppia eliminazione…). Strategia: **layer
sottile sopra ciò che esiste, tarato sul primo caso reale**, progettato per
crescere ma senza costruire tutti i formati subito.

## Decisione chiave: torneo = tipologia di evento

Un torneo *è* un evento (data, luogo, partecipanti, programma, manager). Quindi:

```
Event.type  →  STANDARD (default) | TOURNAMENT
```

Un torneo eredita così tutto ciò che `Event` già offre (pagina pubblica,
partecipazione, manager, postazioni, program page, date, notifiche, mappa, SEO)
senza riscrivere nulla.

La config e la struttura del torneo NON vanno impilate come campi nullable dentro
`Event` (già grosso): stanno in un modello dedicato agganciato 1:1.

## "I tavoli non funzionano" — in realtà quasi

Il `Table` attuale è una *sessione di gioco* (giocatori, posti, join/leave libero,
`position`/`score`, data/ora/durata, `physical_table`, `play_area`). Una **partita
di torneo è concettualmente un Table** → riusandolo si ottiene scheduling,
postazione, program page, calendario, commenti gratis.

Dove il `Table` di oggi non basta:
1. **Join libero vs pairing fisso** — in torneo i partecipanti sono assegnati.
   Soluzione: creare il Table con i giocatori già dentro e non-joinable.
2. **Nessun concetto di squadra** — `Player` è per-utente. Serve un raggruppamento.

Quindi non si butta via `Table`: gli si mette **sopra** un layer torneo, e ogni
partita *opzionalmente* si aggancia a un `Table` per la parte fisica/schedulata.

## Modello dati minimo proposto

```
Tournament        → OneToOne(Event), game FK, format, team_size, scoring config
TournamentEntry   → tournament FK, name, seed          # la squadra (o singolo)
EntryMember       → entry FK, user_profile / guest      # 2 membri per il 2vs2
                                                        # (pattern Player user|guest, XOR)
Round             → tournament FK, index, name
Match             → round FK, entry_a, entry_b,
                    table FK (nullable → postazione + slot),
                    winner FK, score_a, score_b
# Standings = calcolate dai Match, non persistite (come la leaderboard)
```

Note:
- `Tournament` è **OneToOne** con Event per ora (un evento = un torneo). Se in
  futuro un raduno dovrà contenere più tornei → `OneToOne → ForeignKey`,
  migrazione minima.
- `EntryMember` con `user_profile` XOR `guest_profile` ricalca il pattern già
  collaudato di `Player` (gestisce anche chi non ha account).
- Niente `next_match`: il round-robin non ha bracket (servirebbe per
  l'eliminazione diretta, fase successiva).

## Decisioni prese per la v1 (dalle domande a Davide)

- **Aggancio:** torneo = **tipologia di evento** (`Event.type = TOURNAMENT`).
- **Formato v1:** **round-robin** (tutti contro tutti). Solo questo.
- **N. squadre attese GoA2:** **poche (4-6)** → round-robin completo è ideale.
- **Single-game:** un torneo = un `game`. Multi-game (circuito a punti su giochi
  diversi) è un'altra feature, rimandata.

### Round-robin, 4-6 squadre — implicazioni

- 4 squadre → 6 partite · 5 → 10 · 6 → 15. Ognuna è un 2vs2 (4 giocatori).
- **Generazione round** col metodo del cerchio: n pari → n-1 round da n/2 partite;
  n dispari → n round con un *bye* a giro. Serve perché con poche postazioni i
  round scaglionano le partite negli slot.
- **Standings** derivate: vittorie → punti. Tiebreak v1 = manuale/scontri diretti.
- **Aperto:** cosa conta come vittoria in GoA2 — vittoria secca (1 squadra vince)
  vs registrare anche punteggio/margine. È una config, non blocca il modello.

## Piano a fasi

### Fase 1 — MVP per fine ottobre
1. `Event.type` + `Tournament`/`TournamentEntry`/`EntryMember`/`Round`/`Match`
   (migrazione).
2. Creazione torneo = Event con `type=TOURNAMENT` + game + format=round-robin +
   team_size=2.
3. Gestione iscrizioni squadre (add manuale da manager; membri via user o guest).
4. "Genera calendario" → crea Round + Match col metodo del cerchio.
5. (Opz.) ogni Match → Table su postazione/slot.
6. Pagina torneo: griglia round-robin + standings + inserimento risultati.

**Fuori scope v1:** multi-game, eliminazione/gironi/svizzero, matchmaking
automatico, iscrizione self-service.

### Fase 2
- Secondo formato (eliminazione diretta con bracket / `next_match`).
- Generazione bracket assistita.
- Iscrizione squadre self-service.

### Fase 3
- Svizzero + matchmaking automatico + tiebreaker.

## Idee originali di Davide → dove sono finite

| Idea | Esito |
|---|---|
| Single vs multi-game | Single-game in v1; multi-game rimandato |
| Tavoli non funzionano | Riuso `Table` come sessione schedulata sotto `Match`; risolti join-libero e squadre |
| Matchmaking automatico | Rimandato a Fase 3; v1 = generazione round deterministica |
| Tipologie di torneo | v1 solo round-robin; eliminazione Fase 2; svizzero Fase 3 |
| Iscrizione squadre | In v1 (necessaria per il 2vs2); self-service in Fase 2 |
