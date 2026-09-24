# Änderungsprotokoll (CineVault)

Versionsnummern wurden erst nachträglich eingeführt (ab v1.8.0). Die
Einträge bis einschließlich v1.8.0 sind daher rückwirkend rekonstruiert und
ohne genaues Datum; ab jetzt wird jede Änderung hier mit fortlaufender
Versionsnummer festgehalten.

## v2.4.0 – Neue Sortierung: nach Jahr
Zusätzliche Option "Jahr (neueste zuerst)" im Sortier-Dropdown – für Filme
UND Serien, auf dem Desktop UND in CineVault Mobile. Bei gleichem Jahr
alphabetisch als Tie-Breaker; Titel ohne bekanntes Jahr (noch nicht
synchronisiert) rutschen ans Ende statt die Sortierung durcheinander zu
bringen. Mit Testfällen für beide Bereiche und den echten Mobile-Server
abgesichert.

## v2.3.1 – Bugfix: build_exe.bat fand PyInstaller nicht
`build_exe.bat` rief bisher einfach `pyinstaller` auf, in der Annahme,
dass das nach `pip install` automatisch im PATH liegt. Ist auf vielen
Windows-Installationen aber nicht garantiert – `pip` installiert das
Programm zwar korrekt, aber der dabei erzeugte "Scripts"-Ordner mit
`pyinstaller.exe` landet nicht immer automatisch im PATH (abhängig von der
Python-Installationsart). Ruft PyInstaller jetzt stattdessen über
`python -m PyInstaller` auf – das funktioniert unabhängig vom PATH, solange
`pip install -r requirements.txt` in derselben Python-Installation gelaufen
ist. Weicht zusätzlich automatisch auf den `py`-Launcher aus, falls
`python` selbst nicht gefunden wird, und zeigt bei einem echten Fehlen von
PyInstaller jetzt eine klare Fehlermeldung mit dem genauen Befehl zum
Nachinstallieren, statt einer kryptischen Fehlermeldung. GitHub-Actions-
Workflow aus Konsistenzgründen ebenfalls angepasst.

## v2.3.0 – "Alle Episoden als gesehen markieren"
Neuer Rechtsklick-Eintrag auf der Serien-Kachel – praktisch v.a. beim
erstmaligen Einpflegen bereits komplett geschauter Serien, ohne jede
Episode einzeln abhaken zu muessen. Mit Bestätigungsdialog (da Sammel-
Aktion). Verhält sich konsistent zum bestehenden Einzel-Abhaken:
- Löst denselben automatischen NEU→LAUFEND-Übergang aus wie das Abhaken
  einer einzelnen Episode.
- Springt bewusst NICHT automatisch nach ARCHIV – bleibt wie überall sonst
  eine bewusste, manuelle Aktion.
- Als "fehlend" markierte Episoden (Ordner nicht mehr gefunden) werden
  nicht mit angefasst.
- Intern über einen einzigen SQL-Befehl statt einer Schleife über
  hunderte Episoden – bleibt auch bei sehr großen Serien flott.

Mit vollständiger Testreihe abgesichert (inkl. Automatik-Übergang,
mehrfachem Aufruf, und dass fehlende Episoden korrekt ausgenommen bleiben).

## v2.2.1 – Programmstart beschleunigt
Zwei konkrete Ineffizienzen im Scan-Vorgang behoben (rein intern, keine
Verhaltensänderung – dieselbe Erkennungslogik, nur schneller):

- **N+1-Abfrage-Problem behoben**: Der Scan fragte bisher für JEDEN Film
  bzw. JEDE Serie einzeln in der Datenbank nach ("existiert der schon?") –
  bei ~2000 Filmen also 2000 einzelne SQL-Abfragen statt einer. Lädt jetzt
  einmal alle bestehenden Einträge und schlägt sie danach nur noch im
  Arbeitsspeicher nach.
- **Serien-Signaturberechnung eingegrenzt**: Um zu erkennen, ob sich
  irgendwo in einer Serie etwas geändert hat, wurde bisher bei JEDEM
  Programmstart der KOMPLETTE Ordnerbaum jeder Serie rekursiv durchsucht –
  bei Serien mit einem Ordner pro Episode (z. B. Dragon Ball Z mit 291
  Ordnern) entsprechend teuer, und das für jede einzelne Serie bei jedem
  Start. Prüft jetzt nur noch 2 Ebenen tief (Serie → Staffel/Episode-Ordner
  → deren Inhalt) – das reicht nachweislich aus, um jede relevante
  Änderung zu erkennen, geht aber ohne das Durchlaufen der eigentlichen
  Videodateien aus. Zusätzlich auf `os.scandir()` umgestellt statt
  `Path.iterdir()`, das unter Windows Zeitstempel bereits beim Auflisten
  mitliefert statt pro Eintrag einen eigenen Systemaufruf zu brauchen.

Mit ausführlicher Testreihe abgesichert (u. a. gezielt mit einer
291-Episode-Ordner-Serie durchgespielt): Erkennung neuer/geänderter/
fehlender Filme und Serien, alle drei Serien-Strukturmuster, sowie eine
gezielte Prüfung, dass eine Änderung 2 Ebenen tief (innerhalb eines
Staffel- oder Episode-Ordners) trotz der Kürzung zuverlässig erkannt wird –
keine Regression gegenüber dem bisherigen Verhalten.

**Ehrlicher Hinweis**: Ich konnte das mangels großer echter Sammlung und
eigenem Windows-System hier nicht mit echten Zeitmessungen gegentesten –
die Optimierungen beheben aber zwei nachweisbare algorithmische
Ineffizienzen (unnötige Einzelabfragen, unnötig tiefe Rekursion), die bei
~2000 Filmen und Serien mit hunderten Episode-Ordnern sich tatsächlich
spürbar auf die Startzeit auswirken sollten.

## v2.2.0 – Titelleiste, Mobile für Serien, Ansicht-Persistenz
Großes Update mit mehreren größeren Bausteinen:

**Optik**
- Titelleiste (Hauptfenster + alle Dialoge) jetzt dunkel in App-Farbe statt
  Windows-Akzentfarbe, kleines Icon + Fenstertitel daraus entfernt
  (Minimieren/Maximieren/Schließen bleiben unangetastet). Windows-
  spezifische DWM-/WinAPI-Technik – konnte mangels eigenem Windows-System
  nicht selbst gegengetestet werden.
- `.local`-Adresse (mDNS/`zeroconf`) endgültig entfernt wie vorgemerkt –
  IP-Adresse + QR-Code bleiben der zuverlässige Weg.

**CineVault Mobile jetzt auch für Serien**
- Eigener "📺 Serien"-Tab in der mobilen Ansicht, gleiches Grundgerüst wie
  bei Filmen (Suche, Sortierung, Genre-Filter, Status-Filter
  Alle/Neu/Laufend/Archiv).
- Serien-Detailseite mit Episodenliste (nach Staffel gruppiert), "▶
  Nächste Folge abspielen", und direktem Abspielen jeder einzelnen Episode
  in VLC.
- **Episoden können von unterwegs als gesehen/ungesehen markiert werden**
  (Ausnahme vom sonst reinen Lesezugriff – siehe README/Einstellungen, dort
  entsprechend aktualisiert). Löst denselben automatischen
  NEU→LAUFEND-Übergang aus wie im Detail-Fenster. Mit vollständigem
  End-to-End-Test verifiziert (echter Server, echte HTTP-Anfragen).

