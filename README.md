# CineVault

Eine einfache, offline laufende Mediathek für deine lokale Filmsammlung unter Windows 11.

## Voraussetzungen

- Windows 11
- Ordnerstruktur wie beschrieben:
  ```
  FILME/
    NEU/
      Filmname 1/
        film.mkv
        Subs/...
      Filmname 2/
        film.mp4
    ARCHIV/
      Filmname 3/
        film.mkv
  ```
- Python 3.10 oder neuer (https://www.python.org/downloads/, beim Setup
  **"Add python.exe to PATH"** aktivieren)
- Ein kostenloser TMDb-API-Key: https://www.themoviedb.org/settings/api
  (Konto erstellen → Einstellungen → API → "API-Schlüssel (v3 auth)")

## Installation

1. Diesen Ordner irgendwohin entpacken (z. B. `C:\Tools\CineVault`).
2. Eingabeaufforderung (`cmd`) in diesem Ordner öffnen.
3. Abhängigkeiten installieren:
   ```
   pip install -r requirements.txt
   ```
4. Programm starten:
   ```
   python main.py
   ```

Beim ersten Start wirst du gebeten, deinen `FILME`-Hauptordner auszuwählen.
Trage danach über das Zahnrad-Symbol (⚙) oben rechts deinen TMDb-API-Key ein.

## Starten ohne Konsolenfenster (empfohlen für den Alltag)

`python main.py` öffnet immer ein (schwarzes) Konsolenfenster im Hintergrund
– praktisch zum Debuggen, aber unschön für den normalen Gebrauch.

Stattdessen einfach **`CineVault.pyw`** starten (Doppelklick):
Windows öffnet `.pyw`-Dateien automatisch mit `pythonw.exe` statt
`python.exe` – dadurch erscheint **kein Konsolenfenster mehr**. Der Code
dahinter ist exakt derselbe wie bei `main.py`.

Tipp: Rechtsklick auf `CineVault.pyw` → *Verknüpfung erstellen* → die
Verknüpfung auf den Desktop oder ins Startmenü legen. Für das Icon der
Verknüpfung selbst (Windows zeigt Verknüpfungen sonst mit einem generischen
Symbol) kannst du unter Rechtsklick → Eigenschaften → Anderes Symbol die
Datei `assets/cinevault.ico` auswählen – dieselbe violette Filmklappe, die
CineVault auch für sein Fenster- und Taskleisten-Symbol verwendet.

## Eigenständige .exe bauen (optional)

**Variante A – automatisch über GitHub Actions (empfohlen, kein eigenes Python nötig):**

1. Ein (kostenloses) GitHub-Konto erstellen, falls noch nicht vorhanden: https://github.com
2. Ein neues, leeres Repository anlegen (z. B. `filmmediathek`, kann "Private" sein).
3. Den kompletten Inhalt dieses Ordners in das Repository hochladen – entweder per
   Drag&Drop über die GitHub-Weboberfläche ("Add file → Upload files") oder per Git:
   ```
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<dein-benutzername>/filmmediathek.git
   git push -u origin main
   ```
4. Im Repository oben auf den Reiter **"Actions"** klicken. Dort läuft automatisch
   der Workflow **"Build Windows EXE"** (dauert ca. 2–4 Minuten). Falls er nicht von
   selbst startet: auf den Workflow klicken → "Run workflow".
5. Wenn der Lauf grün/fertig ist, den Lauf anklicken → ganz unten bei
   **"Artifacts"** liegt `CineVault-windows-exe` zum Download bereit
   (eine ZIP-Datei mit der fertigen `CineVault.exe` drin).
6. Diese `.exe` einfach auf deinen Windows-11-PC kopieren und starten –
   **kein Python auf deinem eigenen PC nötig.**

Bei jedem weiteren Push auf das Repository (z. B. wenn ich dir künftig Code-
Änderungen schicke) baut GitHub automatisch eine neue `.exe` – du musst nur
wieder unter "Actions" das neueste Artifact herunterladen.

**Variante B – lokal auf deinem eigenen Windows-PC (falls dort Python installiert ist):**

```
build_exe.bat
```

Das erzeugt `dist\CineVault.exe`.

Egal welche Variante: Beim allerersten Start der `.exe` fragt sie dich einmalig
nach deinem `FILME`-Ordner und merkt sich den Pfad danach automatisch.

