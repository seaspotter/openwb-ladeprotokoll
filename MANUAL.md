# openWB Ladeprotokoll – Bedienungsanleitung

Kurze Referenz für die Weboberfläche. Für Installation/Konfiguration siehe
[DEPLOYMENT.md](DEPLOYMENT.md), für die Architektur [CLAUDE.md](CLAUDE.md).

## Kopfzeile

Auf jeder Seite rechts oben:

- **Jetzt abrufen** *(nur auf der Übersicht)* — ruft den aktuellen Monat
  aller aktiven Quellen ab und lädt die Tabelle danach neu. Für einzelne
  Quellen oder ältere Monate siehe Einstellungen → Verlauf abrufen.
- **Sonne/Mond-Symbol** — wechselt zwischen hellem und dunklem Design; die
  Wahl wird im Browser gemerkt (pro Browser, nicht serverseitig) und gilt
  seitenübergreifend.
- **Zahnrad-Symbol (Einstellungen)** — öffnet die Einstellungen als
  Dialogfenster über der aktuellen Seite (kein Seitenwechsel nötig).

## Übersicht (Startseite)

Zeigt alle bereits abgerufenen Ladevorgänge, mit Filter nach Quelle,
Fahrzeug, Ladepunkt und Zeitraum. Fahrzeug und Ladepunkt sind Auswahllisten
(befüllt aus den tatsächlich vorhandenen Werten, ggf. eingeschränkt durch
die gewählte Quelle) statt Freitextfeldern — falsche Schreibweisen liefern
so keine leeren Ergebnisse.

Neben "Kosten (real)" steht der zum jeweiligen Ladevorgang passende
Preis (oder "kein Preis hinterlegt") sowie die tatsächlich verwendeten
Kosten — weicht der korrigierte Preis spürbar von openWBs eigenem Wert
ab, sind beide Spalten rot hervorgehoben. Diese Hervorhebung dient nur der
Prüfung hier und unter "Bericht erstellen" — im fertigen PDF selbst
erscheint die Kosten-Spalte immer neutral, ohne rote Markierung.

Unter dem Filter steht "Letzter Abruf: ..." mit Datum/Uhrzeit des
zuletzt (automatisch oder manuell) erfolgreich abgerufenen Ladeprotokolls
über alle Quellen hinweg — so lässt sich auf einen Blick erkennen, ob die
angezeigten Daten aktuell sind, ohne extra unter Einstellungen
nachzusehen. Ist zuletzt eine Quelle fehlgeschlagen, wird das dort
ebenfalls vermerkt.

Diese Ansicht ist rein zur Übersicht — die Auswahl für einen Bericht
passiert unter "Bericht erstellen".

## Einstellungen (Zahnrad-Symbol)

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
täglicher Abruf aller aktiven Quellen für den aktuellen Monat, einmal beim
Start der Anwendung und danach täglich zur eingestellten Uhrzeit
(Standard: **00:05**, kurz nach Mitternacht — spät genug, dass der gerade
zu Ende gegangene Tag vollständig in openWBs eigener Ladeprotokoll-Datei
angekommen ist, früh genug, dass beim ersten Blick am Morgen schon die
Daten von gestern da sind). Direkt im Quellen-Bereich lässt sich das
über die Checkbox "Automatischer Abruf aktiv" komplett ausschalten und
die Uhrzeit daneben anpassen — beides wird sofort beim Ändern gespeichert,
ohne separaten "Speichern"-Knopf. Die Uhrzeit bezieht sich auf die
Zeitzone des Containers, nicht zwingend die des Browsers.

### Preise

Ein Preis-Eintrag legt fest, mit welchem Strompreis openWBs eigene
Kostenberechnung überprüft und ggf. korrigiert wird ("Kosten (korrigiert)"
in der Übersicht, bei "Bericht erstellen" und im PDF).

Ganz oben im Bereich stehen außerdem zwei eigene Felder, **PV-Preis** und
**Batterie-Preis** (€/kWh, Standard jeweils 0, per "Speichern" sofort
gespeichert). Diese wirken sich **ausschließlich auf die Statistik-Seite**
aus: dort wird jeder Ladevorgang nach seinem tatsächlichen Netz-/PV-/
Speicher-Anteil bepreist (z. B. 60 % Netz zum obigen Preis, 30 % PV zum
PV-Preis, 10 % Speicher zum Batterie-Preis), statt mit einem einzigen
Preis für die gesamte geladene Energie. Übersicht, Bericht erstellen und
bereits erzeugte wie neue PDFs bleiben davon unberührt — dort gilt
weiterhin ausschließlich der oben eingetragene Preis-Eintrag für die
gesamte Energiemenge, unabhängig davon, woher sie kam.

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
- **Kosten-Spalte zeigt** — die **Standard**-Kostenbasis für neue
  Berichte: openWBs eigenen Wert oder den korrigierten (mit
  automatischem Fallback auf openWB, wenn kein Preis passt). Es gibt nur
  eine "Kosten"-Spalte im PDF, keine zwei nebeneinander. Lässt sich pro
  Bericht in "Bericht erstellen" noch einmal bewusst übersteuern (siehe
  unten) — dieser Wert hier ist nur die Vorbelegung.
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
   Korrektur für diese Zeile). Die "Kosten (korrigiert)"-Spalte und die
   Summe darunter aktualisieren sich sofort.
3. **Vorschau** — zeigt das Dokument in der Seite, ohne etwas zu
   speichern; beliebig oft wiederholbar.