**Serien-Detail-Fenster**
- Episoden werden jetzt IMMER nach Staffel gruppiert (auch bei nur einer
  Staffel: "Staffel 01").
- Staffel-Überschrift deutlich markanter (größer, fett) + Trennstrich
  zwischen Staffeln.
- Staffeln ein-/ausklappbar (Pfeil-Symbol, auch per Klick auf den
  Überschrift-Text) – Zustand wird pro Serie gespeichert und beim nächsten
  Öffnen wiederhergestellt, ebenso die Scrollposition der Episodenliste.
- Fortschrittsanzeige auf den Kacheln ("12/24") wird jetzt immer gezeigt,
  auch bei 0/x oder x/x.

**Ansicht merken**
- Aktiver Tab (Filme/Serien), Filter, Sortierung, Genre-Auswahl, Suchtext
  und Scrollposition werden beim Beenden gespeichert und beim nächsten
  Start automatisch wiederhergestellt – für beide Bereiche getrennt.

**Sonstiges**
- Test-Skripte (`test_series_scan.py`, `test_series_sync.py`) werden ab
  sofort nicht mehr mit ausgeliefert (waren nur für die Entwicklung
  gedacht).

## v2.1.1 – Bugfix: Manuelle TMDb-Zuweisung erkannte keine Serien-Links
Die Erkennung einer TMDb-ID aus einem eingefügten Link war ausschließlich
auf Film-Links (`/movie/...`) ausgelegt – ein Serien-Link wie
`themoviedb.org/tv/456-the-simpsons` wurde nicht erkannt ("Daraus konnte
keine ID erkannt werden"), obwohl die Funktion sowohl beim Film- als auch
beim Serien-Detail-Fenster zum Einsatz kam. Erkennt jetzt beide
Linkformate (`/movie/` und `/tv/`); Funktion dafür passend umbenannt
(`parse_tmdb_movie_id` → `parse_tmdb_id`). Mit mehreren Testfällen
verifiziert (Film-Links, Serien-Links, reine ID, ID mit Titel-Slug).

## v2.1.0 – Serien-Feinschliff: Filter, Staffel-Checkbox, klarere Buttons
Erstes Feedback nach dem echten Praxistest von v2.0.0 umgesetzt:

- **Volle Such-/Filterleiste für Serien** – jetzt 1:1 wie bei Filmen: Suche,
  Sortierung (Titel A–Z / Älteste zuerst), Genre-Filter, sowie die
  Statusfilter Alle/Neu/Laufend/Archiv (statt Ungesehen/Gesehen/Rewatch bei
  Filmen).
- **Diagnose-Filter jetzt auch für Serien** (⚙ Einstellungen → Tab
  "Diagnose"): nicht synchronisiert / mehrdeutig / ohne Beschreibung / ohne
  Cover / fehlend – als eigener Bereich neben den bestehenden Film-Filtern.
  Ein Klick wechselt automatisch in den passenden Tab.
- **Staffel-Checkbox**: In der Episoden-Checkliste hat jede Staffel-
  Überschrift jetzt eine eigene Checkbox, die alle Episoden dieser Staffel
  auf einmal abhakt (bzw. wieder entabhakt). Zeigt dabei den tatsächlichen
  Fortschritt an (leer/voll/teilweise). Mit Testfall verifiziert (inkl. des
  Falls "teilweise abgehakt" → nächster Klick komplettiert statt zu leeren).
- **Play-Buttons in der Episodenliste** deutlicher als solche erkennbar:
  jetzt runde, in der Akzentfarbe eingefärbte Buttons statt eines einzelnen
  kleinen Zeichens auf grauem Grund.
- **Einheitliche Kopfzeilen-Titel**: "CineVault Movies" bzw. "CineVault
  Series" statt vorher uneinheitlich "CineVault" / "Serien" (Symbole 🎬/📺
  bleiben wie gehabt).

## v2.0.0 – Serien-Unterstützung (komplett neuer Programmbereich)
Das große neue Feature: CineVault verwaltet jetzt neben Filmen auch
komplette Serien – als eigener, bewusst getrennter Programmbereich (eigener
Tab), der aber dieselbe Infrastruktur nutzt (Datenbank, Backup, Sync-Muster).

**Ordnerstruktur & Erkennung**
- Eigener SERIEN-Wurzelordner (komplett optional, unter ⚙ Einstellungen →
  "Dateipfade" einzurichten) mit den Unterordnern `NEU` / `LAUFEND` /
  `ARCHIV` – der Zwischenzustand "begonnen, aber noch nicht fertig" gibt es
  nur bei Serien.
- Automatische Erkennung von Staffel/Episode aus Ordner- und Dateinamen –
  deckt alle in der Praxis vorkommenden Strukturen ab: klassische
  Staffelordner, Episodendateien direkt im Serienordner, UND ein Ordner pro
  Episode (typisch bei Szene-Release-Downloads). Funktioniert auch bei
  uneinheitlicher Nummerierung (kein alphabetischer Sortier-Bug mehr bei
  "Folge 2" vs. "Folge 10"), und bei Serien ganz ohne erkennbare Nummern im
  Namen (z. B. Spezialfolgen) über eine stabile Ersatz-Reihenfolge.
- Echte Bonus-/Zusatzordner (Extras, Making-of, Interviews, ...) werden
  weiterhin zuverlässig ausgeschlossen.

**TMDb-Sync**
- Serien-Metadaten (Titel, Beschreibung, Cover, Genre, Besetzung, Trailer)
  UND vollständige Beschreibung pro einzelner Episode werden von TMDb
  geladen. Mehrdeutige Treffer (z. B. gleichnamige Reboots) werden wie bei
  Filmen über ein Auswahl-Dropdown mit Vorschau aufgelöst, nie automatisch
  geraten. Episoden, die TMDb nicht kennt (z. B. Spezialfolgen), bleiben
  ganz normal abspielbar, nur ohne Beschreibung.

**Episoden-Checkliste statt einfachem Gesehen/Ungesehen**
- Einzelne Episoden werden per Checkbox abgehakt – ein reines Metadaten-Flag,
  es wird dabei NICHTS auf der Festplatte verschoben.
- Erst die komplette Serie wandert zwischen NEU/LAUFEND/ARCHIV: automatisch
  beim Abhaken der allerersten Episode (NEU → LAUFEND), und manuell über
  eine eigene Aktion für alle Übergänge (inkl. "Serie abschliessen" nach
  ARCHIV – bewusst ohne jede Automatik anhand von TMDbs Serienstatus, der
  unzuverlässig gepflegt sein kann).

**Oberfläche**
- Eigener "📺 Serien"-Tab mit eigener Kachel-Ansicht (Status-Badge
  NEU/LAUFEND, Fortschrittsanzeige "12/24" bei begonnenen Serien).
- Detail-Fenster mit demselben Funktionsumfang wie bei Filmen (Bearbeiten,
  TMDb-Link manuell zuweisen inkl. Suchlink, Cover ändern, Ordner öffnen,
  Löschen) – bewusst OHNE Rewatch (ergibt bei Serien keinen Sinn), dafür MIT
  der Episoden-Checkliste und einer Status-Aktion statt des einfachen
  Umschalters.