## Bedienung

- **Akzentfarbe** (⚙ Einstellungen → "Darstellung"): frei wählbar über einen
  Farbwähler, wird sofort angewendet (kein Neustart nötig) – betrifft
  Buttons, Scrollbar, Kachel-Hover-Effekt und das "NEU"-Badge.
- **Kachel-Titel**: Zeigt bewusst den **rohen Ordnernamen** (nicht den
  TMDb-Titel), zweizeilig mit Umbruch an Wortgrenzen. So bleibt deine eigene
  Dateibenennung (z. B. "Teil 1/2/3" bei Reihen) sichtbar, und falsch
  zugeordnete TMDb-Daten fallen sofort auf – der TMDb-Titel steht weiterhin
  im Detail-Fenster sowie im Tooltip der Kachel (zusammen mit dem Ordnernamen).
- **Klick auf einen Film** → öffnet das Detail-Fenster (Titel, Beschreibung,
  Besetzung, Genre, Trailer-Link, Abspielen-Button).
- **Rechtsklick auf einen Film** → Kontextmenü mit:
  - Abspielen (direkt, ohne Umweg über die Details)
  - Details anzeigen
  - Cover ändern (von Festplatte, per URL, oder Google-Bildersuche öffnen)
  - Als gesehen / ungesehen markieren
  - Für Rewatch vormerken (nur bei bereits gesehenen Filmen)
  - Erneut synchronisieren (erzwingt einen neuen Metadaten-Abgleich für
    genau diesen Film)
  - Löschen … (mit Sicherheitsabfrage, siehe unten)
- **Filminfos von Hand bearbeiten**: Im Detail-Fenster über "✏ Bearbeiten"
  lassen sich Titel, Beschreibung, Besetzung, Genre und – falls ein echter
  Link vorliegt – auch der Trailer-Link direkt eintragen oder korrigieren.
  Im Bearbeiten-Modus blenden sich zusätzlich "Cover ändern" und "TMDb-Link
  manuell zuweisen" ein (siehe unten); der "Abspielen"-Button ist dann
  ausgeblendet, da er dort nicht gebraucht wird.
- **TMDb-Link manuell zuweisen**: Findet die automatische Suche einen Film
  nicht oder ordnet ihn falsch zu (z. B. bei Remakes ohne Jahresangabe im
  Dateinamen), kannst du im Bearbeiten-Modus über "🔗 TMDb-Link manuell
  zuweisen" einen TMDb-Link oder eine TMDb-ID direkt eintragen – der Film
  wird dann ohne weitere Prüfung übernommen (Cover, Beschreibung, Besetzung,
  Genre, Trailer). Der Dialog verlinkt direkt auf die TMDb-Suche mit dem
  (bereinigten) Ordnernamen vorausgefüllt, spart also den Umweg über eine
  eigene Suche.
- **Ordner öffnen**: Button im Detail-Fenster, öffnet den Filmordner direkt
  im Explorer – praktisch, um z. B. den Dateinamen zu korrigieren.
- **Film löschen**: Über das Detail-Fenster oder das Kontextmenü, mit
  Sicherheitsabfrage. Der Ordner wird in den ganz normalen Windows-Papierkorb
  verschoben (nicht endgültig gelöscht) und lässt sich von dort jederzeit
  wiederherstellen.
- **"Für Rewatch vormerken"**: Für bereits gesehene Filme, die du noch einmal
  schauen möchtest – Button im Detail-Fenster (eigene Zeile) oder Kontextmenü,
  eigenes "REWATCH"-Badge auf der Kachel, eigener Filter-Button "Rewatch" in
  der Kopfleiste.
