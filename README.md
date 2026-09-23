# Vatican Media Monitor

Dashboard statica e gratuita per monitorare la copertura internazionale su Papa Leone XIV, Santa Sede e temi collegati. Non richiede un server, un computer acceso o API a pagamento.

## Attivazione su GitHub

1. Carica nella repository tutti i file principali.
2. Apri **Settings → Pages**.
3. In **Build and deployment**, scegli **Deploy from a branch**.
4. Seleziona `main`, cartella `/(root)`, quindi **Save**.
5. Apri **Actions → Update news → Run workflow** per il primo aggiornamento.
6. Dopo qualche minuto, in **Settings → Pages** comparirà l'indirizzo pubblico della dashboard.

L'aggiornamento automatico è programmato due volte ogni ora. GitHub può avviarlo con qualche minuto di ritardo. Nelle repository GitHub Free, Pages potrebbe richiedere che la repository sia pubblica.

La scheda **Ora per ora** usa un flusso separato (`breaking.json`), aggiornato dal workflow **Update breaking news** ogni 10 minuti circa. Comprende notizie generali da TGcom24 e BBC News World, non soltanto articoli sul Vaticano. Mostra l'ora italiana della pubblicazione e l'ultimo controllo dei feed. La pagina ricarica i dati ogni 2 minuti mentre è aperta; i tempi effettivi dipendono anche dall'avvio di GitHub Actions e dalla distribuzione di Pages. Se una fonte non risponde, il workflow mantiene temporaneamente i titoli recenti già raccolti e segnala il problema. TGcom24 è letto dalla pagina pubblica “Ora per ora” poiché il vecchio feed RSS Ultimissime non è più disponibile.

## Copertura

- Otto edizioni geografiche e sei lingue.
- Papa Leone XIV, Santa Sede, pace e diplomazia, viaggi, tutela, finanze, nomine, dialogo e temi sociali.
- YouTube, X, Reddit, TikTok e Instagram tramite contenuti pubblici indicizzati. La copertura social è parziale: un monitoraggio completo richiede le API commerciali delle singole piattaforme.

## Privacy e costi

Il sito non raccoglie dati personali e non usa cookie. Il progetto utilizza esclusivamente file statici e GitHub Actions/Pages nei relativi limiti gratuiti.