4. **Bericht erzeugen** — Titel eingeben (z. B. "August 2026"), bei Bedarf
   die **Kostenbasis** für diesen einen Bericht umstellen (openWB-Wert
   oder Korrigiert — voreingestellt mit dem Wert aus Berichts-
   Einstellungen, aber hier bewusst je Bericht änderbar), dann erzeugen.
   Das PDF steht danach über den angezeigten Link sowie in "Bisherige
   Berichte" zur Verfügung. Der Dateiname beim Herunterladen ist das
   Erzeugungsdatum plus "Ladeprotokoll" plus der eingegebene Titel (z. B.
   "20260901 Ladeprotokoll August 2026.pdf").

"Bisherige Berichte" zeigt zu jedem Bericht, welche Kostenbasis er
tatsächlich verwendet hat ("Kostenbasis"-Spalte) — ein später erzeugter
Bericht mit anderer Kostenbasis lässt sich so von einem älteren
unterscheiden, ohne das PDF öffnen zu müssen. Das PDF selbst zeigt die
Kostenbasis bewusst nicht als eigene Zeile — nur die "Kosten"-Spalte
darin.

Welche Spalten im PDF erscheinen, wird ausschließlich unter Einstellungen
→ Berichts-Einstellungen festgelegt (siehe oben) — nur die Kostenbasis
selbst lässt sich zusätzlich pro Bericht übersteuern.

Im PDF selbst stehen die Ladevorgänge chronologisch aufsteigend
(ältester zuerst, neuester unten), unabhängig von der Reihenfolge in der
Auswahl-Tabelle oben (dort: neueste zuerst, besser zum Prüfen frisch
abgerufener Daten).

Ein erzeugter Bericht ist unveränderlich: eine erneute Erzeugung legt
immer einen neuen, eigenständigen Bericht an — die zum jeweiligen
Zeitpunkt verwendeten Ladevorgangs- und Preisdaten sind darin eingefroren
und bleiben auch dann unverändert, wenn die zugrunde liegenden Daten
oder die Berichts-Einstellungen später geändert werden.

## Statistik

Über "Statistik" in der Kopfzeile (Übersicht und "Bericht erstellen").
Zeigt, wie viel geladen wurde, was es gekostet hat, und woher die Energie
kam — monatlich oder jährlich zusammengefasst.

- **Filter** — optional nach Quelle und/oder Fahrzeug eingrenzen, sowie
  Monatlich/Jährlich wählen, dann "Laden".
- **Summe** — Ladevorgänge, Energie, Kosten und PV-Eigenverbrauch (Anteil
  von PV + Speicher an der Gesamtenergie, in %) über den gesamten
  angezeigten Zeitraum.
- **Energiequellen (kWh)** — gestapeltes Balkendiagramm pro Zeitraum:
  Netz, PV, Speicher, Ladepunkt. Die Balken zeigen die tatsächlich
  geladene Energiemenge je Quelle, nicht einen gemittelten Prozentwert —
  ein einzelner sehr großer Ladevorgang mit viel PV-Anteil verschiebt das
  Bild also stärker als mehrere kleine Ladevorgänge mit wenig PV-Anteil,
  was der Realität eher entspricht als eine einfache Durchschnittsbildung.
- **Kosten** — Balkendiagramm pro Zeitraum, zeigt openWB-Wert oder
  korrigiert (je nach Berichts-Einstellungen → Kosten-Spalte zeigt) —
  welche der beiden gerade aktiv ist, steht direkt in der Überschrift
  ("Kosten (openWB-Wert)" bzw. "Kosten (Korrigiert)"), ebenso in der
  Summe-Kachel und der Nach-Fahrzeug-Spalte. Bei "Korrigiert" ist diese
  Seite die **einzige** Stelle in der Anwendung, an der zusätzlich
  PV-Preis/Batterie-Preis einfließen (siehe "Preise" oben) — die
  korrigierten Kosten hier können sich daher von den korrigierten Kosten
  in Übersicht/Bericht erstellen/PDF unterscheiden, wenn PV-Preis oder
  Batterie-Preis gesetzt sind. In diesem Fall ist das Diagramm ebenfalls
  gestapelt (Netz/PV/Speicher, dieselben Farben wie im Energiequellen-
  Diagramm darüber), darunter steht eine Zeile mit den drei Gesamtsummen
  über den angezeigten Zeitraum (z. B. "Netz: 6,45 € · PV: 1,90 € ·
  Speicher: 0,67 €"). Bei "openWB-Wert" bleibt es bei einem einzigen
  Balken, da openWBs eigener Wert nicht nach Quelle aufgeschlüsselt ist.
- **Nach Fahrzeug** — Tabelle mit Ladevorgängen, Energie, Netz-/PV-/
  Speicher-Anteil (je in %) und Kosten je Fahrzeug (nicht nach Zeitraum),
  absteigend nach Energie sortiert — zum Vergleichen mehrerer Fahrzeuge
  untereinander.

## Self-Update

Unter Einstellungen → "Update" (letzter Bereich im Dialog) steht die
aktuell installierte Version, sowie "Nach Updates suchen" und "Update".
Sofern über `docker-compose.yml` eingebunden (siehe
[DEPLOYMENT.md](DEPLOYMENT.md)), lässt sich die Anwendung so ohne
manuellen `git pull`/Rebuild aktualisieren — Details dort unter
"Self-update from the UI". Bei einer reinen Image-Installation ohne
dieses Bind-Mount (z. B. auf Synology über Container Manager) erscheinen
die beiden Buttons gar nicht erst, nur die aktuelle Version bleibt
sichtbar — es gibt dort schlicht nichts, was `git pull` an Ort und Stelle
aktualisieren könnte.