- **"Jetzt synchronisieren"** (oben rechts) → lädt Titel, Cover, Beschreibung,
  Genre, Hauptbesetzung und – falls vorhanden – einen YouTube-Trailer-Link für
  alle noch nicht aufbereiteten Filme aus dem Internet (TMDb). Es wird gezielt
  zuerst nach einem **deutschsprachigen** Trailer gesucht; nur wenn TMDb dazu
  keinen hat, wird als Fallback ein englischer verwendet (das Detail-Fenster
  zeigt dann klar an, dass es der englische ist). Bereits aufbereitete Filme
  werden automatisch übersprungen. Läuft im Hintergrund, die Oberfläche
  bleibt währenddessen bedienbar. Der Trailer wird **nicht heruntergeladen** –
  im Detail-Fenster öffnet ein Klick lediglich den Trailer auf YouTube im
  Standardbrowser.
  - Ist im Dateinamen **kein Jahr** erkennbar und gibt es bei TMDb mehrere
    gleichnamige Filme mit unterschiedlichem Erscheinungsjahr (typisch bei
    Remakes, z. B. Ben-Hur 1959 vs. 2016), wird das jetzt als **mehrdeutig**
    erkannt statt automatisch (und ggf. falsch) den populäreren/älteren zu
    wählen. Solche Filme bekommen den Status "Mehrdeutig" – im Detail-Fenster
    erscheint dann direkt ein **Dropdown mit allen gefundenen Versionen**
    (z. B. "Ben-Hur (2016)" / "Ben-Hur (1959)") samt Cover- und
    Beschreibungs-Vorschau zum jeweils ausgewählten Kandidaten sowie
    "Übernehmen"-Button – kein manuelles Suchen/Kopieren des TMDb-Links
    nötig. Hat TMDb für einen Kandidaten keine deutsche Beschreibung
    hinterlegt (kommt v. a. bei älteren/weniger populären Filmen vor), wird
    automatisch die englische nachgeladen (mit entsprechendem Hinweis).
    Am einfachsten über den Diagnosefilter "Mehrdeutige Filme anzeigen"
    (⚙ Einstellungen → Tab "Diagnose") findest du alle betroffenen Filme auf
    einen Blick.
- **"Ordner neu einlesen"** → prüft NEU/ARCHIV auf neu hinzugekommene oder
  entfernte Filme. Das geschieht auch automatisch beim Start und vor jeder
  Synchronisierung. Dank inkrementeller Indexierung (nur geänderte Ordner
  werden neu gelesen) dauert das auch bei ~2000 Filmen nur Sekunden.
- **Filter-Buttons "Alle / Ungesehen / Gesehen / Rewatch"** + Suchfeld (mit
  "✕"-Button zum schnellen Leeren), um die Liste einzugrenzen. "Ungesehen"
  entspricht genau dem Inhalt von `NEU`. Der Status-Text unten zeigt bei
  jedem aktiven Filter (egal ob Ungesehen/Gesehen/Rewatch, Genre, Suche oder
  Diagnosefilter) immer die tatsächlich angezeigte Trefferanzahl an.
- **Genre-Filter** (Dropdown in der Kopfleiste): füllt sich automatisch mit
  allen tatsächlich vorhandenen Genres deiner Sammlung.
- **Sortierung** (Dropdown in der Kopfleiste): Titel (A–Z) oder Älteste
  zuerst (nach Windows-Erstelldatum des Filmordners).
- **Vollständigkeits-Punkt** auf den Kacheln: **rot** = weder Cover noch
  Beschreibung vorhanden, **gelb** = nur eines von beiden vorhanden, **kein
  Punkt** = beides vorhanden (egal ob automatisch per TMDb oder von Hand
  eingetragen).
- **Hover-Effekt**: Fährt man mit der Maus über eine Kachel, wächst sie
  sanft animiert leicht auf und bekommt einen dezenten farbigen Schein –
  rein optisch, ändert nichts an der Funktion.
- Scrollen erfolgt pixelweise statt sprunghaft zeilenweise, und die Cover
  werden nur einmal (nicht bei jedem Scroll-Frame neu) auf die Zielgröße
  skaliert – das sorgt gerade bei ~2000 Filmen für spürbar flüssigeres
  Scrollen.
- **Als gesehen markieren** verschiebt den Filmordner physisch von
  `NEU` nach `ARCHIV` (und umgekehrt bei "als ungesehen markieren") –
  ganz wie gewünscht, ohne zusätzliche Verwaltungsebene.

## Serien

Eigener Programmbereich (Tab "📺 Serien"), komplett getrennt von Filmen,
aber mit demselben Funktionsumfang (Bearbeiten, TMDb-Link manuell zuweisen,
Cover ändern, Ordner öffnen, Löschen) – nur ohne Rewatch, dafür mit einer
Episoden-Checkliste.