**Rein internes Detail**: Serien-Cover liegen im selben MEDIA-Ordner wie
Filme (nur im eigenen Unterordner) und die Datenbank ist dieselbe Datei wie
bei Filmen – ein bestehendes Backup sichert Serien-Daten dadurch automatisch
mit, ganz ohne Änderung an der Backup-Funktion selbst.

Die gesamte Backend-Logik (Ordner-Scan, TMDb-Sync, Status-Übergänge) wurde
mit umfangreichen Testfällen abgesichert; die Oberfläche selbst konnte
mangels lokalem Windows/Qt-System nicht selbst gegengetestet werden – hier
zählt der erste echte Test bei dir.

## v1.25.1 – .local-Adresse direkt in der prominenten Anzeige
Die `cinevault.local`-Adresse (falls `zeroconf` installiert ist) steht jetzt
direkt mit in der großen, hervorgehobenen Adress-Box in den Einstellungen –
vorher stand sie nur im kleineren Hinweistext darunter. Beide Adressen
zusammen an einem Blick sichtbar, IP-Adresse weiterhin zuerst als die
verlässliche Angabe.

## v1.25.0 – "CineVault Mobile"-Branding, optionale .local-Adresse
- Mobile Seite (Titel, Überschrift, Web-App-Manifest) heißt jetzt
  "CineVault Mobile" statt schlicht "CineVault" – macht auf den ersten
  Blick klar, dass es sich um die abgespeckte, rein lesende Ansicht handelt.
- **Neu, rein optional**: Zusätzlich zur IP-Adresse wird jetzt (sofern das
  neue, optionale Paket `zeroconf` installiert ist) `cinevault.local` per
  mDNS/Bonjour im Heimnetz angemeldet – eine echte Internet-Domain wie
  "cinevault.live" wäre hier der falsche Ansatz gewesen (würde eine
  Portweiterleitung nach außen erfordern, genau das Gegenteil vom
  "nur im eigenen WLAN"-Sicherheitskonzept), `.local`-Adressen sind die
  dafür vorgesehene lokale Alternative (dieselbe Technik wie z. B. bei
  Druckern im Heimnetz). Wird in den Einstellungen als "eventuell auch
  erreichbar unter" zusätzlich zur (weiterhin verlässlichen) IP-Adresse
  angezeigt. Ob die Auflösung tatsächlich funktioniert, hängt von
  Betriebssystem/Router ab (Android/iOS in der Regel zuverlässig, Windows
  je nach Version durchwachsen) – schlägt es fehl, wird es still
  übersprungen, ohne den eigentlichen Streaming-Server zu beeinträchtigen.
  Mit Testfall verifiziert (Server läuft einwandfrei, auch ohne installiertes
  `zeroconf`-Paket).

## v1.24.3 – Mobile Toolbar: Layout aufgeteilt
Sortierung/Genre-Dropdowns saßen bisher in derselben Zeile wie Suchfeld und
Lupe – in Summe zu breit. Jetzt zwei Zeilen: Suchfeld + Lupe oben, die
beiden Dropdowns (je zur Hälfte) darunter. Funktional unverändert, alle
Werte werden weiterhin gemeinsam übermittelt. Mit Testfall verifiziert.

## v1.24.2 – Sortierung & Genre-Filter auch auf der mobilen Seite
- Die mobile Übersichtsseite hat jetzt dieselben Dropdown-Filter wie am PC:
  **Sortierung** (Titel A–Z / Älteste zuerst) und **Genre** (füllt sich
  automatisch mit allen tatsächlich vorhandenen Genres). Auswahl wendet
  sich direkt beim Ändern an (kleines, unauffälliges Inline-JavaScript nur
  für dieses automatische Absenden – die Seite bleibt ansonsten wie gehabt
  rein lesend ohne jede schreibende Funktionalität).
- Beide Einstellungen bleiben wie Suche/Filter auch beim Wechsel auf die
  Detailseite und zurück erhalten. Mit 6 Testfällen verifiziert (beide
  Sortierrichtungen, Genre-Filter, Dropdown-Inhalte, aktuelle Auswahl
  markiert, Zustandserhalt beim Zurücknavigieren).

## v1.24.1 – VLC-Start auch unter Windows/Desktop
- Der "▶ In VLC abspielen"-Button auf der mobilen Detailseite nutzte bisher
  ausschließlich den Android-spezifischen `intent://`-Link, der auf
  Desktop-Browsern (z. B. beim Testen am Laptop) ins Leere lief.
- Die mobile Seite erkennt jetzt anhand des Browsers (User-Agent), ob sie
  auf Android oder einem Desktop-System läuft: Android bekommt weiterhin
  den Intent-Link, alle anderen (Windows, macOS, Linux) bekommen stattdessen
  eine winzige `.m3u`-Playlist-Datei zum Download – VLC registriert sich bei
  der Windows-Installation üblicherweise selbst als Standard-Handler für
  diesen Dateityp, wodurch ein Klick VLC direkt mit dem Stream öffnet, ganz
  ohne eigene Protokoll-Registrierung. Mit Testfall verifiziert (korrekte
  Weiche je nach User-Agent, gültiger Playlist-Inhalt inkl. Download-Header).

## v1.24.0 – TMDb-Suchlink, Titel-Parsing-Bugfix, prominentere Netzwerk-Anzeige
- **TMDb-Suchlink im "manuell zuweisen"-Dialog**: Statt erst selbst zu
  themoviedb.org zu wechseln, öffnet ein Klick direkt die TMDb-Suche mit
  dem (bereinigten) Titel des Films vorausgefüllt.
- **Bugfix Titel-Bereinigung**: Beim Entfernen der Jahreszahl aus dem
  Ordnernamen wurden die umgebenden Trennzeichen mitgelöscht, wodurch
  Wörter direkt davor/danach zusammenrutschten (z. B. wurde aus
  "Ringe.2001.German" fälschlich "RingeGerman" statt "Ringe German"). Das
  betraf nicht nur die neue Suchlink-Funktion, sondern auch die eigentliche
  automatische TMDb-Suche selbst – dürfte also nebenbei ein paar bisher
  nicht erkannte Filme zukünftig korrekt finden. Mit mehreren Testfällen
  verifiziert.
- **Netzwerk-Tab aufgeräumt**: Adresse + QR-Code jetzt als größerer,
  horizontal zentrierter Block – deutlich prominenter als vorher links
  hängend.

## v1.23.3 – Kachel-Zentrierung endgültig zurückgenommen
Nach drei Anläufen (v1.21.1, v1.23.1, v1.23.2) – einer davon mit komplettem
Programm-Hänger, die anderen beiden ohne jede Verbesserung trotz in
Isolation korrekt getesteter Rechenlogik – wird die horizontale
Kachel-Zentrierung endgültig wieder entfernt. Die zugrunde liegende
Qt-Eigenheit ließ sich aus der Ferne (ohne eigenes Windows-System zum
Testen) offenbar nicht zuverlässig genug nachvollziehen, um sie sicher zu
beheben. Das Grid ist wieder im bewährten, stabilen Zustand vor v1.21.1:
linksbündig, mit etwas Rand rechts bei nicht exakt passender Fensterbreite
– rein kosmetisch, aber zuverlässig.

