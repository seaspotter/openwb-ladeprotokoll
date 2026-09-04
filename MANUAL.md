# openWB Ladeprotokoll – Bedienungsanleitung

Kurze Referenz für die Weboberfläche. Für Installation/Konfiguration siehe
[DEPLOYMENT.md](DEPLOYMENT.md), für die Architektur [CLAUDE.md](CLAUDE.md).

## Kopfzeile

Auf jeder Seite rechts oben:

- **Jetzt abrufen** *(nur auf der Übersicht)* — ruft den aktuellen Monat
  aller aktiven Quellen ab und lädt die Tabelle danach neu. Für einzelne
  Quellen oder ältere Monate siehe Einstellungen → Verlauf abrufen.
- **🌙/☀️** — wechselt zwischen hellem und dunklem Design; die Wahl wird
  im Browser gemerkt (pro Browser, nicht serverseitig) und gilt für alle
  drei Seiten.
- **⚙️ Einstellungen** — öffnet die Einstellungen als Dialogfenster über
  der aktuellen Seite (kein Seitenwechsel nötig).

## Übersicht (Startseite)

Zeigt alle bereits abgerufenen Ladevorgänge, mit Filter nach Quelle,
Fahrzeug, Ladepunkt und Zeitraum. Fahrzeug und Ladepunkt sind Auswahllisten
(befüllt aus den tatsächlich vorhandenen Werten, ggf. eingeschränkt durch
die gewählte Quelle) statt Freitextfeldern — falsche Schreibweisen liefern
so keine leeren Ergebnisse.

Neben "Kosten (openWB)" steht der zum jeweiligen Ladevorgang passende
Preis (oder "kein Preis hinterlegt") sowie die tatsächlich verwendeten
Kosten — weicht der korrigierte Preis spürbar von openWBs eigenem Wert
ab, sind beide Spalten rot hervorgehoben.

Diese Ansicht ist rein zur Übersicht — die Auswahl für einen Bericht
passiert unter "Bericht erstellen".

## Einstellungen (⚙️)

Ein Dialogfenster mit fünf Bereichen, in dieser Reihenfolge:

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

Zusätzlich zu "Jetzt abrufen" läuft im Hintergrund bereits automatisch ein
täglicher Abruf — einmal beim Start der Anwendung und danach alle 24
Stunden werden alle aktiven Quellen für den aktuellen Monat neu
abgefragt, ohne dass dafür etwas eingestellt werden muss (ein Hinweis
dazu steht auch direkt im Quellen-Bereich).

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

### Fahrzeuge

Listet jedes Fahrzeug auf, das in bereits abgerufenen Ladevorgängen
vorkommt, mit einem Eingabefeld für das **Kennzeichen** und einem
"Speichern"-Knopf pro Zeile. openWB selbst liefert kein Kennzeichen — das
ist eine rein hier gepflegte Zusatzangabe, wird aber in jedem PDF-Bericht
bei "Fahrzeug(e)" mit ausgegeben (z. B. "VW ID3 (AB-CD 123)"), sofern für
das jeweilige Fahrzeug eines hinterlegt ist.

### Verlauf abrufen

Sowohl der automatische Abruf als auch "Jetzt abrufen" erfassen immer nur
den **aktuellen** Monat. Um ältere, bereits vergangene Monate
nachzuholen (z. B. beim erstmaligen Einrichten einer Quelle): Quelle,
Start- und Endmonat wählen und "Abrufen". Das kann je nach Zeitraum einen
Moment dauern; die Anzahl der verarbeiteten Ladevorgänge wird danach
angezeigt.

### Berichts-Einstellungen

Gilt für alle künftig erzeugten Berichte (bereits erzeugte PDFs bleiben
unverändert). Dies ist die **einzige** Stelle, an der die PDF-Spalten
gewählt werden — in "Bericht erstellen" selbst gibt es keine separate
Auswahl mehr:

- **PDF-Spalten** — welche Spalten im PDF erscheinen.
- **Kosten-Spalte zeigt** — ob das PDF pro Ladevorgang und in der Summe
  openWBs eigenen Wert oder den korrigierten (mit automatischem Fallback
  auf openWB, wenn kein Preis passt) zeigt. Es gibt nur eine "Kosten"-
  Spalte im PDF, keine zwei nebeneinander.
- **Ausrichtung** — Hochkant (Standard) oder Querformat. Bei vielen
  ausgewählten Spalten passt Hochkant u. U. nicht mehr sauber auf eine
  Seite — dann Querformat wählen.
- **Unterschriftzeile im PDF** — ob am Ende des Dokuments eine Zeile für
  Unterschrift/Datum steht. Standardmäßig aus.

Nicht vergessen: nach Änderungen unten **Speichern** klicken.

## Bericht erstellen

Über "Bericht erstellen" in der Kopfzeile gelangt man zur Auswahl-Ansicht.

1. **Filter** — optional nach Quelle, Fahrzeug, Ladepunkt und Zeitraum
   eingrenzen, dann "Laden". Alle gefundenen Ladevorgänge sind zunächst
   ausgewählt (Häkchen), einzelne lassen sich abwählen.
2. **Ladevorgänge-Tabelle** — pro Zeile steht der automatisch ermittelte
   Preis ("Automatisch (Anbieter)" oder "Automatisch (kein Preis)"); über
   das Dropdown lässt sich das für diesen einen Ladevorgang übersteuern:
   ein bestimmter Preis-Eintrag, oder "openWB-Wert verwenden" (keine
   Korrektur für diese Zeile). Die "Kosten (verwendet)"-Spalte und die
   Summe darunter aktualisieren sich sofort.
3. **Vorschau** — zeigt das Dokument in der Seite, ohne etwas zu
   speichern; beliebig oft wiederholbar.
4. **Bericht erzeugen** — Titel eingeben (z. B. "August 2026") und
   erzeugen. Das PDF steht danach über den angezeigten Link sowie in
   "Bisherige Berichte" zur Verfügung. Der Dateiname beim Herunterladen ist
   das Erzeugungsdatum plus "Ladeprotokoll" plus der eingegebene Titel
   (z. B. "20260901 Ladeprotokoll August 2026.pdf").

Welche Spalten im PDF erscheinen, wird ausschließlich unter Einstellungen
→ Berichts-Einstellungen festgelegt (siehe oben).

Im PDF selbst stehen die Ladevorgänge chronologisch aufsteigend
(ältester zuerst, neuester unten), unabhängig von der Reihenfolge in der
Auswahl-Tabelle oben (dort: neueste zuerst, besser zum Prüfen frisch
abgerufener Daten).

Ein erzeugter Bericht ist unveränderlich: eine erneute Erzeugung legt
immer einen neuen, eigenständigen Bericht an — die zum jeweiligen
Zeitpunkt verwendeten Ladevorgangs- und Preisdaten sind darin eingefroren
und bleiben auch dann unverändert, wenn die zugrunde liegenden Daten
oder die Berichts-Einstellungen später geändert werden.

## Self-Update

Sofern über `docker-compose.yml` eingebunden (siehe
[DEPLOYMENT.md](DEPLOYMENT.md)), lässt sich die Anwendung ohne manuellen
`git pull`/Rebuild aktualisieren — Details dort unter "Self-update from
the UI".