**Einrichtung**: Unter ⚙ Einstellungen → Tab "Dateipfade" → Bereich
"Serien" einen eigenen Ordner auswählen. Komplett optional – ohne
eingerichteten Ordner bleibt der Serien-Tab einfach ungenutzt, der Rest der
App funktioniert unverändert.

**Ordnerstruktur**: Analog zu Filmen, aber mit einem dritten Zwischenordner:
```
SERIEN/
  NEU/          <- noch nicht begonnen
  LAUFEND/      <- wird gerade geschaut
  ARCHIV/       <- abgeschlossen
```
Innerhalb einer Serie werden Staffel/Episode automatisch erkannt – egal ob
klassische Staffelordner ("Staffel 01/S01E02.mkv"), Episodendateien direkt
im Serienordner, oder ein eigener Ordner pro Episode (typisch bei
Szene-Release-Downloads). Bonus-/Zusatzordner (Extras, Making-of, ...)
werden dabei zuverlässig ausgeschlossen.

**Episoden abhaken statt verschieben**: Einzelne Episoden werden per
Checkbox im Detail-Fenster als gesehen markiert – reines Datenbank-Flag,
es wird dabei nichts auf der Festplatte bewegt. Erst die komplette Serie
wandert zwischen den drei Ordnern:
- **NEU → LAUFEND**: automatisch beim Abhaken der allerersten Episode,
  oder jederzeit manuell über "Serie beginnen".
- **→ ARCHIV**: ausschließlich manuell über "Serie abschließen" – bewusst
  keine Automatik anhand von TMDbs Serienstatus (kann verspätet/falsch
  gepflegt sein).

**TMDb-Sync**: Lädt Serien-Metadaten (Titel, Beschreibung, Cover, Genre,
Besetzung, Trailer) UND die vollständige Beschreibung jeder einzelnen
Episode. Mehrdeutige Treffer werden wie bei Filmen über ein
Auswahl-Dropdown mit Vorschau aufgelöst statt automatisch geraten.
Episoden, die TMDb nicht kennt (z. B. Spezialfolgen), bleiben ganz normal
abspielbar, nur ohne Beschreibung.

## Wo werden die Daten gespeichert?

Im `FILME`-Ordner liegen ausschließlich deine Filme selbst – keinerlei
Programmdaten:

```
FILME/
  NEU/            ← deine Filme (unverändert von dir gepflegt)
  ARCHIV/         ← deine Filme (unverändert von dir gepflegt)
```

