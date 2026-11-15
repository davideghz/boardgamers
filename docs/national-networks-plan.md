# Affiliazioni nazionali delle location

## Modello dati

`Network` è il modello Django per l’anagrafica delle reti nazionali. Con la convenzione Django le tabelle si chiamano `webapp_network` e `webapp_locationnetwork`. Nell’interfaccia usiamo **Affiliazioni nazionali** per la sezione di gestione e **Associazione nazionale** per il filtro. Il termine `Network` copre federazioni, enti e reti come FederLudo, La Tana dei Goblin e AICS.

Una rete è un’entità a sé. Nel progetto, `Location` identifica un luogo di gioco con coordinate, tavoli, eventi e permessi. Rappresentare anche le reti come location richiederebbe eccezioni nel catalogo, nella mappa e negli altri flussi che selezionano un luogo. La relazione N:N consente a una location di dichiarare più affiliazioni e a una rete di raggruppare più location. Se la stessa associazione locale ha più schede, ciascuna dichiara le proprie affiliazioni.

| Modello | Campi essenziali |
| --- | --- |
| `Network` | `name`, `slug` univoco e stabile per i link al filtro, `logo` nazionale e `website` facoltativi, `is_active` per l’archiviazione. |
| `LocationNetwork` | `location`, `network`, `local_name` e `custom_logo` facoltativi, `created_at`, `updated_at`. |

`Location.networks` usa `LocationNetwork` come modello intermedio esplicito. Un vincolo univoco sulla coppia `(location, network)` impedisce i duplicati anche con invii simultanei. La chiave esterna `network_id` serve alle ricerche per rete. L’eliminazione di una location rimuove i suoi legami. Una rete con legami si archivia e la chiave esterna ne protegge la cancellazione.

## Gestione

