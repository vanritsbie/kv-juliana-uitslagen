# KV Juliana – automatisch thuisprogramma voor Yodeck

Deze repository genereert een schermpagina met het thuisprogramma van KV Juliana en publiceert die via GitHub Pages.

## Eerste configuratie
1. Controleer en configureer `config.json`: bron-URL, locatiekeywords en tijdsvenster.
2. De huidige bronlink vanaf de clubwebsite is ingesteld als uitgangspunt; de structuur is nog niet gevalideerd. De parser/filter moet eerst met een echt programma getest worden.
3. Open GitHub **Settings → Pages** en kies GitHub Actions als publicatiebron.
4. Start een handmatige run via **Actions → Weekly KV Juliana home program → Run workflow**.
5. Na succesvolle publicatie is de URL doorgaans `https://<owner>.github.io/<repo>/`. Controleer de exacte URL onder de Pages-deployment.
6. Voeg die URL als website/HTML-item in Yodeck toe.

## Schema
- Wekelijks maandag om 04:00 UTC
- Ook handmatig via GitHub Actions
- Het scherm refresh't zelf elke 15 minuten.

## Belangrijk
De eerste versie kan een lege statuspagina tonen als de bron niet bereikbaar is of geen passende tabel/JSON oplevert. Verifieer de bron en parser vóór gebruik op schermen. De filter vereist Juliana en een locatiekeyword (Veerhuis/Oud Gastel).