Datenbank, Cover, Einstellungen (inkl. TMDb-API-Key) und der gemerkte Pfad zu
deinem `FILME`-Ordner liegen alle zusammen in einem `Mediathek`-Unterordner
**direkt neben der `CineVault.exe`** (z. B.
`C:\Programme\CineVault\Mediathek\`):

```
C:\Programme\CineVault\
  CineVault.exe
  Mediathek\
    mediathek.db
    config.json
    pointer.json
    MEDIA\
      covers\     ← heruntergeladene/manuelle Cover in voller Größe
      thumbs\     ← kleine Vorschaubilder für die Kachelansicht
```

Das heißt konkret:
- Tauschst du nur die `.exe` gegen eine neuere Version aus (im selben
  Ordner), bleiben alle gesyncten Daten **inklusive Cover** erhalten, da
  `Mediathek\` ein eigener Unterordner ist.
- Löschst/deinstallierst du den kompletten Programmordner, sind auch
  Datenbank, Cover und Einstellungen weg – der `FILME`-Ordner mit deinen
  Filmen selbst bleibt davon vollkommen unberührt.
- Cover aus einer älteren CineVault-Version (die noch in `FILME\MEDIA` lagen)
  werden beim ersten Start automatisch in den neuen Ort migriert.

## Netzwerkfreigabe (Streaming)

Unter ⚙ Einstellungen im Tab "Netzwerk" kannst du CineVault so
einstellen, dass es im selben WLAN einen kleinen Webserver bereitstellt –
praktisch, um unterwegs (im Heimnetz) am Handy durch die Sammlung zu
stöbern und Filme/Serien direkt in VLC abzuspielen. Zeigt sowohl Filme als
auch Serien (eigener Tab in der mobilen Ansicht). Bis auf eine Ausnahme
komplett lesend: Episoden können von unterwegs als gesehen/ungesehen
markiert werden (genau dieselbe Funktion wie das Abhaken im Detail-Fenster)
– löschen, bearbeiten oder synchronisieren geht über das Netzwerk
weiterhin nicht.

**Einrichtung:**
1. ⚙ Einstellungen → Tab "Netzwerk" → Haken bei "Aktivieren" setzen,
   Speichern.
2. Die angezeigte Adresse (`http://<IP>:8765`) am Handy im selben WLAN im
   Browser öffnen – oder einfach den dort angezeigten **QR-Code scannen**,
   dann musst du nichts abtippen.
3. Film/Episode antippen → "▶ In VLC abspielen". Erkennt automatisch, ob du
   am Handy (Android) oder am PC (Windows/macOS/Linux) bist:
   - **Android**: öffnet VLC direkt mit dem Video.
   - **Desktop**: lädt eine winzige `.m3u`-Playlist-Datei herunter, die
     VLC (sofern als Standard-Handler für diesen Dateityp registriert,
     üblich nach einer normalen Windows-Installation) automatisch öffnet.

**Zum Startbildschirm hinzufügen**: Am Handy über das Browser-Menü "Zum
Startbildschirm hinzufügen" wählen – "CineVault Mobile" erscheint dann mit
eigenem Icon (nicht dem generischen Browser-Symbol) wie eine normale App.

Die mobile Seite hat dieselben Filter wie am PC: die Hauptfilter
(Alle/Ungesehen/Gesehen/Rewatch), eine Suche, sowie Dropdowns für
**Sortierung** (Titel A–Z / Älteste zuerst) und **Genre**. Alle Einstellungen
bleiben auch beim Zurücknavigieren von der Detailseite erhalten.

**Was das NICHT kann** (bewusst so gebaut):
- Kein Löschen, Bearbeiten, Synchronisieren oder sonst irgendein Schreib-
  zugriff über das Netzwerk – nur Ansehen und Abspielen.
- Kein Login/keine Verschlüsselung (reines HTTP) – daher nur in
  vertrauenswürdigen Netzwerken aktivieren (dein eigenes Heim-WLAN), nicht
  in einem Gäste- oder öffentlichen WLAN.
- Getestet und gebaut für **Android**. Auf dem iPhone lässt sich VLC nicht
  auf demselben Weg direkt aus dem Browser heraus öffnen.

Der Port lässt sich bei Bedarf ändern (Standard: 8765) – z. B. falls er auf
deinem Rechner bereits belegt ist.

## Backup

Unter ⚙ Einstellungen im Tab "Dateipfade" (Bereich "Backup") kannst du einen
Zielordner auswählen (z. B. ein Cloud-Sync-Laufwerk wie Google Drive) und
über "Jetzt Backup erstellen" eine Sicherung anstoßen, oder den Haken
"Automatisch bei jedem Beenden sichern" setzen. Während des Sicherns zeigt
der Button "⏳ Backup läuft …" an (läuft im Hintergrund, der Rest des
Dialogs bleibt bedienbar); beim automatischen Backup vorm Schließen
erscheint kurz eine "Bitte warten"-Anzeige.

Gesichert wird der **komplette Programmordner** – nicht nur die Datenbank:
Code (main.py, CineVault.pyw, der komplette `mediathek`-Ordner, Icons, …)
UND Datenbank/Cover/Einstellungen zusammen. Geht mal etwas kaputt oder
verloren, reicht es, den Backup-Ordner `CineVault-Backup\` 1:1 zurückzukopieren
(bzw. an dessen Stelle den Programmordner zu ersetzen) – alles läuft danach
wieder exakt wie zuvor.

Je nach Aenderungsverhalten der Dateien kommen dabei unterschiedliche
Strategien zum Einsatz:
- **Programmcode**: ändert sich nur bei einem Update – wird daher
  inkrementell kopiert (`__pycache__`-Ordner werden dabei übersprungen).
- **Datenbank** (`mediathek.db`): ändert sich laufend, ist aber klein – wird
  daher bei jedem Durchlauf komplett neu über SQLites eigene Backup-Funktion
  gesichert (schnell, und garantiert konsistent, auch während CineVault
  läuft).
- **Cover** (`MEDIA\`): können zusammen mehrere hundert MB ausmachen, ändern
  sich nach dem ersten Sync aber praktisch nie wieder – werden daher
  ebenfalls **inkrementell** kopiert.

Dadurch ist jedes Backup nach dem allerersten Mal sehr schnell, auch bei
"automatisch bei jedem Beenden".

⚠️ **Trotzdem gilt weiterhin**: Die laufende Datenbank im `Mediathek`-Ordner
selbst sollte NIE direkt in einem Cloud-Sync-Ordner liegen (also nicht den
kompletten Programmordner in Google Drive/OneDrive verschieben und *von
dort aus* CineVault betreiben). SQLite-Datenbanken ändern sich laufend im
Hintergrund (WAL-Modus), das Sync-Programm erkennt "wird gerade benutzt"
nicht zuverlässig – im schlimmsten Fall drohen eine beschädigte Datenbank
oder angelegte "Konflikt-Kopien". Der fertige Backup-**Snapshot** im
`CineVault-Backup\`-Ordner dagegen ist unproblematisch (abgeschlossene,
nicht mehr aktiv beschriebene Dateien) – dieser Ordner darf also
gefahrlos in Google Drive/OneDrive liegen. Nur der Programmordner, mit dem
du tatsächlich arbeitest, sollte lokal bleiben.

## Der FILME-Ordner ändert sich / wird verschoben

Kein Problem und kein Datenverlust: Datenbank, Cover und Einstellungen
liegen ja unabhängig davon im Programmordner. Findet CineVault beim Start
den zuletzt gemerkten `FILME`-Ordner nicht mehr (weil verschoben, umbenannt
oder auf einem nicht angeschlossenen Laufwerk), fragt es dich einfach erneut
danach – wie beim allerersten Start.

Willst du den Ordner proaktiv ändern (z. B. weil du auf eine neue Festplatte
umgezogen bist), geht das auch direkt: ⚙ Einstellungen → Tab "Dateipfade"
→ Bereich "Bibliothek" → "Ändern …". Anschließend einmal CineVault neu starten.

## Problembehandlung

Falls du nach einer Synchronisierung prüfen willst, welche Filme noch Lücken
haben: Unter dem Zahnrad-Symbol (⚙ Einstellungen) im Tab "Diagnose" gibt es
einen Bereich mit unauffälligen **Diagnose-Filtern**:
- **"Nicht synchronisierte Filme anzeigen"** – Status pending/nicht
  gefunden/Fehler/**mehrdeutig** (siehe unten).
- **"Mehrdeutige Filme anzeigen"** – nur Filme mit Status "Mehrdeutig",
  zum bequemen Durchklicken und Auflösen.
- **"Filme ohne Beschreibung anzeigen"**
- **"Filme ohne Cover anzeigen"**
- **"Fehlende Filme anzeigen (Ordner nicht mehr gefunden)"** – für Filme,
  die direkt im Explorer gelöscht (statt über CineVault entfernt) wurden.
  Solche Filme bleiben ganz normal in der Übersicht sichtbar (erkennbar am
  roten "MISSING"-Badge auf der Kachel), der Datenbankeintrag bleibt
  ebenfalls bestehen (kein automatisches Löschen). Dieser Filter isoliert
  bei Bedarf nur die fehlenden Filme auf einen Blick.

Getrennt davon, in einem eigenen Bereich **"Nachladen"** (das ist eine
echte Aktion, kein reiner Filter):
- **"Fehlende Besetzung/Genre/Trailer nachladen"** – praktisch, falls du
  früher schon synchronisiert hast, bevor CineVault diese Felder
  unterstützte: fragt für die betroffenen Filme direkt die bereits bekannte
  TMDb-ID erneut ab und ergänzt **nur echte Lücken** bei Besetzung, Genre
  und Trailer (kostet keine zusätzlichen Anfragen, da alles aus derselben
  TMDb-Abfrage kommt). Titel, Beschreibung, Cover, bereits vorhandene bzw.
  von Hand eingetragene Werte und eine eventuell manuell getroffene
  Zuordnung bleiben dabei garantiert unangetastet – kein komplettes
  Neu-Synchronisieren, keine erneute Titelsuche, kein Risiko für bereits
  erledigte manuelle Arbeit.

Ein Klick filtert die Hauptliste entsprechend; über den Filter-Button "Alle"
oben kommst du wieder zur kompletten Liste zurück.

**Status "Mehrdeutig"**: Bedeutet, dass TMDb mehrere gleichnamige Filme mit
unterschiedlichem Erscheinungsjahr gefunden hat (typisch bei Remakes), im
Dateinamen aber kein Jahr steht, um automatisch zu entscheiden. CineVault
rät in diesem Fall bewusst nicht, sondern zeigt im Detail-Fenster direkt ein
Dropdown mit allen gefundenen Versionen (Titel + Jahr) an – einfach die
richtige auswählen und auf "Übernehmen" klicken. Alternativ funktioniert
weiterhin auch "✏ Bearbeiten" → "🔗 TMDb-Link manuell zuweisen" mit einem
selbst herausgesuchten Link.

**Taskleisten-Icon**: Zeigt Windows trotz des eingebauten Fixes weiterhin
nur das generische Symbol an, ist das ein bekanntes, hartnäckiges
Eigenheit-Problem bei mit `python.exe`/`pythonw.exe` gestarteten Programmen.
Am zuverlässigsten löst sich das durch eine gebaute `.exe` (siehe oben) –
dort ist das Icon fest in die Datei eingebettet und unterliegt nicht mehr
diesem Verhalten.

Falls sich das Programm nicht (mehr) starten lässt oder abstürzt: Neben der
`.exe` erscheint automatisch eine Datei **`crash.log`** mit der genauen
Fehlermeldung – am einfachsten den Inhalt dieser Datei mitschicken, dann
lässt sich die Ursache gezielt beheben.

## Version & Änderungsprotokoll

Die aktuelle Version steht unten rechts im Einstellungen-Dialog (⚙). Alle
bisherigen und künftigen Änderungen stehen chronologisch in
[`CHANGELOG.md`](./CHANGELOG.md).

## Hinweise

- Es wird ausschließlich für die Schaltfläche "Jetzt synchronisieren"
  eine Internetverbindung benötigt (Abfrage bei TMDb). Alles andere läuft
  komplett offline.
- Erkannte Video-Endungen: `.mkv .mp4 .avi .mov .m4v .wmv .ts`. Liegen
  mehrere Videodateien in einem Filmordner, wird automatisch die größte
  Datei als Hauptfilm verwendet.
- Titel-Erkennung: Aus dem Ordnernamen werden Release-Tags (1080p, BluRay,
  x264, German, …) sowie ein evtl. enthaltenes Jahr automatisch entfernt/
  erkannt, bevor bei TMDb gesucht wird. Falls die Erkennung daneben liegt,
  kannst du im Detail-Fenster über "✏ Bearbeiten" Titel, Beschreibung,
  Besetzung und Genre jederzeit von Hand setzen, oder gleich per "🔗 TMDb-Link
  manuell zuweisen" den passenden Film direkt verknüpfen.
- **Schutz vor Fehltreffern**: Ein TMDb-Ergebnis wird nur dann übernommen,
  wenn dessen Titel wirklich zum Ordnernamen passt (bzw. bei exakt
  übereinstimmendem Erscheinungsjahr auch bei einer nur moderaten
  Titelähnlichkeit, z. B. leicht abweichender Untertitel). Ist sich das
  Programm nicht sicher genug – etwa bei kurzen, mehrdeutigen Titeln wie
  "Haus" – wird lieber **kein** Treffer übernommen (Status "Bei TMDb nicht
  gefunden") als ein falscher Film mit falschem Cover und falscher
  Beschreibung. Gibt es bei exakt passendem Titel mehrere Filme mit
  unterschiedlichem Jahr (Remakes) und steht kein Jahr im Dateinamen, gilt
  der Fall als "Mehrdeutig" (siehe Abschnitt Problembehandlung oben). Der
  Ordnername/Dateiname bleibt in beiden Fällen immer unangetastet; betroffen
  ist ausschließlich, welche Online-Metadaten angezeigt werden. Solche Fälle
  erkennst du am roten Punkt oben links auf dem Cover in der Kachelansicht
  und kannst sie über "✏ Bearbeiten" → "🔗 TMDb-Link manuell zuweisen" von
  Hand auflösen.