- **Admin**. In `/admin/`, gli amministratori con i permessi sui modelli gestiscono nome, logo nazionale, sito web e stato della rete. Dalla scheda della rete accedono all’elenco delle location filtrato per quella rete. Nella scheda della singola location possono consultare le affiliazioni, sostituire o rimuovere il logo personalizzato ed eliminare una dichiarazione, secondo i permessi su `LocationNetwork`. [Gestione admin](../webapp/admin.py)
- **Proprietario e manager delegati**. Una voce **Affiliazioni nazionali** nel menu di gestione apre la pagina `/locations/<slug>/manage/networks/`. I gestori scelgono una rete attiva dall’anagrafica e salvano con pubblicazione immediata. Per ogni affiliazione possono impostare, modificare o svuotare il campo facoltativo «Nome locale dell’affiliazione». Possono anche aggiungere, sostituire o rimuovere il logo personalizzato oppure rimuovere l’intera affiliazione. Ogni operazione controlla il permesso con `location.is_manager`. [Gestione location](../webapp/views/location_views.py)
- **Rete mancante**. Vicino al selettore, anche con anagrafica vuota, compare «Non trovi la tua associazione nazionale? [Scrivici](/contacts)». I gestori inviano la richiesta tramite il form esistente e l’admin inserisce la rete nel catalogo. [Form contatti](../webapp/views/static_page_views.py#L157)
- **Archiviazione**. Una rete archiviata scompare da filtro, badge e loghi e viene esclusa dalle nuove dichiarazioni. I gestori possono ancora vedere e rimuovere un legame archiviato. Riattivare la rete ripubblica i legami ancora presenti.

Il testo nel dettaglio qualifica le affiliazioni come dichiarate dalla location. La rimozione da parte dell’admin è una correzione puntuale. I gestori possono dichiarare di nuovo la rete finché è attiva. Il salvataggio controlla lato server il permesso di gestione, l’appartenenza del legame a quella location e lo stato della rete. Le modifiche usano POST con protezione CSRF.

## Catalogo e pagina pubblica

- **Filtro**. In `/locations/`, il selettore presenta «Tutte» e le reti attive con il loro nome nazionale. Per la prima versione si seleziona una rete alla volta, anche quando una location ne dichiara diverse. Il filtro è pubblico, si salva nell’URL (`?network=<slug>`) e si applica alla stessa selezione di location per elenco e mappa. Sulla mappa compaiono le location della selezione che hanno coordinate. Si conserva l’ordinamento corrente, incluso quello per distanza quando disponibile, e il parametro `new_table=1` se presente. Con filtro attivo la sezione personale si omette per evitare duplicati. Una rete attiva senza risultati mostra uno stato vuoto con possibilità di azzerare il filtro. Uno slug inesistente o archiviato mostra «Affiliazione non disponibile», con la stessa possibilità di azzeramento. [Vista catalogo](../webapp/views/location_views.py#L42)
- **Card elenco e mappa**. La card dell’elenco e il popup del segnaposto mostrano un badge testuale per ogni affiliazione attiva, anche quando il filtro seleziona una sola rete. Il badge mostra il nome locale se presente e il nome nazionale se il campo è vuoto. Per esempio, Magno Fato può mostrare «TdG Vicenza» nel badge e comparire nel filtro «La Tana dei Goblin». La vista carica i legami attivi con i nomi locali e nazionali in blocco. Il popup riceve le etichette come dati e le inserisce come testo. La card elenco è condivisa con la home, quindi il catalogo le passa esplicitamente i badge. [Card location](../webapp/templates/tags/location_card.html), [mappa](../webapp/templates/locations/location_index.html#L110)
- **Dettaglio rete**. Il catalogo filtrato per una rete mostra il suo nome, il logo nazionale se presente e il link «Sito ufficiale» se l’admin ha impostato il sito web. [Catalogo location](../webapp/templates/locations/location_index.html)
- **Dettaglio location**. «Affiliazioni nazionali» compare nella barra laterale, sotto «Come arrivare», quando c’è almeno un’affiliazione attiva. Ogni riga mostra lo stesso badge di elenco e mappa e i due loghi affiancati quando entrambi sono disponibili. Il badge apre il catalogo filtrato per la rete nazionale. Quando il nome locale differisce, il nome nazionale compare accanto al badge. Il logo nazionale arriva dall’anagrafica. Il logo personalizzato arriva dal singolo legame, così due affiliate alla Tana dei Goblin possono avere immagini diverse. [Dettaglio location](../webapp/templates/locations/location_detail.html)

I due caricamenti accettano PNG, JPEG e WebP fino a 2 MB e 2048 pixel per lato e controllano il formato effettivo. Il campo immagine salva i loghi in PNG fino a 512 pixel per lato, conservando proporzioni e trasparenza. I file sostituiti o rimossi vengono cancellati dallo storage dopo il commit, quando nessuna rete o affiliazione li usa più. [Servizio immagini](../webapp/services/images.py)

## Verifiche di accettazione

1. L’admin crea una rete e carica il logo nazionale. Il proprietario dichiara due affiliazioni e vede subito entrambe in elenco, popup mappa e dettaglio.
2. Due affiliate della stessa rete caricano loghi personalizzati diversi. Entrambe vedono lo stesso logo nazionale e il proprio logo personalizzato. Rimuovere il logo personalizzato mantiene badge e logo nazionale.
3. Il proprietario di Magno Fato imposta «TdG Vicenza» per la propria affiliazione. Elenco, popup mappa e dettaglio mostrano il nome locale, mentre il filtro «La Tana dei Goblin» include la location. Svuotare il campo riporta il nome nazionale nel badge.
4. Un manager delegato può aggiungere, modificare e rimuovere le affiliazioni della location che gestisce. Un visitatore anonimo, un utente senza permessi e un gestore di un’altra location non possono alterare il legame.
5. Due invii per la stessa rete producono un solo legame. Il secondo gestore riceve un avviso e apre la modifica dell’affiliazione già salvata. Il filtro restituisce le location pertinenti una sola volta, con i segnaposti corrispondenti alle location geolocalizzate.
6. Archiviazione e riattivazione aggiornano filtro, badge e loghi. Gli invii diretti per una rete archiviata vengono respinti. Il link Contatti funziona anche quando il selettore è vuoto.
7. La migrazione crea anagrafica e legami vuoti per le location esistenti. Le pagine caricano i badge senza una query per card. Le nuove etichette sono traducibili in italiano e inglese e le due immagini restano leggibili su mobile e in modalità scura.
