# openWB Ladeprotokoll – Bedienungsanleitung

Kurze Referenz für die Weboberfläche. Für Installation/Konfiguration siehe
[DEPLOYMENT.md](DEPLOYMENT.md), für die Architektur [CLAUDE.md](CLAUDE.md).

## Übersicht (Startseite)

Zeigt alle bereits abgerufenen Ladevorgänge, mit Filter nach Quelle,
Fahrzeug, Ladepunkt und Zeitraum. Fahrzeug und Ladepunkt sind Auswahllisten
(befüllt aus den tatsächlich vorhandenen Werten, ggf. eingeschränkt durch
die gewählte Quelle) statt Freitextfeldern — falsche Schreibweisen liefern
so keine leeren Ergebnisse.

- **Jetzt abrufen** — ruft den aktuellen Monat aller aktiven Quellen ab
  und lädt die Tabelle danach neu. Für einzelne Quellen oder ältere Monate
  siehe "Einstellungen" → Verlauf abrufen.
- Neben "Kosten (openWB)" steht der zum jeweiligen Ladevorgang passende
  Preis (oder "kein Preis hinterlegt") sowie die tatsächlich verwendeten
  Kosten — weicht der korrigierte Preis spürbar von openWBs eigenem Wert
  ab, sind beide Spalten rot hervorgehoben.

Diese Ansicht ist rein zur Übersicht — die Auswahl für einen Bericht
passiert unter "Bericht erstellen".

## Einstellungen

Erreichbar über "Einstellungen" in der Kopfzeile.

### Quellen

Eine Quelle ist eine openWB-Installation, deren Ladeprotokoll erfasst
werden soll.

- **Quelle hinzufügen** — über das "+" neben "Quellen" öffnet sich das
  Formular: Name (frei wählbar, z. B. "Zuhause") und Adresse (IP oder URL,
  z. B. `192.168.1.10`) eingeben. Ohne Schema wird automatisch `http://`
  angenommen.
- **Jetzt abrufen** — ruft sofort den aktuellen Monat dieser einen Quelle
  ab und aktualisiert Datum/Status der letzten Abfrage in der Tabelle. Ein
  Fehler (Quelle nicht erreichbar o. ä.) wird in der Status-Spalte
  angezeigt.
- **Löschen** — entfernt die Quelle dauerhaft, inklusive aller bereits
  gespeicherten Ladevorgänge dieser Quelle.

Zusätzlich zu "Jetzt abrufen" läuft im Hintergrund ein automatischer
Abruf: einmal beim Start der Anwendung und danach alle 24 Stunden werden
alle aktiven Quellen für den aktuellen Monat neu abgefragt — ohne, dass
dafür etwas eingestellt werden muss.

### Verlauf abrufen

Sowohl der automatische Abruf als auch "Jetzt abrufen" erfassen immer nur
den **aktuellen** Monat. Um ältere, bereits vergangene Monate
nachzuholen (z. B. beim erstmaligen Einrichten einer Quelle): Quelle,
Start- und Endmonat wählen und "Abrufen". Das kann je nach Zeitraum einen
Moment dauern; die Anzahl der verarbeiteten Ladevorgänge wird danach
angezeigt.

### Preise

Ein Preis-Eintrag legt fest, mit welchem Strompreis openWBs eigene
Kostenberechnung überprüft und ggf. korrigiert wird.

- **Preis hinzufügen** — über das "+" neben "Preise" öffnet sich das
  Formular: Anbieter, Preis pro kWh, sowie optional eine Quelle und/oder
  ein Fahrzeug (leer gelassen = gilt für alle), ein Gültigkeitszeitraum
  (ohne "Gültig bis" gilt der Preis unbegrenzt), und eine **Notiz** —
  diese unbedingt ausfüllen (z. B. "Vertrag XY", "Grundpreis Winter"),
  sonst ist ein Jahre später betrachteter Eintrag mit nur Datum und Preis
  kaum noch zuzuordnen.
- **Auswahl bei mehreren passenden Preisen** — der spezifischste gewinnt:
  Quelle+Fahrzeug vor nur Quelle vor nur Fahrzeug vor einem Preis ohne
  jede Einschränkung. Bei gleicher Spezifität gewinnt der zuletzt
  angelegte Preis.
- **Löschen** — entfernt den Preis-Eintrag dauerhaft; bereits erzeugte
  PDF-Berichte sind davon nicht betroffen, da sie den zum Zeitpunkt der
  Erzeugung verwendeten Preis eingefroren mitspeichern.

### Berichts-Einstellungen

Gilt für alle künftig erzeugten Berichte (bereits erzeugte PDFs bleiben
unverändert):

- **PDF-Spalten (Vorauswahl)** — welche Spalten in "Bericht erstellen"
  standardmäßig angehakt sind. Dort lässt sich das für einen einzelnen
  Bericht weiterhin ändern.
- **Kosten-Spalte zeigt** — ob das PDF pro Ladevorgang und in der Summe
  openWBs eigenen Wert oder den korrigierten (mit automatischem Fallback
  auf openWB, wenn kein Preis passt) zeigt. Es gibt nur eine "Kosten"-
  Spalte im PDF, keine zwei nebeneinander.
- **Unterschriftzeile im PDF** — ob am Ende des Dokuments eine Zeile für
  Unterschrift/Datum steht. Standardmäßig aus.

## Bericht erstellen

Über "Bericht erstellen" in der Kopfzeile gelangt man zur Auswahl-Ansicht.

1. **Filter** — optional nach Quelle, Fahrzeug, Ladepunkt und Zeitraum
   eingrenzen, dann "Laden". Alle gefundenen Ladevorgänge sind zunächst
   ausgewählt (Häkchen), einzelne lassen sich abwählen.
2. **PDF-Spalten** — welche der Ladeprotokoll-Spalten im PDF erscheinen
   sollen; die Vorauswahl kommt aus den Berichts-Einstellungen und lässt
   sich hier für diesen einen Bericht ändern.
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

Im PDF selbst stehen die Ladevorgänge chronologisch aufsteigend
(ältester zuerst, neuester unten), unabhängig von der Reihenfolge in der
Auswahl-Tabelle oben (dort: neueste zuerst, besser zum Prüfen frisch
abgerufener Daten).

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
