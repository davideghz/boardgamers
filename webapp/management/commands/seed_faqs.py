from django.core.management.base import BaseCommand

from webapp.models import FAQCategory, FAQ


CATEGORIES = [
    {
        'name_it': 'Per iniziare',
        'name_en': 'Getting started',
        'order': 1,
        'faqs': [
            {
                'order': 1,
                'question_it': 'Cos\'è Board-Gamers.com?',
                'question_en': 'What is Board-Gamers.com?',
                'answer_it': (
                    'Board-Gamers.com è una piattaforma gratuita pensata per circoli e associazioni di giochi da tavolo. '
                    'Ti permette di gestire sessioni di gioco (tavoli), tenere traccia dei soci, '
                    'mantenere una biblioteca di giochi e tenere viva la tua comunità — tutto in un unico posto.'
                ),
                'answer_en': (
                    'Board-Gamers.com is a free platform designed for board game clubs and associations. '
                    'It helps you manage game sessions (tables), track members, maintain a game library, '
                    'and keep your community engaged — all in one place.'
                ),
            },
            {
                'order': 2,
                'question_it': 'Devo registrarmi per usare la piattaforma?',
                'question_en': 'Do I need an account to use the platform?',
                'answer_it': (
                    'Hai bisogno di un account per creare luoghi, partecipare a sessioni di gioco o gestire i soci. '
                    'Sfogliare i luoghi pubblici e i tavoli in programma è aperto a tutti senza registrazione.'
                ),
                'answer_en': (
                    'You need an account to create locations, join game sessions, or manage members. '
                    'Browsing public locations and upcoming tables is open to everyone without registration.'
                ),
            },
            {
                'order': 3,
                'question_it': 'Board-Gamers.com è davvero gratuito?',
                'question_en': 'Is Board-Gamers.com really free?',
                'answer_it': (
                    'Sì, completamente. Nessun abbonamento, nessun costo nascosto, nessuna trappola freemium. '
                    'La piattaforma è gratuita e lo resterà sempre.'
                ),
                'answer_en': (
                    'Yes, completely. No subscriptions, no hidden fees, no freemium traps. '
                    'The platform is free to use and will stay that way.'
                ),
            },
        ],
    },
    {
        'name_it': 'Luoghi e circoli',
        'name_en': 'Locations & clubs',
        'order': 2,
        'faqs': [
            {
                'order': 1,
                'question_it': 'Cos\'è una location?',
                'question_en': 'What is a location?',
                'answer_it': (
                    'Una location rappresenta il tuo circolo, la tua associazione o qualsiasi posto fisico '
                    'dove giocate a giochi da tavolo. Una volta creata, puoi gestire sessioni di gioco, '
                    'soci e una biblioteca di giochi.'
                ),
                'answer_en': (
                    'A location represents your club, association, or any physical place where you play board games. '
                    'Once you create a location, you can manage game sessions, members, and a game library from it.'
                ),
            },
            {
                'order': 2,
                'question_it': 'Chi può creare una location?',
                'question_en': 'Who can create a location?',
                'answer_it': (
                    'Qualsiasi utente registrato può creare una location. Il creatore diventa il proprietario '
                    'e può nominare altri gestori per aiutarlo ad amministrarlo.'
                ),
                'answer_en': (
                    'Any registered user can create a location. The creator becomes the owner and can appoint '
                    'additional managers to help run it.'
                ),
            },
            {
                'order': 3,
                'question_it': 'Posso avere più gestori per la mia location?',
                'question_en': 'Can I have multiple managers for my location?',
                'answer_it': (
                    'Sì. Il proprietario della location può aggiungere quanti gestori desidera. '
                    'I gestori hanno lo stesso accesso amministrativo del proprietario, '
                    'tranne che non possono trasferire la proprietà.'
                ),
                'answer_en': (
                    'Yes. The location owner can add as many managers as needed. '
                    'Managers have the same administrative access as the owner, '
                    'except they cannot transfer ownership.'
                ),
            }
        ],
    },
    {
        'name_it': 'Sessioni di gioco (tavoli)',
        'name_en': 'Game sessions (tables)',
        'order': 3,
        'faqs': [
            {
                'order': 1,
                'question_it': 'Cos\'è un tavolo?',
                'question_en': 'What is a table?',
                'answer_it': (
                    'Un tavolo è una sessione di gioco creata in un luogo. '
                    'Puoi impostare il gioco, la data, l\'orario e il numero di giocatori. '
                    'I soci possono unirsi con un solo tap.'
                ),
                'answer_en': (
                    'A table is a game session created at a location. '
                    'You set the game, date, time, and the number of players. '
                    'Members can join with one tap.'
                ),
            },
            {
                'order': 2,
                'question_it': 'Possono partecipare a un tavolo persone esterne alla piattaforma?',
                'question_en': 'Can people outside the platform join a table?',
                'answer_it': (
                    'Sì. Quando crei un tavolo puoi indicare un numero di giocatori esterni — '
                    'persone che parteciperanno ma non hanno un account su Board-Gamers.com.'
                ),
                'answer_en': (
                    'Yes. When creating a table you can set a number of external players — '
                    'people who will participate but don\'t have a Board-Gamers.com account.'
                ),
            },
            {
                'order': 3,
                'question_it': 'Posso incorporare i tavoli in programma sul sito del mio circolo?',
                'question_en': 'Can I embed upcoming tables on my club\'s website?',
                'answer_it': (
                    'Sì. Ogni location ha un widget con il calendario live — '
                    'una singola riga di codice da incollare in qualsiasi sito web '
                    'per mostrare le sessioni di gioco in programma e quelle passate in tempo reale.'
                ),
                'answer_en': (
                    'Yes. Each location has a live schedule widget — a single line of code you can paste '
                    'into any website to show upcoming and past game sessions in real time.'
                ),
            },
        ],
    },
    {
        'name_it': 'Gestione soci',
        'name_en': 'Member management',
        'order': 4,
        'faqs': [
            {
                'order': 1,
                'question_it': 'Qual è la differenza tra un utente e un socio?',
                'question_en': 'What is the difference between a user and a member?',
                'answer_it': (
                    'Un utente è una persona con un account su Board-Gamers.com. '
                    'Un socio è una persona registrata nell\'anagrafica del tuo circolo. '
                    'I soci possono essere collegati a un account utente, ma un circolo può '
                    'anche gestire soci che non sono sulla piattaforma.'
                ),
                'answer_en': (
                    'A user is someone with a Board-Gamers.com account. '
                    'A member is a person registered in your club\'s registry. '
                    'Members can optionally be linked to a user account, but a club can also '
                    'manage members who are not on the platform.'
                ),
            },
            {
                'order': 2,
                'question_it': 'Come funzionano i periodi di tesseramento?',
                'question_en': 'How do membership periods work?',
                'answer_it': (
                    'Ogni socio può avere uno o più periodi di tesseramento con una data di inizio e di fine. '
                    'I gestori possono approvare o rifiutare le richieste direttamente dal pannello di amministrazione.'
                ),
                'answer_en': (
                    'Each member can have one or more membership periods with a start and end date. '
                    'Managers can approve or reject membership requests directly from the admin panel.'
                ),
            },
            {
                'order': 3,
                'question_it': 'Un socio può richiedere il tesseramento autonomamente?',
                'question_en': 'Can a member request membership themselves?',
                'answer_it': (
                    'Sì. Se abiliti le richieste di tesseramento per il tuo luogo, '
                    'i soci possono inviare una richiesta dalla pagina pubblica del luogo. '
                    'I gestori potranno quindi approvarla o rifiutarla.'
                ),
                'answer_en': (
                    'Yes. If you enable membership requests for your location, members can submit a request '
                    'from the location\'s public page. Managers will then review and approve or reject it.'
                ),
            },
        ],
    },
    {
        'name_it': 'Classifiche',
        'name_en': 'Rankings',
        'order': 5,
        'faqs': [
            {
                'order': 1,
                'question_it': 'Come vengono calcolate le classifiche?',
                'question_en': 'How are player rankings calculated?',
                'answer_it': (
                    'Le classifiche si basano sull\'attività — principalmente il numero di tavoli giocati '
                    'e i punteggi registrati. Ogni location può abilitare o disabilitare le classifiche in modo indipendente.'
                ),
                'answer_en': (
                    'Rankings are based on activity — primarily the number of tables played and scores recorded. '
                    'Each location can enable or disable rankings independently.'
                ),
            },
            {
                'order': 2,
                'question_it': 'Le classifiche sono per location o globali?',
                'question_en': 'Are rankings per-location or global?',
                'answer_it': (
                    'Le classifiche sono calcolate per gioco in ogni luogo. '
                    'Non esiste una classifica globale unica — ogni circolo gestisce la propria.'
                ),
                'answer_en': (
                    'Rankings are calculated per game at each location. '
                    'There is no single global leaderboard — each club manages its own.'
                ),
            },
        ],
    },
    {
        'name_it': 'Privacy e dati',
        'name_en': 'Privacy & data',
        'order': 6,
        'faqs': [
            {
                'order': 1,
                'question_it': 'Chi può vedere i miei dati?',
                'question_en': 'Who can see my data?',
                'answer_it': (
                    'Le informazioni del tuo profilo sono visibili agli altri utenti della piattaforma. '
                    'La partecipazione alle sessioni di gioco è visibile nella pagina del relativo tavolo. '
                    'Consulta la nostra Informativa sulla Privacy per tutti i dettagli.'
                ),
                'answer_en': (
                    'Your profile information is visible to other users on the platform. '
                    'Game session participation is visible on the relevant table\'s page. '
                    'You can read our full Privacy Policy for details.'
                ),
            }
        ],
    },
]


class Command(BaseCommand):
    help = 'Populate FAQ categories and questions in Italian and English'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete all existing FAQs and categories before seeding',
        )

    def handle(self, *args, **options):
        if options['clear']:
            FAQ.objects.all().delete()
            FAQCategory.objects.all().delete()
            self.stdout.write(self.style.WARNING('Existing FAQs and categories deleted.'))

        created_categories = 0
        created_faqs = 0

        for cat_data in CATEGORIES:
            faqs = cat_data.pop('faqs')
            category, created = FAQCategory.objects.get_or_create(
                name_it=cat_data['name_it'],
                defaults=cat_data,
            )
            if not created:
                for field, value in cat_data.items():
                    setattr(category, field, value)
                category.save()
            else:
                created_categories += 1

            for faq_data in faqs:
                faq, created = FAQ.objects.get_or_create(
                    category=category,
                    question_it=faq_data['question_it'],
                    defaults={**faq_data, 'is_active': True},
                )
                if not created:
                    for field, value in faq_data.items():
                        setattr(faq, field, value)
                    faq.save()
                else:
                    created_faqs += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done. {created_categories} categories and {created_faqs} FAQs created.'
        ))
