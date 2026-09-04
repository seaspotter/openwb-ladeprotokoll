# openWB Ladeprotokoll – Bedienungsanleitung

Kurze Referenz für die Weboberfläche. Für Installation/Konfiguration siehe
[DEPLOYMENT.md](DEPLOYMENT.md), für die Architektur [CLAUDE.md](CLAUDE.md).

## Quellen

Eine Quelle ist eine openWB-Installation, deren Ladeprotokoll erfasst
werden soll.

- **Quelle hinzufügen** — Name (frei wählbar, z. B. "Zuhause") und
  Adresse (IP oder URL, z. B. `192.168.1.10`) eingeben. Ohne Schema wird
  automatisch `http://` angenommen.
- **Jetzt abrufen** — ruft sofort den aktuellen Monat dieser Quelle ab und
  aktualisiert Datum/Status der letzten Abfrage in der Tabelle. Ein Fehler
  (Quelle nicht erreichbar o. ä.) wird in der Status-Spalte angezeigt.
- **Löschen** — entfernt die Quelle dauerhaft, inklusive aller bereits
  gespeicherten Ladevorgänge dieser Quelle.

Zusätzlich zu "Jetzt abrufen" läuft im Hintergrund ein automatischer
Abruf: einmal beim Start der Anwendung und danach alle 24 Stunden werden
alle aktiven Quellen für den aktuellen Monat neu abgefragt — ohne, dass
dafür etwas eingestellt werden muss.

## Preise

Ein Preis-Eintrag legt fest, mit welchem Strompreis openWBs eigene
Kostenberechnung überprüft und ggf. korrigiert wird.

- **Preis hinzufügen** — Anbieter, Preis pro kWh, sowie optional eine
  Quelle und/oder ein Fahrzeug (leer gelassen = gilt für alle) und ein
  Gültigkeitszeitraum. Ohne "Gültig bis" gilt der Preis unbegrenzt.
- **Auswahl bei mehreren passenden Preisen** — der spezifischste gewinnt:
  Quelle+Fahrzeug vor nur Quelle vor nur Fahrzeug vor einem Preis ohne
  jede Einschränkung. Bei gleicher Spezifität gewinnt der zuletzt
  angelegte Preis.
- **Löschen** — entfernt den Preis-Eintrag dauerhaft; bereits erzeugte
  PDF-Berichte sind davon nicht betroffen, da sie den zum Zeitpunkt der
  Erzeugung verwendeten Preis eingefroren mitspeichern.

## Bericht erstellen

Über "Bericht erstellen" in der Kopfzeile gelangt man zur Auswahl-Ansicht.

1. **Filter** — optional nach Quelle, Fahrzeug und Zeitraum eingrenzen,
   dann "Laden". Alle gefundenen Ladevorgänge sind zunächst ausgewählt
   (Häkchen), einzelne lassen sich abwählen.
2. **PDF-Spalten** — welche der Ladeprotokoll-Spalten im PDF erscheinen
   sollen; alle sind standardmäßig aktiv.
3. **Ladevorgänge-Tabelle** — pro Zeile steht der automatisch ermittelte
   Preis ("Automatisch (Anbieter)" oder "Automatisch (kein Preis)"); über
   das Dropdown lässt sich das für diesen einen Ladevorgang übersteuern:
   ein bestimmter Preis-Eintrag, oder "openWB-Wert verwenden" (keine
   Korrektur für diese Zeile). Die "Kosten (verwendet)"-Spalte und die
   Summe darunter aktualisieren sich sofort.
4. **Vorschau** — zeigt das Dokument in der Seite, ohne etwas zu
   speichern; beliebig oft wiederholbar.
5. **Bericht erzeugen** — Titel eingeben (z. B. "August 2026") und
   erzeugen. Das PDF steht danach über den angezeigten Link sowie in
   "Bisherige Berichte" zur Verfügung.

Ein erzeugter Bericht ist unveränderlich: eine erneute Erzeugung legt
immer einen neuen, eigenständigen Bericht an — die zum jeweiligen
Zeitpunkt verwendeten Ladevorgangs- und Preisdaten sind darin eingefroren
und bleiben auch dann unverändert, wenn die zugrunde liegenden Daten
später bearbeitet oder erneut abgerufen werden.

## Self-Update

Sofern über `docker-compose.yml` eingebunden (siehe
[DEPLOYMENT.md](DEPLOYMENT.md)), lässt sich die Anwendung ohne manuellen
`git pull`/Rebuild aktualisieren — Details dort unter "Self-update from
the UI".