## v1.23.2 – Bugfix: Zentrierung bei wenigen Treffern & Springen beim Resize
Zwei Probleme mit der Zentrierung aus v1.23.1 behoben:
- **Wenige Treffer standen untereinander statt nebeneinander** (z. B. bei
  einer Suche mit nur 2 oder 4 Ergebnissen), obwohl reichlich Platz da war.
  Ursache: Es wurde gemessen, wie viele Kacheln *tatsächlich* in Zeile 0
  standen, statt wie viele *grundsätzlich* in die Fensterbreite passen
  würden. Bei wenigen Treffern wurde der "fehlende Rest bis zur vollen
  Zeile" fälschlich als Leerraum interpretiert und großzügig wegzentriert
  – wodurch effektiv nur noch eine Spalte Platz blieb.
- **Kacheln sprangen beim Ändern der Fensterbreite hin und her.** Die alte
  Messung hing indirekt von der Gesamtanzahl der Treffer ab, wodurch sich
  bei bestimmten Fensterbreiten die berechnete Spaltenzahl destabilisieren
  konnte.
- **Zusätzlich**: Suche/Filter lösen kein Resize-Event aus – die
  Zentrierung wurde daher bisher nach dem Filtern nie neu berechnet. Jetzt
  wird zusätzlich auf Modelländerungen (Suche, Filter, Sync) reagiert.

Neuer Ansatz: Es wird nur noch der **Abstand zwischen zwei nebeneinander
liegenden Kacheln** gemessen (unabhängig von der Trefferanzahl) und daraus
berechnet, wie viele Spalten die Fensterbreite grundsätzlich hergibt. Für
die Zentrierung wird dann das Minimum aus "möglichen Spalten" und
"tatsächlich vorhandenen Treffern" verwendet – wenige Treffer werden so als
eigene, kompakte Gruppe zentriert, viele Treffer füllen wie gewohnt die
volle Breite. Mit mehreren Testfällen (2/4/7/11/2000 Treffer, sowie der
Übergang zwischen 7 und 8 Spalten Schritt für Schritt) verifiziert.

## v1.23.1 – Zweiter Anlauf: Kachel-Zentrierung (diesmal entkoppelt)
Der Hänger bei der Kachel-Zentrierung in v1.21.1 kam höchstwahrscheinlich
daher, dass Windows während eines interaktiven Fenster-Resizes (Ziehen am
Rand) sehr viele Resize-Events sehr schnell hintereinander schickt – und
für jedes einzelne davon wurde synchron ein komplettes Neu-Layout von
~2000 Kacheln ausgelöst, wodurch die App nicht mehr rechtzeitig reagierte.

Neuer Ansatz: Die eigentliche (weiterhin an Qts echtem Layout *gemessene*,
nicht bloß berechnete) Zentrierung läuft jetzt über einen 150ms-Debounce-
Timer – während des Ziehens wird nur der Timer zurückgesetzt, die
eigentliche Arbeit passiert erst **einmalig**, kurz nachdem die
Fenstergröße sich nicht mehr ändert. Zusätzlich schützt ein
Wiedereintritts-Schutz gegen jede Form von Rückkopplung.

⚠️ Konnte mangels eigenem Windows-System weiterhin nicht selbst am echten
interaktiven Resize getestet werden – bitte beim ersten Test bewusst auf
Reaktionsfreudigkeit beim Ziehen am Fensterrand achten.

## v1.23.0 – Mobile-Icon, QR-Code, Backup-Fortschritt
- **Eigenes Icon auf der mobilen Seite**: Neue Endpunkte `/icon.png` und
  `/manifest.json` (Web-App-Manifest) – fügst du die Seite am Handy zum
  Startbildschirm hinzu, erscheint jetzt das CineVault-Icon statt des
  generischen Browser-Symbols. Mit Testfall verifiziert (PNG-Auslieferung,
  gültiges Manifest-JSON, korrekte Verlinkung auf der Übersichtsseite).
- **QR-Code für die mobile Adresse**: Im Einstellungen-Dialog (Tab
  "Netzwerk") wird bei aktivierter Netzwerkfreigabe automatisch ein
  QR-Code zur Adresse angezeigt – einfach am Handy scannen, statt die
  Adresse abzutippen. Neue Abhängigkeit `qrcode` (siehe
  `requirements.txt`, bitte `pip install -r requirements.txt` erneut
  ausführen); falls das Paket fehlt, wird der QR-Code einfach ausgeblendet,
  ohne die App zu beeinträchtigen.
