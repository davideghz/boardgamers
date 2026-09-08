# Modulo di adesione soci — piano di lavoro (bozza, 2026-09-08)

Per aderire a una APS in qualità di socio è **obbligatorio firmare un documento**
cartaceo. Obiettivo: i manager di una location caricano il modulo di adesione,
il socio che invia la richiesta lo scarica, lo stampa e lo firma; il manager
registra a mano l'avvenuta consegna.

> Stato: **Fasi 1, 2 e 3 implementate** (branch `membership-documents`); resta la Fase 4.

## Scope

Dentro:

1. anagrafica del socio completa (serve comunque al modulo, e in prospettiva
   alla compilazione automatica);
2. upload di **un documento vuoto** da parte del manager, download da parte del
   socio, **senza compilazione automatica**;
3. flag `signed_document` sulla `Membership`, impostato dal manager.

Fuori (per ora):

- riempimento automatico dei placeholder con i dati del socio — vedi
  [Evoluzione futura](#evoluzione-futura-compilazione-automatica);
- upload del modulo firmato da parte del socio. Il socio **non carica nulla**:
  consegna il cartaceo di persona e il manager spunta il flag. Questa scelta
  tiene fuori dal sistema le scansioni di documenti firmati, e con esse buona
  parte della superficie GDPR (conservazione, retention, cancellazione).

## Stato attuale del codice

- `Member` ([webapp/models.py:867](../webapp/models.py)): `location`,
  `user_profile` (nullable), `first_name`, `last_name`, `code`, `email`,
  `phone_number`, `uuid`.
- `Membership` ([webapp/models.py:911](../webapp/models.py)): `member`,
  `start_date`, `end_date`, `status` (PENDING/ACTIVE/EXPIRED/REJECTED),
  `notes`, `approved_by`, `uuid`.
- `MembershipRequestForm` raccoglie solo `notes`; `RequestMembershipView` crea
  il `Member` con nome/cognome/email presi dall'utente Django.
- Storage: tutto passa da `PublicMediaStorage` (`default_acl='public-read'`,
  [webapp/storage_backends.py:5](../webapp/storage_backends.py)).
- Ultima migrazione: `0067_table_unlimited_seats`.

Il modulo vuoto è un documento pubblico per natura (lo statuto/modulo di una
APS non è riservato): **si carica sul bucket pubblico esistente**, nessun
storage privato da introdurre. La questione privacy si porrebbe solo con il PDF
precompilato, che oggi è fuori scope.

## Fase 1 — Anagrafica del socio ✅ fatta

### 1.1 Rinomina `code` → `fiscal_code`

`Member.code` è di fatto il codice fiscale: rinominarlo esplicita l'intento.

```python
fiscal_code = models.CharField(max_length=16, blank=True, verbose_name=_('Fiscal Code'))
```

- Migrazione `RenameField` + `AlterField` (50 → 16 caratteri).
- Normalizzazione a maiuscolo in `Member.save()` o nel form.
- Validazione **soft** (decisa): regex del CF italiano applicata *solo se il
  campo è valorizzato*, così resta vuoto per i soci stranieri senza codice
  fiscale. Nessun controllo del carattere di controllo, nessun blocco altrove.
- Occorrenze da aggiornare: `webapp/models.py:884`, `webapp/forms.py:688`
  (`MemberForm.Meta.fields`), `webapp/admin.py:134,136`,
  `webapp/views/location_views.py:793` (export CSV),
  `templates/accounts/account_memberships.html:30,79`,
  `templates/locations/location_manage_members.html:51`.

### 1.2 Nuovi campi anagrafici

Tutti opzionali (`blank=True`), su `Member`:

| campo          | tipo                    | note                          |
|----------------|-------------------------|-------------------------------|
| `birth_date`   | `DateField`             |                               |
| `birth_place`  | `CharField(100)`        | comune o città estera         |
| `address`      | `CharField(200)`        | via e numero civico           |
| `city`         | `CharField(100)`        |                               |
| `zip_code`     | `CharField(10)`         |                               |
| `province`     | `CharField(2)`          | sigla                         |
| `nationality`  | `CharField(100)`        | default vuoto                 |

Una sola migrazione insieme al rename di 1.1.

### 1.3 Form e UI

- `MemberForm` (lato manager): aggiungere i campi in un blocco collassabile
  "Dati anagrafici", come si fa già per la sezione link e la cover custom del
  tavolo.
- `MembershipRequestForm`: da form con il solo `notes` a form che raccoglie
  l'anagrafica. `RequestMembershipView` la scrive sul `Member` creato al posto
  dei soli dati dell'utente Django.
- **Precompilazione fra location**: l'anagrafica sta su `Member`, che è
  per-location — un socio iscritto a tre location compilerebbe tre volte gli
  stessi dati. Al primo render del form, precompilare dal `Member` più recente
  dello stesso `user_profile`. Nessuna sincronizzazione successiva: ogni
  location resta padrona della propria copia.

#### Modifica dei dati da parte del socio

Il punto di accesso è **`account_memberships.html`** (deciso): nessuna pagina
nuova nel menu account, il socio ritrova i propri dati dove già vede le proprie
iscrizioni.

- Le card di `active_memberships` sono oggi un `<a>` che avvolge tutto e porta
  alla location ([account_memberships.html:19](../webapp/templates/accounts/account_memberships.html)):
  il link "Modifica i miei dati" va messo **fuori** dall'ancora, in fondo alla
  card, per non annidare due `<a>`.
- Nuova view + URL `account/memberships/<uuid:member_uuid>/data/`, che verifica
  `member.user_profile == request.user.user_profile`.
- Modificabile finché la membership è `PENDING` o `ACTIVE`; a membership
  `EXPIRED`/`REJECTED` i dati restano in sola lettura (le card di
  `past_memberships` non ricevono il link).
- Se l'anagrafica è incompleta, badge "Dati da completare" sulla card — è il
  richiamo che serve al socio quando la location gli chiede il modulo firmato.
- Aggiornare anche i due usi di `membership.member.code` alle righe 30 e 79 nel
  rename di 1.1.

## Fase 2 — Documento caricabile ✅ fatta

### 2.1 Modello

```python
class MembershipDocument(DateTimeModel):
    location = FK(Location, related_name='membership_documents')
    name = CharField(200)                 # "Modulo di adesione 2026"
    file = FileField(upload_to='membership-documents',
                     storage=PublicMediaStorage())
    is_active = BooleanField(default=True)
    uuid = UUIDField(...)
```

Più documenti per location (modulo di adesione, informativa privacy,
regolamento…), ognuno attivabile/disattivabile. Nessun vincolo di formato in
DB; validazione lato form sulle estensioni ammesse (PDF, DOC/DOCX, ODT) e sulla
dimensione massima.

### 2.2 URL

```
/locations/<slug>/manage/members/documents/           lista + upload
/locations/<slug>/manage/members/documents/<uuid>/    rinomina / attiva / elimina
```

Il download usa direttamente `document.file.url` (bucket pubblico), come per
cover e avatar: nessuna view di streaming.

### 2.3 View e permessi

Le view di gestione seguono lo schema esistente: `LoginRequiredMixin` +
`_require_membership_enabled(location)` + check `creator`/`managers`.

### 2.4 UI

- **Area gestione soci** (`location_manage_members.html`): card "Documenti"
  con elenco, upload e azioni.
- **Richiesta membership** (`location_request_membership.html`): se la location
  ha documenti attivi, mostrarli **prima dell'invio** — il socio deve sapere
  che dovrà firmare — e ripeterli nel messaggio di conferma dopo l'invio.
- **Le mie iscrizioni** (`account_memberships.html`): link ai documenti della
  location per ogni membership `PENDING` o `ACTIVE`, così il socio li ritrova.
- **Dettaglio location**: eventuale link accanto al bottone di richiesta.

## Fase 3 — Flag documento firmato ✅ fatta

```python
# su Membership
signed_document = models.BooleanField(default=False, verbose_name=_('Signed document received'))
```

- Impostabile dal manager in `MembershipEditForm` e in `ApproveMembershipForm`
  (checkbox "Modulo firmato ricevuto").
- Badge nella lista soci e nel dettaglio membership; filtro "senza modulo
  firmato" nella lista.
- Colonna nell'export CSV.
- **L'approvazione non è bloccata** dal flag (deciso): bloccare renderebbe
  impossibile approvare chi consegna il modulo lo stesso giorno. In
  `ApproveMembershipForm` compare solo un avviso non bloccante quando il flag è
  falso, e la lista soci resta filtrabile per "senza modulo firmato" così il
  manager recupera gli scoperti a posteriori.

## Fase 4 — Rifiniture

- Test: permessi upload/eliminazione, visibilità dei documenti al socio,
  rename `code` → `fiscal_code` (regressione su CSV e template), flag firmato.
- Admin: `MembershipDocument` registrato; `signed_document` in
  `list_display`/`list_filter` di `Membership`.
- i18n: `makemessages -l it --no-location -i "venv/*"` + `compilemessages`,
  commit di `.po` e `.mo`.

## Evoluzione futura: compilazione automatica

Registrata qui perché la Fase 1 è pensata per abilitarla, non per farla ora.

Approccio scelto in caso di ripresa: **PDF con campi modulo (AcroForm) +
`pypdf`**. Il manager prepara il PDF ufficiale aggiungendo campi nominati
(fattibile con LibreOffice Draw); all'upload si ispeziona l'AcroForm, si
salvano i nomi dei campi in un `field_map` (JSONField) e si prova l'automatch
con le chiavi canoniche (`nome`→`first_name`, `codice_fiscale`→`fiscal_code`,
…), lasciando al manager una UI di mapping per i campi non riconosciuti.

Due accortezze già individuate:

- **Non riempire lasciando i campi vivi**: molti lettori PDF mobile non
  renderizzano i valori senza appearance stream. Meglio usare l'AcroForm come
  *mappa di coordinate* — leggere i `/Rect` dei widget, stampare i valori in
  overlay con ReportLab, rimuovere l'AcroForm. PDF piatto, identico ovunque, e
  sia `pypdf` sia `reportlab` sono pure-Python (nessun buildpack apt su Heroku,
  a differenza di WeasyPrint/pdftk/LibreOffice).
- **Il PDF precompilato non va salvato**: contiene dati personali e lo storage
  è pubblico. Generazione on-the-fly e `FileResponse`, nessuna persistenza.

Fallback obbligatorio: se il PDF caricato non ha campi modulo, si serve
l'originale così com'è — cioè esattamente il comportamento della Fase 2.

Alternative valutate e scartate:

- **DOCX + `docxtpl`**: template facilissimo da preparare in Word, ma output
  `.docx` (il socio deve avere Word/LibreOffice per stampare), layout che
  shifta con testi più lunghi del previsto, conversione a PDF fuori portata su
  Heroku. Eventuale opzione aggiuntiva, non sostitutiva.
- **Documento scritto in-app (markdown/HTML) → WeasyPrint**: autofill banale ma
  richiede buildpack apt e soprattutto fa perdere all'associazione il proprio
  modulo ufficiale (carta intestata, clausole già validate).
- **Sostituzione di placeholder testuali `{{nome}}` cercati nel PDF**: fragile,
  si rompe con font e a capo diversi.

## Riepilogo migrazioni

1. `00XX_member_fiscal_code_and_personal_data` — rename `code` → `fiscal_code`,
   `AlterField` a 16 caratteri, sette nuovi campi anagrafici.
2. `00XX_membershipdocument` — nuovo modello.
3. `00XX_membership_signed_document` — nuovo flag.