- **"Backup läuft"-Anzeige**: Der Button "Jetzt Backup erstellen" läuft
  jetzt über einen Hintergrund-Thread (Button zeigt währenddessen "⏳ Backup
  läuft …", restliche Oberfläche bleibt bedienbar). Das automatische Backup
  beim Beenden zeigt eine kurze "Backup läuft, bitte warten …"-Anzeige,
  bevor sich das Fenster tatsächlich schließt.

## v1.22.0 – Einstellungen-Dialog mit Tabs aufgeräumt
- Der zunehmend lange Einstellungen-Dialog ist jetzt in 5 Tabs unterteilt:
  **Darstellung** (Akzentfarbe), **TMDb** (API-Key, Sprache, Sync-Anfragen),
  **Dateipfade** (FILME-Ordner, Backup), **Netzwerk** (Streaming) und
  **Diagnose** (Filter + Nachladen-Aktion). Speichern/Abbrechen und die
  Versionsnummer bleiben als gemeinsame Leiste unterhalb aller Tabs.
- Tab-Leiste im dunklen Theme gestylt, aktiver Tab farblich mit der
  gewählten Akzentfarbe unterstrichen.
- Funktional unverändert – reine Umsortierung, alle Einstellungen und
  Aktionen wie gehabt vorhanden.

## v1.21.2 – Rollback: Scrollbar-Form & Kachel-Zentrierung
Beide Versuche aus v1.21.1 haben sich beim echten Test als Fehlschlag
erwiesen und wurden komplett zurückgenommen, um Stabilität wiederherzustellen:
- **"Fusion"-Stil entfernt**: Hat die Scrollbar-Form nicht wie erhofft
  korrigiert, dafür aber die Bildlaufleiste im Genre-Dropdown komplett zum
  Verschwinden gebracht (ganze Liste wurde stattdessen angezeigt). Scrollbar
  im Hauptfenster ist damit wieder wie zuvor (farbig, aber eckig).
- **Kachel-Zentrierung komplett entfernt**: Verursachte beim Ändern der
  Fensterbreite einen kompletten Programm-Hänger (nur noch per Task-Manager
  beendbar) – mit hoher Wahrscheinlichkeit eine Rückkopplungsschleife
  zwischen Rand-Änderung, Neu-Layout und erneuter Größenänderung des
  Viewports. Zurück auf den stabilen Stand ohne Zentrierung.

Beide Punkte bleiben vorerst offen und werden nicht erneut angegangen, ohne
vorher eine deutlich vorsichtigere, tatsächlich getestete Lösung zu finden –
Stabilität hat Vorrang vor kosmetischem Feinschliff.

## v1.21.1 – Feedback aus dem ersten echten Praxistest
- **Mobile Seite**: Suche + Hauptfilter (Alle/Ungesehen/Gesehen/Rewatch)
  ergänzt, ganz ohne JavaScript (einfache GET-Links/-Formular). Der
  "Zurück"-Link auf der Detailseite behält die aktuelle Suche/Filterauswahl
  bei. Mit 8 Testfällen verifiziert (jeder Filter einzeln, Suche, Suche+
  Filter kombiniert, Zustandserhalt beim Zurücknavigieren).
- Fallback-Button "Direkter Link" auf der Detailseite entfernt, da der
  VLC-Link zuverlässig funktioniert – nur noch der "▶ In VLC abspielen"-
  Button.
- **Bugfix Scrollbar-Form**: `border-radius` griff bei Windows' nativem Stil
  nicht (bekanntes Qt-Verhalten bei manchen Widget-Eigenschaften). Fix:
  Anwendung läuft jetzt explizit im "Fusion"-Stil, der Stylesheets
  vollständig respektiert.
- **Bugfix Kachel-Zentrierung**: Die Berechnung, wie viele Spalten in die
  Fensterbreite passen, konnte sich um eine ganze Kachelbreite verschätzen
  (abhängig von Qt-Version/Stil leicht abweichende Spaltenabstände). Statt
  die nötige Breite pro Spalte selbst zu berechnen, wird jetzt direkt am
  tatsächlichen Qt-Layout gemessen, wo die letzte Kachel der ersten Zeile
  endet – dadurch unabhängig von solchen Abweichungen.

## v1.21.0 – Netzwerkfreigabe (Streaming), einstellbare Akzentfarbe, Grid-Politur
- **Neu: Netzwerkfreigabe/Streaming**. Optionaler, rein lesender lokaler
  Webserver (⚙ Einstellungen → "Netzwerkfreigabe") – im selben WLAN
  erreichbar, zeigt eine mobil-freundliche Übersicht (Cover, Titel,
  Beschreibung) und erlaubt, Filme per Klick direkt in VLC (Android)
  abzuspielen. HTTP-Range-Requests werden unterstützt, damit sich im Video
  vor-/zurückspulen lässt. Keinerlei schreibende Endpunkte – weder Löschen
  noch Bearbeiten noch Synchronisieren ist übers Netzwerk möglich. Mit
  vollständigem End-to-End-Test verifiziert (Übersicht, Detailseite, Cover,
  kompletter Stream, Range-Request mit Status 206, 404-Behandlung).
- **Einstellbare Akzentfarbe** (⚙ Einstellungen → "Darstellung"): Farbwähler,
  wird sofort angewendet (kein Neustart nötig) – betrifft Buttons,
  Scrollbar, Kachel-Hover-Effekt und "NEU"-Badge. Hover-/Klick-Varianten
  werden automatisch aus der gewählten Farbe abgeleitet.
- **Scrollbar überarbeitet**: jetzt standardmäßig farbig (gedämpfte
  Akzentfarbe statt Grau) statt erst beim Hover, zusätzlich runder gestaltet.
- **Kachel-Raster zentriert sich jetzt horizontal**: Beim Ändern der
  Fensterbreite verteilt sich übrig bleibender Platz gleichmäßig auf beide
  Seiten, statt sich einseitig rechts anzusammeln, bis eine weitere Spalte
  passt.

## v1.20.1 – Fehlende Filme bleiben in der normalen Übersicht sichtbar
- Korrektur zu v1.20.0: Filme mit fehlendem Ordner wurden aus der normalen
  Übersicht komplett ausgeblendet und waren nur über den Diagnosefilter
  auffindbar. Jetzt bleiben sie ganz normal in Alle/Ungesehen/Gesehen/
  Rewatch sichtbar (samt rotem "MISSING"-Badge) – der Diagnosefilter dient
  jetzt als praktischer Schnellfilter, um NUR die fehlenden auf einen Blick
  zu isolieren, statt als einziger Weg, sie überhaupt zu sehen.

## v1.20.0 – Fehlende Filme sichtbar machen
- Wird ein Filmordner direkt im Explorer gelöscht (statt über CineVault),
  verschwindet er beim nächsten Scan automatisch aus der normalen Übersicht
  – der Datenbankeintrag bleibt aber bewusst erhalten (kein automatisches
  Löschen), für den Fall, dass es sich nur um eine kurzzeitig nicht
  angeschlossene externe Platte handelte.
- Neuer Diagnose-Link in den Einstellungen: "Fehlende Filme anzeigen
  (Ordner nicht mehr gefunden)" – macht diese Fälle jetzt gezielt sichtbar,
  unabhängig vom sonstigen Filter (Alle/Ungesehen/Gesehen/Rewatch).
- Neues rotes "MISSING"-Badge auf der Kachel (hat Vorrang vor "NEU" und
  "REWATCH", da die dringendste Information).
- Kein Cleanup-Button – bewusst rein informativ, da so ein Fall laut
  Rückmeldung ohnehin höchst selten vorkommen sollte. Mit Testfall
  verifiziert (Datenbank behält fehlende Filme, andere Funktionen wie Sync
  ignorieren sie weiterhin korrekt).

## v1.19.0 – Backup sichert jetzt den kompletten Programmordner
- Bisher wurden nur Datenbank + Cover gesichert. Jetzt wird der **komplette
  Programmordner** mitgesichert (main.py, CineVault.pyw, der gesamte
  `mediathek`-Code, Icons, u.a.) – geht mal etwas am Programmordner selbst
  kaputt oder verloren, reicht es, den Backup-Ordner 1:1 zurückzukopieren,
  und alles läuft wieder wie zuvor.
- Programmcode wird dabei ebenfalls inkrementell kopiert (ändert sich ja nur
  bei einem Update); `__pycache__`-Ordner werden dabei übersprungen.
  Datenbank weiterhin bei jedem Durchlauf komplett über SQLites Backup-API
  gesichert, Cover weiterhin inkrementell. `pointer.json` (Zeiger auf den
  FILME-Ordner) wird jetzt ebenfalls mitgesichert. Mit Testfall verifiziert.

## v1.18.1 – Backup jetzt inkrementell
- Backup erstellt keine ZIP-Datei mehr, sondern einen Ordner
  `CineVault-Backup\`: Die Datenbank wird weiterhin bei jedem Durchlauf
  komplett (aber klein & schnell) über SQLites Backup-API gesichert, Cover
  werden jetzt **inkrementell** kopiert – nur neue/geänderte Dateien werden
  tatsächlich übertragen, bereits vorhandene unveränderte Cover werden
  übersprungen. Macht jedes Backup nach dem ersten Mal deutlich schneller,
  gerade bei "automatisch bei jedem Beenden". Mit Testfall verifiziert
  (0 kopierte Dateien bei unverändertem Bestand, nur die tatsächlich neuen
  bei einem neu hinzugekommenen Film).
- Cover sind statische, nach dem Schreiben nie mehr veränderte Dateien –
  ein Ordner mit Einzeldateien ist dafür (anders als bei der aktiv
  geöffneten Datenbank) auch für Cloud-Sync-Ordner völlig unproblematisch.

## v1.18.0 – Backup-Funktion, FILME-Ordner änderbar
- **Backup**: Neuer Bereich in den Einstellungen – Zielordner auswählen,
  Button "Jetzt Backup erstellen" und Haken "Automatisch bei jedem Beenden
  sichern". Erstellt/überschreibt eine einzige Datei `CineVault-Backup.zip`
  (Datenbank + Cover + Einstellungen). Die Datenbank wird dabei NICHT
  einfach kopiert, sondern über SQLites eigene Backup-API dupliziert – das
  liefert auch bei laufender App einen garantiert konsistenten Snapshot.
  Bewusst eine einzelne ZIP-Datei statt vieler Einzeldateien: deutlich
  freundlicher für Cloud-Sync-Ordner wie Google Drive/OneDrive. Mit Testfall
  verifiziert.
- **FILME-Ordner ändern**: Neuer Button in den Einstellungen ("Bibliothek"),
  falls sich der Speicherort deiner Filme mal ändert (z. B. neue Festplatte).
  Datenbank, Cover und Einstellungen bleiben davon komplett unberührt, da
  sie ja im Programmordner liegen, nicht im FILME-Ordner. Erfordert einen
  Neustart von CineVault.

## v1.17.3 – Trailer-Link-Feld verbreitert
- Das Trailer-Link-Eingabefeld im Bearbeiten-Modus füllt jetzt die volle
  Zeilenbreite (wie das Beschreibungsfeld darüber), statt sich sein Drittel
  mit einem ungenutzten Leerraum daneben zu teilen.

## v1.17.2 – Detail-Fenster: letzter Feinschliff
- "Löschen" wird im Bearbeiten-Modus jetzt ausgeblendet – dadurch bleibt die
  untere Buttonzeile links immer bei zwei Buttons (Bearbeiten+Löschen bzw.
  Speichern+Abbrechen), keine Breitenänderung mehr beim Umschalten.
- Trailer-Link-Eingabefeld (Bearbeiten-Modus) sitzt jetzt in derselben Zeile
  wie Abspielen/Trailer statt in einer eigenen Zeile darunter.

## v1.17.1 – Detail-Fenster nachjustiert
- Trailer-Button neben "Abspielen" gezogen (statt eigener Zeile darunter).
- "Bearbeiten" (morpht zu "Speichern"/"Abbrechen") und "Löschen" jetzt
  zusammen in einer kompakten Zeile direkt unter "Ordner öffnen" in der
  linken Spalte – vorher führte das Übereinanderstapeln mehrerer Zeilen im
  Bearbeiten-Modus zu einem unschönen Layout oberhalb des Covers.

## v1.17.0 – Optischer Feinschliff
- **Kopfleiste**: Suchfeld übernimmt jetzt die dynamisch wachsende Rolle
  (wie der Status-Text in Zeile 2) statt einer festen Maximalbreite –
  Sortierung/Genre-Filter/Alle/Ungesehen/Gesehen/Rewatch bleiben dadurch bei
  jeder Fensterbreite konsequent rechtsbündig zusammen, statt teils schon
  rechts zu kleben und teils mitzuwandern.
- **Detail-Fenster überarbeitet**:
  - Tippfehler "Cover aendern" → "Cover ändern".
  - Linke Spalte neu geordnet: Bearbeiten (morpht zu Speichern/Abbrechen)
    steht jetzt direkt über Ordner öffnen / Film löschen, die beide unten
    zusammenstehen.
  - "Abspielen" und "Trailer" getauscht – Abspielen ist jetzt die oberste,
    dominante Aktion direkt unter der Beschreibung.
  - Trailer-Button deutlich gekürzt: "▶ Trailer (DE)" / "▶ Trailer (EN)"
    statt "… auf YouTube ansehen" (Hinweis auf fehlende deutsche Fassung
    jetzt als Tooltip statt im Text).
  - Gesehen/Ungesehen und Rewatch jetzt gemeinsam in einer eigenen Zeile
    unterhalb des Trailers, getrennt von der Kernbedienung.

## v1.16.0 – "Genres nachladen" zu "Zusatzinfos nachladen" erweitert
- Die Nachlade-Funktion aus v1.15.0 ergänzt jetzt nicht mehr nur fehlendes
  Genre, sondern auch fehlende Besetzung und Trailer – alles kommt ohnehin
  aus derselben TMDb-Abfrage, kostet also keine zusätzlichen Anfragen.
  Bereits vorhandene Werte (auch von Hand eingetragene) werden dabei nie
  überschrieben, nur echte Lücken aufgefüllt. Mit Testfall verifiziert.
- Umbenannt: "Genres für bereits synchronisierte Filme nachladen" →
  "Fehlende Besetzung/Genre/Trailer nachladen".
- Im Einstellungen-Dialog jetzt in einen eigenen Bereich "Nachladen"
  ausgelagert, getrennt von den reinen Diagnose-**Filtern** darüber – das
  hier ist schließlich eine echte Aktion (löst Netzwerkanfragen aus und
  ändert Daten), kein reiner Ansichtsfilter.

## v1.15.0 – Sicheres Nachladen statt riskantem Voll-Resync
- **Grundsätzliches Problem behoben**: Die "Genres nachladen"-Funktion
  (⚙ Einstellungen) setzte betroffene Filme bisher auf "pending" zurück und
  ließ sie über die normale Synchronisierung (per Titelsuche) komplett neu
  abgleichen. Das hätte theoretisch eine bereits per Mehrdeutigkeits-Dropdown
  getroffene Auswahl wieder verwerfen und Titel/Beschreibung/Cover
  überschreiben können.
- **Jetzt**: Genres werden direkt über die bereits bekannte TMDb-ID
  nachgeladen und ausschließlich das Genre-Feld ergänzt – Titel,
  Beschreibung, Cover, TMDb-Zuordnung und Sync-Status bleiben garantiert
  unangetastet. Mit Testfall verifiziert.
- Dient als Vorlage für alle künftigen Fälle dieser Art: Wird CineVault um
  ein neues Datenfeld erweitert, das bei bereits zugeordneten Filmen
  nachgezogen werden muss, geschieht das ab sofort grundsätzlich per
  direkter ID-Abfrage statt per vollständigem Re-Sync – bereits manuell
  aufgelöste oder bearbeitete Filme bleiben davon unberührt.

## v1.14.1 – Englisch-Fallback für Beschreibungsvorschau
- Manche Filme haben bei TMDb schlicht keine deutsche Beschreibung
  hinterlegt (v. a. ältere/weniger populäre Titel). Die Vorschau im
  Mehrdeutigkeits-Dropdown lädt für betroffene Kandidaten jetzt automatisch
  die englische Beschreibung nach, mit kurzem Hinweis, dass keine deutsche
  verfügbar war – statt einfach leer zu bleiben.

## v1.14.0 – Trefferanzahl bei jedem Filter, Sortier-Bugfix
- **Trefferanzahl immer sichtbar**: Der Status-Text zeigt jetzt bei jedem
  aktiven Filter (Ungesehen/Gesehen/Rewatch, Genre, Suche, Diagnosefilter)
  die tatsächlich angezeigte Anzahl an ("X von Y Filmen angezeigt").
- **Bugfix Sortierung**: Ein Wechsel der Sortierung (Titel/Älteste zuerst)
  wurde von Qt manchmal ignoriert, weil sich Spalte/Richtung des
  `sort()`-Aufrufs technisch nicht geändert hatten – wirksam wurde die neue
  Sortierung dadurch erst beim nächsten (unabhängigen) Filterwechsel. Jetzt
  wird bei jedem Sortier-Wechsel eine echte Neusortierung erzwungen.
- Die Beschreibungsvorschau im Mehrdeutigkeits-Dropdown zeigt weiterhin nur
  das, was in den gespeicherten Kandidatendaten steht – bei Filmen, die
  schon vor v1.13.0 als "mehrdeutig" markiert wurden, fehlt dort schlicht
  noch das Beschreibungsfeld. Einmal komplett neu einlesen/synchronisieren
  behebt das (kein Software-Fix nötig).

## v1.13.2 – Sortierung zurückgestellt, Beschreibungsvorschau deutlicher
- Sortierung "Titel (A–Z)" / Erstelldatum wieder auf das ursprüngliche,
  einfachere Verfahren zurückgestellt (war doch schon korrekt). Die
  Erstelldatum-Sortierung zeigt jetzt bewusst die **ältesten** Filme zuerst,
  Dropdown entsprechend in "Älteste zuerst" umbenannt.
- Beschreibungsvorschau im Mehrdeutigkeits-Dropdown deutlicher gestaltet:
  eigener abgesetzter Kasten mit fetter "Beschreibung:"-Überschrift statt
  nur dezentem Fließtext daneben.

## v1.13.1 – Bugfix: Sortierung "Zuletzt hinzugefügt"
- Reihenfolge war vertauscht (älteste statt neueste zuerst). Die
  Sortierrichtung wird jetzt direkt in der Vergleichslogik festgelegt statt
  über Qt's Sortier-Richtungs-Flag – neueste Filme stehen wieder ganz oben.

## v1.13.0 – Cover & Beschreibung in der Mehrdeutigkeits-Auswahl
- Das Auswahl-Dropdown bei mehrdeutigen Sync-Treffern zeigt jetzt zusätzlich
  zu Titel + Jahr auch **Cover und Beschreibung** des gerade ausgewählten
  Kandidaten an (lädt automatisch im Hintergrund nach, während man
  durchklickt) – macht die Unterscheidung z. B. bei Remakes deutlich
  einfacher als nur anhand von Titel und Jahreszahl.

## v1.12.1 – Diagnosefilter für mehrdeutige Filme
- Neuer Diagnose-Link in den Einstellungen: "Mehrdeutige Filme anzeigen" –
  filtert die Übersicht direkt auf alle Filme mit Status "Mehrdeutig", zum
  bequemen Durchklicken und Auflösen per Dropdown im Detail-Fenster.

## v1.12.0 – Mehrdeutigkeit direkt auflösen, Cover in den Programmordner
- **Mehrdeutige TMDb-Treffer direkt auswählbar**: Statt nur eines Hinweises
  gibt's im Detail-Fenster jetzt ein Dropdown mit allen gefundenen
  gleichnamigen Filmen (inkl. Jahr, z. B. "Ben-Hur (2016)" / "Ben-Hur
  (1959)") plus "Übernehmen"-Button – kein manuelles Suchen/Kopieren des
  TMDb-Links mehr nötig. Nach der Auswahl verschwinden Dropdown und die
  dahinterliegenden Kandidatendaten automatisch wieder (auch bei
  Bearbeitung der Filminfos von Hand).
- **Cover/MEDIA-Ordner umgezogen**: Liegt jetzt zusammen mit der Datenbank
  im `Mediathek`-Unterordner im Programmordner statt im `FILME`-Ordner –
  konsequent zu Ende gedacht, da die Datenbank ohnehin schon dort liegt und
  bei einem Update erhalten bleibt. Bestehende Cover aus `FILME\MEDIA`
  werden beim ersten Start automatisch migriert.

## v1.11.0 – Aus der Praxis: Titel, Treffergenauigkeit, Detail-Fenster-Politur
- **Kachel-Titel überarbeitet**: Zeigt jetzt den **rohen Ordnernamen** statt
  des TMDb-Titels an, echt zweizeilig mit Umbruch an Wortgrenzen (statt
  einzeiliger Kürzung). Das entspricht 1:1 der eigenen Dateibenennung (z. B.
  bei mehrteiligen Reihen mit "Teil 1/2/3") und macht falsch zugeordnete
  TMDb-Daten auf den ersten Blick erkennbar. Im Detail-Fenster steht
  weiterhin der TMDb-Titel; ein Tooltip auf der Kachel zeigt beide.
- **Treffergenauigkeit bei Remakes verbessert**: Ist im Dateinamen kein Jahr
  angegeben und liefert TMDb mehrere gleichnamige Filme mit unterschiedlichem
  Erscheinungsjahr (z. B. Ben-Hur 1959 vs. 2016), wird das jetzt als
  **mehrdeutig** erkannt, statt automatisch (und ggf. falsch) den
  populäreren/älteren zu wählen. Solche Filme landen im Status "Mehrdeutig"
  und lassen sich im Detail-Fenster gezielt per "TMDb-Link manuell zuweisen"
  auflösen. Zählt auch zum Diagnosefilter "nicht synchronisiert".
- **Detail-Fenster aufgeräumt**:
  - "Rewatch"-Button in eine eigene Zeile verschoben, damit sein Ein-/
    Ausblenden nicht mehr die Fensterbreite verändert; umbenannt in "Für
    Rewatch vormerken" (einheitlich mit dem Filter-Button).
  - "Cover ändern" und "TMDb-Link manuell zuweisen" werden nur noch im
    Bearbeiten-Modus angezeigt.
  - Im Bearbeiten-Modus: "Abspielen"-Button ausgeblendet; der
    Trailer-Button wird durch ein editierbares Textfeld mit dem YouTube-Link
    ersetzt (nur wenn wirklich ein Link vorliegt, keine reine Suchanfrage).
  - Neuer Button "📂 Ordner öffnen" – öffnet den Filmordner im Explorer, z. B.
    um den Dateinamen direkt zu korrigieren.
  - Rewatch-Badge auf der Kachel einheitlich in "REWATCH" umbenannt (vorher
    "WATCH"); Filter-Button "Rewatch" ohne Sonder-Symbol, passend zu den
    übrigen Filter-Buttons.
- **Taskleisten-Icon, zweiter Anlauf**: Zusätzlich zum Setzen der
  AppUserModelID wird das Icon jetzt direkt per Windows-API (WM_SETICON)
  gesetzt, ein bekannter, zuverlässiger Workaround für genau dieses
  Python/Windows-Verhalten. Ließ sich leider nicht an einem echten
  Windows-System gegentesten.

## v1.10.0 – Löschen, Rewatch, manuelle TMDb-Zuweisung, Layout- & Bugfixes
- **Film löschen**: Neuer Button (Detail-Fenster) bzw. Kontextmenü-Eintrag,
  mit Sicherheitsabfrage. Der Ordner wird in den normalen Windows-Papierkorb
  verschoben (nicht endgültig gelöscht) und kann von dort jederzeit
  wiederhergestellt werden.
- **Manuelle TMDb-Zuweisung**: Im Detail-Fenster lässt sich jetzt gezielt ein
  TMDb-Link oder eine TMDb-ID eintragen, falls die automatische Suche wegen
  abweichender Schreibweise im Ordnernamen nichts gefunden hat – ohne
  Ähnlichkeitsprüfung, der angegebene Film wird direkt übernommen.
- **Rewatch-Funktion**: Für bereits gesehene Filme gibt es jetzt "🔁 Zum
  Nochmal-Ansehen vormerken" (Detail-Fenster oder Kontextmenü), inkl. eigenem
  Badge auf der Kachel und eigenem Filter-Button in der Kopfleiste.
- **Kopfleiste neu angeordnet** (zweizeilig): Suche/Sortierung/Genre/Filter
  in einer Zeile, Status-Text und Aktions-Buttons in einer zweiten. Der
  variabel lange Status-Text konnte zuvor ungewollt die Fensterbreite
  verschieben – das ist jetzt behoben.
- **Sortierung bereinigt**: "Zuletzt geändert" entfernt; "Zuletzt
  hinzugefügt" verwendet jetzt das tatsächliche Windows-Erstelldatum des
  Filmordners statt eines eigenen CineVault-internen Zeitstempels.
- **Bugfix Taskleisten-Icon**: Windows zeigte im ersten Programmstart einer
  Windows-Sitzung teils noch das generische Python-Symbol statt des
  CineVault-Icons (erst ab dem zweiten Start korrekt). Behoben durch
  explizites Setzen einer eigenen Windows-"AppUserModelID".
- Suchfeld hat jetzt einen "✕"-Button zum schnellen Leeren.
- Kontrast in Dropdown-Listen korrigiert (ausgewählter Eintrag: helle statt
  schwarzer Schrift auf blauem Hintergrund).

## v1.9.1 – Genres nachträglich für bereits synchronisierte Filme
- Neuer Diagnose-Link in den Einstellungen: "Genres für bereits
  synchronisierte Filme nachladen". Merkt gezielt nur Filme vor, die zwar
  erfolgreich synchronisiert sind, aber (weil mit einer älteren Version
  abgeglichen) noch kein Genre haben, und bietet an, direkt dafür zu
  synchronisieren – ohne Datenverlust, ohne alles neu abgleichen zu müssen.

## v1.9.0 – Genre, freie Bearbeitung, feinere Diagnose, eigenes App-Icon
- Genre wird jetzt zusätzlich zu Titel/Beschreibung/Besetzung/Trailer von
  TMDb mitgeladen und im Detail-Fenster angezeigt.
- Neuer Genre-Filter in der Kopfleiste (Dropdown, füllt sich automatisch mit
  allen tatsächlich vorhandenen Genres).
- Detail-Fenster: Beschreibung, Besetzung, Genre und Titel lassen sich jetzt
  direkt von Hand bearbeiten und speichern (Button "✏ Bearbeiten").
- Vollständigkeits-Punkt auf den Kacheln überarbeitet: **rot** = weder Cover
  noch Beschreibung vorhanden, **gelb** = nur eines von beiden vorhanden,
  **kein Punkt** = beides vorhanden – unabhängig davon, ob die Infos
  automatisch per TMDb oder von Hand eingetragen wurden.
- Diagnose-Bereich in den Einstellungen um zwei weitere versteckte Filter
  erweitert: "Filme ohne Beschreibung anzeigen" und "Filme ohne Cover
  anzeigen" (zusätzlich zum bestehenden "nicht synchronisiert").
- Eigenes App-Icon (violette Filmklappe) ergänzt – erscheint jetzt auch in
  der Windows-Taskleiste statt eines generischen Python-Symbols.

## v1.8.0 – UI-Feinschliff
- Suchfeld verbreitert (Text wurde vorher abgeschnitten).
- Scrollleiste breiter und kontrastreicher gestaltet.
- Neue Sortier-Auswahl in der Kopfleiste: Titel (A–Z), Zuletzt geändert
  (Ordner-Änderungsdatum wie im Explorer), Zuletzt hinzugefügt.
- Mausrad-Scrollen sanft animiert/abgefedert statt abrupter Sprünge pro
  Wheel-Tick.
- Versionsnummer eingeführt (diese Datei + Anzeige in den Einstellungen).

## v1.7.0 – Umbenennung zu CineVault
- Projekt von "Filmmediathek" in "CineVault" umbenannt (Fenstertitel,
  Meldungen, README, Build-Skripte).
- Neue Startdatei `CineVault.pyw` für konsolenlosen Start per Doppelklick
  (nutzt `pythonw.exe` statt `python.exe`).

## v1.6.0 – Bugfixes & versteckter Diagnosefilter
- Fehler behoben: Cover wurden nach der letzten Performance-Optimierung nur
  noch klein oben links statt kachelfüllend angezeigt (fehlerhafte
  HiDPI-Vorskalierung entfernt, durch robustes "object-fit: cover"-Zuschneiden
  ersetzt).
- Neuer, bewusst unauffälliger Diagnosefilter in den Einstellungen: "Nicht
  synchronisierte Filme in der Übersicht anzeigen".

## v1.5.1 – Bugfix: Programmstart
- Fehlerhafter Import (`QAbstractItemView` aus falschem Qt-Modul) behoben,
  der das Programm sofort beim Start abstürzen ließ.
- Absicherung ergänzt: Fehler beim Start landen jetzt in `crash.log` neben
  der .exe/dem Skript, inkl. Fehlermeldung im UI statt stillem Absturz.

## v1.5.0 – Optik & Performance
- Sanft animierter Hover-Effekt auf den Film-Kacheln (Kachel wächst leicht
  auf, bekommt einen dezenten farbigen Schein).
- Scroll-Performance verbessert: pixelweises statt zeilenweises Scrollen,
  Cover werden nur einmal statt bei jedem Scroll-Frame neu skaliert.

## v1.4.0 – Verlässlichere Metadaten-Zuordnung
- Strengere Titel-Ähnlichkeitsprüfung gegen TMDb-Suchergebnisse eingebaut,
  damit kurze/mehrdeutige Ordnernamen (z. B. "Haus") nicht mehr fälschlich
  einem völlig anderen Film zugeordnet werden. Im Zweifel lieber "nicht
  gefunden" als ein falscher Treffer.

## v1.3.0 – Deutschsprachige Trailer bevorzugt
- Trailer-Suche versucht gezielt zuerst deutsche Sprachvarianten bei TMDb,
  fällt nur bei Bedarf auf Englisch zurück; Detail-Fenster zeigt an, welche
  Sprache der gefundene Trailer hat.

## v1.2.0 – Detailansicht, Besetzung & Trailer
- Klick auf eine Kachel öffnet jetzt das Detail-Fenster statt den Film
  direkt zu starten (Abspielen weiterhin per Button dort oder per
  Rechtsklick-Kontextmenü).
- Hauptbesetzung wird zusätzlich zur Beschreibung angezeigt.
- YouTube-Trailer-Link im Detail-Fenster (öffnet nur den Browser, kein
  Download).

## v1.1.0 – Speicherort der Programmdaten
- Datenbank und Einstellungen liegen jetzt im Programmordner selbst (neben
  der .exe/dem Skript) statt im `FILME`-Ordner, damit z. B. eine Installation
  unter `C:\Programme\...` sauber getrennt bleibt. Nur der `MEDIA`-Ordner
  (heruntergeladene Cover) bleibt weiterhin in `FILME`.
- Automatische Migration eventuell schon vorhandener Daten aus der alten
  Struktur.

## v1.0.0 – Erste Version
- Kachelansicht mit Cover, Titel, Beschreibung.
- Automatische Metadaten-Synchronisierung über TMDb ("Jetzt synchronisieren"),
  bereits aufbereitete Filme werden übersprungen.
- Manuelles Ersetzen von Covern (Datei, URL, Google-Bildersuche).
- Ungesehen/gesehen-Verwaltung durch tatsächliches Verschieben der
  Filmordner zwischen `NEU` und `ARCHIV`.
- Wiedergabe über den Windows-Standardplayer.
- Schnelle inkrementelle Ordner-Indexierung (nur geänderte Ordner werden neu
  eingelesen).
- Build-Pipeline über GitHub Actions für eine eigenständige Windows-.exe.
