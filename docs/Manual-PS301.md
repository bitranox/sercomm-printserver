# Sercom (SerComm) PS301 Printserver - Zusammenfassung

Für den PS301 selbst ist online kein Handbuch auffindbar. Das Gerät gehört aber zu einer
SerComm-Firmwarefamilie, die unter mehreren Marken verkauft wurde (TRENDnet "Netprint",
Perle "IOPRINT+", Netgear PS10x/PS11x). Deren Handbücher beschreiben dieselbe
FTP-Schnittstelle, dieselben CONFIG-Schlüssel und denselben Telnet-Monitor und passen daher.
Die Zuordnung beruht auf identischen Dateinamen, Schlüsseln und Meldungen; ein offizielles
Dokument, das PS301 und diese Modelle gleichsetzt, wurde nicht gefunden.

## Baugleiche Modelle

"Belegt durch" sagt, woran die Zugehörigkeit festgemacht ist: FW = Strings im
Firmware-Image (Telnet-Banner, `PS>`, "220 Print Server Ready.", BOX_NAME/L1_PROUT,
"SerComm SNMP agent."), Doku = Handbuch beschreibt FTP-Dateien, CONFIG-Format, SC-Namen.

| Modell                  | Anschlüsse    | Netz                 | Log. Drucker | Belegt durch | Bemerkung                                      |
|-------------------------|---------------|----------------------|--------------|--------------|------------------------------------------------|
| Sercom PS301 (dieses)   | 2 par + 1 ser | 10BaseT              | L1..L8       | Gerät selbst | FW 6022                                        |
| Perle IOPRINT+          | 2 par + 1 ser | 10BaseT, 10Base2     | L1..L8       | Doku         | Perle-FW 2P1S 6017                             |
| TRENDnet TE-310         | 2 par + 1 ser | 10BaseT, 10Base2     | L1..L8       | Doku         | Utility-Disk gemeinsam mit TE-360              |
| Netgear PS110           | 2 par         | 10/100               | L1..L8       | FW + Doku    | FW 6017/6025/6026/6028 vorhanden               |
| Netgear PS113           | 3 par         | 10/100               | L1..L8       | Doku         |                                                |
| Linksys EPSX3           | 3 par         | 10/100               | L1..L8       | FW           | FW 6015-6018 vorhanden                         |
| TRENDnet TEW-P1U1P      | 1 par + 1 USB | 10/100, WLAN 802.11b | L1..L6       | FW           | FW 6035 vorhanden, zusätzlich WLAN-Schlüssel   |
| TRENDnet TE-360         | 1 par         | 10BaseT              | L1..L3       | Doku         |                                                |
| TRENDnet TE100-P1P (v1) | 1 par         | 10/100               | L1..L3       | FW + Doku    | FW 6034 vorhanden; v2/v3 sind andere Firmware  |
| Linksys PPSX1 (v1, v2)  | 1 par         | 10/100               | L1..L3       | FW + Doku    | FW 6013-6017 vorhanden                         |
| Perle IOPRINT+ Jr       | 1 par         | 10BaseT, 10Base2     | L1..L3       | Doku         |                                                |
| Netgear PS104 / PS105   | 1 par         | 10, mit 4-Port-Hub   | L1..L3       | Doku         | PS105 zusätzlich BNC; Default Name "PS..."     |
| Netgear PS101           | 1 par         | v1 10, v2 10/100 (?) | L1..L3 (?)   | nur vermutet | Freigabenamen "PSxxxxxx_P1", Weboberfläche     |
| TRENDnet TE-350         | 1 par         | 10BaseT, 10Base2     | L1..L3       | Doku         | nur IPX: kein TCP/IP, also kein FTP/LPD/Telnet |
| TRENDnet TE100-P1U (v1) | 1 USB         | 10/100               | ?            | nur vermutet | teilt die P1P-Handbücher                       |

Faustregel: 1-Port-Modelle haben L1..L3, Mehrport-Modelle L1..L8. Die TEW-P1U1P mit L1..L6
zeigt aber, dass die Anzahl an der Firmware hängt. Eine Library sollte sie aus CONFIG lesen
und nicht fest annehmen. Die Namen L1..Ln sind fest.

Nicht zu dieser Familie gehören (andere Firmware, "PS-Admin"/"EtherPort Admin", Telnet-Menü,
Queues "lp1"): TRENDnet TE100-PS1/PS3/PS1U/TEW-PS*, TE100-P1P/P1U v2/v3, TE100-P21,
TE100-P11, TEW-P1PG, TEW-P21G, TE100-P2U1P sowie wahrscheinlich Longshine LCS-PS1xx.
SerComm-eigene "PrintMate"-Dokumente wurden außer dem Datenblatt des Fast PrintMate 1P nicht
gefunden.

## Unterschiede, die für eine Client-Library zählen

Aus den CONFIG-Tabellen der Firmware-Images und den Unix-Handbüchern:

- Anzahl logischer Drucker: siehe oben, aus CONFIG ableiten.
- RAW/DSI-Ports: Alle Handbücher und Perle-KB q163 nennen fest 4010/4020/4030 (nur L1..L3);
  in den untersuchten Firmware-Images taucht 9100 nicht auf. Dieses Gerät (FW 6022) hat
  beide Reihen offen, 9100-9102 und 4010/4020/4030 (gemessen 2026-10-24). Bei anderer
  Firmware kann eine Reihe fehlen.
- Schlüssel nur bei Mehrport-Modellen: LPT2MODE/LPT3MODE, NR_NAME2.., AP_TYPE2..,
  AP_PCOMM2.. (beim EPSX3 trägt Port 3 die Endung 4).
- Schlüssel nur bei manchen Firmware-Ständen:
  - P1_NAME/P2_NAME (0040-0042) und Ln_NAME: nur PS110 v3 6028.
  - P1_STROBE, SMBDESC: nur TE100-P1P 6034 und TEW-P1U1P 6035.
  - serielle Schlüssel (BAUDRATE..HANDSHAK): PPSX1, EPSX3, PS110 und dieses Gerät, nicht in
    den TRENDnet-603x-Images.
  - MAIL_*: fehlen bei PS110 6028.
  - WINS_IP: in allen Images, fehlt in der Handbuch-Tabelle.
  - SSID/WEP: nur TEW-P1U1P.
  - Firmware über 6100 nutzt laut Unix-Handbuch größere Feldlängen.
- Weboberfläche: laut TRENDnet nur bei 100BaseT-Modellen, Perle-10-Mbit ohne HTTP. Die
  10/100-Images von PPSX1 und EPSX3 enthalten HTML-Seiten; PS101 (10 Mbit) hat trotzdem
  eine. Dieses Gerät hat keine.
- Telnet und FTP sind in allen untersuchten Images gleich: "Welcome to Print Server",
  `PS>`, Help/Monitor/Exit, Monitor-Format "(Pn)STATE / TYPE / PRINTER STATUS /
  BYTES SERVICED / OCCUPIED BY"; FTP-Banner "220 Print Server Ready.", SYST/HELP liefert
  "215 Print Server FW nnnn". Damit lässt sich die Firmware-Version ohne Login abfragen.
- Werkseinstellungen (Unix-Handbuch): IP 0.0.0.0, Ln_PROUT P1, CHGLF No, TCP_INT 2,
  TCP_CNT 254, SNMP-Community "public".

## Dieses Gerät (ausgelesen am 2026-10-23)

Quelle: `device-dump/PSINF.txt`, `device-dump/CONFIG.txt`, `device-dump/telnet-monitor.txt`.

IP-Adressen, MAC, Gerätenamen und Hardware-ID sind in diesem Dokument und in `device-dump/`
durch Platzhalter ersetzt (192.0.2.0/24 nach RFC 5737, `PS_EXAMPLE`, `SC123456`). Die echten
Werte des Testgeräts stehen lokal in `test-device.json` im Projektverzeichnis (gitignored,
Vorlage `test-device.example.json`).

| Eigenschaft     | Wert                                           |
|-----------------|------------------------------------------------|
| IP / Maske / GW | 192.0.2.52 / 255.255.255.0 / .1                |
| DHCP            | aus (statische IP)                             |
| MAC             | 00:c0:02:12:34:56 (OUI SerComm)                |
| Default Name    | SC123456 (SC + letzte 6 MAC-Stellen)           |
| Server Name     | PS_EXAMPLE                                     |
| Hardware ID     | 024010XXXX                                     |
| Firmware        | 6022                                           |
| Protokolle      | nur TCP/IP aktiv (IPX, AppleTalk, NetBEUI aus) |
| Weboberfläche   | keine (Port 80 zu)                             |

Anschlüsse: P1 und P2 parallel, SP seriell (9600 8N1, Handshake BOTH).

| Queue | Anschluss | Pre/Post-String | LF->CRLF |
|-------|-----------|-----------------|----------|
| L1    | P1        | leer            | nein     |
| L2    | P2        | leer            | nein     |
| L3    | SP        | leer            | nein     |
| L4    | P1        | leer            | nein     |
| L5    | P2        | leer            | nein     |
| L6    | SP        | leer            | nein     |
| L7    | P1        | leer            | nein     |
| L8    | P2        | leer            | nein     |

Die LPD-Queue `lp` landet ebenfalls auf P1.

Offene Ports: 21 (FTP), 23 (Telnet), 69/udp (TFTP), 515 (LPD), 9100-9102 und
4010/4020/4030 (RAW / Direct Socket). Geschlossen: 80, 139, 443, 631, 9103.

Die RAW-Ports gehören zu den logischen Druckern, nicht zu den Anschlüssen: 9100 und 4010
-> L1, 9101 und 4020 -> L2, 9102 und 4030 -> L3. Die Daten gehen an den Anschluss, auf
den der logische Drucker zeigt (`Ln_PROUT`). L4..L8 haben keinen RAW-Port. Gemessen
2026-10-24 ohne Drucker, über den Anschluss, der danach auf "Direct Socket" stand: ab
Werk landeten 9100/4010 auf P1, 9101/4020 auf P2 und 9102/4030 auf SP; mit
`L1_PROUT=P2` landeten 9100 und 4010 auf P2.

## Verwaltung

### Telnet (Port 23)

Kein Passwort, Prompt `PS>`. Nur drei Befehle: `Help`, `Monitor` (Status je Anschluss),
`Exit`. Über Telnet lässt sich nichts konfigurieren.

### FTP (Port 21) - die eigentliche Konfigurationsschnittstelle

Nur Kommandozeilen-FTP, nur eine Verbindung gleichzeitig, nur aktiver Modus (PASV wird
mit `500 Invalid command` abgelehnt). Login laut Handbuch mit dem Gerätenamen
(`PS_EXAMPLE`, sonst der Default Name `SC123456`) und leerem Passwort, falls keines
gesetzt ist. Beobachtet: `LIST` und `RETR CONFIG` funktionierten hier auch ganz ohne Login.

Virtuelle Dateien:

| Datei     | Wirkung von get                         | put              |
|-----------|-----------------------------------------|------------------|
| CONFIG    | Konfiguration herunterladen             | Konfig schreiben |
| PSINF     | Geräteinfo herunterladen                | -                |
| RESET     | Neustart (beendet die FTP-Verbindung)   | -                |
| DEFAULTC  | WERKSEINSTELLUNGEN (IP danach 0.0.0.0!) | -                |
| PASSRESET | Passwort löschen                        | -                |
| SETIP     | aktuelle IP als statisch speichern      | -                |

Achtung: `get` auf RESET, DEFAULTC, PASSRESET oder SETIP liest nichts, sondern löst die
Aktion aus. Nach `DEFAULTC` hat das Gerät die IP 0.0.0.0 und sucht per DHCP, BOOTP, RARP.

Weitere Befehle:

- `put PASSWORD`: Datei mit neuem Passwort (max. 19 Byte) hochladen.
- `put <datei> L<n>`: Datei auf logischen Drucker n drucken (nur zum Testen, kein Spooling).

Konfiguration ändern:

```
ftp 192.0.2.52        # Name: PS_EXAMPLE, Passwort: leer
ftp> get CONFIG
  (CONFIG lokal bearbeiten)
ftp> put CONFIG
ftp> get RESET
```

### TFTP

Laut TE-310-Handbuch funktionieren die Aktionsdateien auch per TFTP, und zwar ohne Login:
`tftp <ip> GET RESET` (Neustart) und `tftp <ip> GET DEFAULTC` (Werkseinstellungen).

Gemessen auf diesem Gerät (FW 6022): `CONFIG` und `PSINF` lassen sich per TFTP ohne Login
lesen (identisch mit FTP). `GET PASSRESET` per TFTP lehnt es mit TFTP-Fehler 4
"Read(Get) Command Not Supportted" ab. `GET RESET` per TFTP startet das Gerät neu: es antwortet mit einem leeren DATA-Block,
und die SNMP-Uptime fällt nach rund 6 s auf 0 (gemessen 2026-10-24, sechsmal).
`DEFAULTC` per TFTP ist nicht geprüft.

### Werkseinstellungen, wenn IP oder Passwort unbekannt sind

Für Firmware über 5000 (dieses Gerät: 6022), nach TE-310-Handbuch und Perle-KB q=171:

1. Auf einem Rechner im selben Netz der MAC eine freie IP zuweisen:
   `arp -s <ip> 00:c0:02:xx:yy:zz` (xx:yy:zz = die sechs Stellen hinter "SC" im Default
   Name, hier `00:c0:02:12:34:56`).
2. `tftp <ip> GET DEFAULTC`
3. Etwa 5 Sekunden warten, bis die rote LED blinkt. Danach ist alles zurückgesetzt, auch die
   IP (0.0.0.0, das Gerät fragt dann DHCP, BOOTP, RARP).

Mit diesem Werkzeug: `sercomm-printserver arp reach | assign-ip | factory-reset --mac MAC --ip
FREIE_IP` (als root bzw. Administrator). Es setzt den statischen ARP-Eintrag selbst, spricht das
Gerät per FTP statt TFTP an (TFTP lehnt `PASSRESET` ab und meldet nichts zurück, siehe oben) und entfernt den Eintrag
danach wieder. Gemessen: `arp reach` erreicht das Gerät über eine geliehene freie Adresse im
eigenen Subnetz und liest PSINF; danach steht für die Adresse kein statischer Eintrag mehr.

Weitere Wege: `get DEFAULTC` per FTP, BiAdmin "InitDevice > Restore Factory Default",
PSCONFIG "Restore Default Configuration". Das TE-310-Handbuch erwähnt einen Reset-Taster;
Perle dokumentiert für den IOPRINT+ keinen. Ob der PS301 einen hat, ist nicht geprüft.

Standardpasswort: keines. `put PASSWORD` setzt eines, `get PASSRESET` löscht es - per FTP
auch ganz ohne Login (gemessen, FW 6022). Ein Passwort schützt das Gerät also nicht.

Die Datei `PASSWORD` muss mit einem Zeilenende (CR, LF) oder NUL enden. Ohne Abschluss liest
das Gerät über die gesendeten Bytes hinaus und speichert ein unbekanntes Passwort; danach
hilft nur `get PASSRESET` (gemessen).

### Windows- und DOS-Werkzeuge (historisch)

- BiAdmin: Windows 95/98/NT, Konfiguration und Firmware-Update aus .BIN-Dateien
  (bei Netgear "FirstGear Print Server Administration"). In
  `oem-manuals/trendnet/TE310360_utility.zip` unter `WIN9XNT/`.
- WPCONFIG (Windows 3.1), PSCONFIG und QUICKSET (DOS, über IPX).
- WebAdmin: lief auf einem NT-Server mit IIS, nicht auf dem Gerät.

### Wichtige CONFIG-Schlüssel

Das vollständige Format steht in `oem-manuals/trendnet/UG_TE-350_TE-360_NetWare_ConfigFormat.pdf`,
Anhang B.

| Zeile     | Schlüssel            | Bedeutung                                      |
|-----------|----------------------|------------------------------------------------|
| 0001      | BOX_NAME             | Gerätename, max. 19 Zeichen, keine Leerzeichen |
| 0011-0014 | *_P                  | Protokolle IPX/SPX, TCP/IP, AppleTalk, NetBEUI |
| 0030-0034 | BAUDRATE...          | serielle Schnittstelle                         |
| 0100-0243 | Ln_PROUT             | Anschluss je logischem Drucker (P1, P2, SP)    |
|           | Ln_PREST/POSTR       | Steuerstring vor/nach Job (Hex, max. 15)       |
|           | Ln_CHGLF             | LF in CR+LF wandeln                            |
| 4000-4002 | IP_ADDR/GATEWAY/MASK | IP-Konfiguration                               |
| 4010/4011 | TCP_INT/TCP_CNT      | TCP-Wiederholintervall / -anzahl               |
| 4020      | DHCP_MODE            | DHCP ein/aus                                   |
| 4100-4109 | MAIL_*               | E-Mail-Druck (POP3), hier ungenutzt            |
| 6000-6144 | CONTACT, M*, T*      | SNMP-Manager und Traps (Community "public")    |

## Drucken

- LPD: Host 192.0.2.52, Queue `L1` (P1), `L2` (P2), `L3` (SP).
  - CUPS: `lpd://192.0.2.52/L1`
  - Windows: Standard-TCP/IP-Port mit LPR, Warteschlange `L1`
  - Kommandozeile: `lpr -H 192.0.2.52 -P L1 datei`
- RAW / Direct Socket: 9100/9101/9102 oder 4010/4020/4030 für L1/L2/L3 (beide gemessen,
  siehe oben). Daten, die kein Drucker abnimmt, bleiben liegen: der Anschluss steht auf
  "Printing / Direct Socket", bis das Gerät neu startet. Ein einzelner Connect, sofort
  wieder geschlossen, ließ die Anschlüsse auf Idle (gemessen auf 4010-4030); nach einem
  Portscan standen sie dagegen minutenlang auf "Direct Socket". Daher nicht leichtfertig
  testen.
- Hinweis aus dem Handbuch: Bei LPD druckt das Gerät die Datendatei sofort und ignoriert
  Optionen aus der Steuerdatei.

## Gemessenes Verhalten (PS301, FW 6022)

Gemessen mit `sercomm-printserver` und Rohsitzungen, 2026-10-23:

- **FTP-Login:** `USER <BOX_NAME>` antwortet `331`, `PASS` mit leerem Passwort `230 User
  logged in.`; ein falsches Passwort `531 Invalid password.`. `PWD`, `NOOP` und `PASV`
  antworten `500 Invalid command.`, `HELP` wie `SYST` mit `215 Print Server FW 6022`.
- **Eine Verbindung zur Zeit:** Direkt nach dem Ende einer FTP-Sitzung lehnt das Gerät neue
  Verbindungen etwa 0,1 s lang ab (ECONNREFUSED); danach nimmt es wieder an.
- **Neustart (`get RESET`):** Antwort `150`, 0 Byte Daten, `226`. Endet die Sitzung mit `QUIT`,
  startet das Gerät erst etwa 5 s später neu und antwortet bis dahin normal; ohne `QUIT` sofort.
  Ein Neustart dauert etwa 5 s. Erreichbarkeit kann ihn daher nicht sicher anzeigen, die
  SNMP-Uptime schon.
- **SNMP:** `sysUpTime` (1.3.6.1.2.1.1.3.0) ist mit der Community `public` lesbar und fällt
  beim Neustart auf nahezu 0 zurück. Der SNMP-Agent antwortet nur unter der eigenen Adresse des
  Geräts, nicht unter einer per ARP-Trick geliehenen (v1 und v2c, 2026-10-26); erst wenn ein
  Neustart die geliehene Adresse zur eigenen gemacht hat, antwortet er dort.
- **Neustart erkennen:** Ein Neustart zeigt sich nur an der Uptime. Auf das Wegbleiben von FTP
  zu warten, verpasste ihn in beiden Messungen (2026-10-26): Das Gerät war nach dem Neustart
  wieder da, bevor eine abgelehnte Verbindung länger als die 2 s Wiederholung des FTP-Clients
  dauerte.
- **Schreiben + Anwenden:** `put CONFIG`, Rücklesen, `get RESET`, bis das Gerät wieder
  antwortet: etwa 11 s.
- **Rücklesen nach `put CONFIG`:** Einmal speicherte das Gerät einen Wert anders als gesendet
  (`T4_S` 0 statt 1, nur `IP_ADDR` geändert); das nächste Hochladen speicherte ihn richtig. In
  60 Wiederholungen danach (unverändert, `IP_ADDR` geändert und nicht angewendet, zurück)
  stimmte jedes Rücklesen (2026-10-26). Die Ursache - ein verlorenes Byte beim Hochladen oder
  eine Änderung im Gerät - ist offen. `write_config` lehnt ein abweichendes Rücklesen mit
  `DeviceResponseError` ab und versucht es nicht selbst erneut, damit eine Änderung durch das
  Gerät sichtbar bleibt; der Aufrufer lädt erneut hoch.
- **IP-Wechsel:** Eine geänderte `IP_ADDR` gilt nach dem Neustart; das Gerät antwortet dann nur
  noch unter der neuen Adresse (Hin- und Rückweg gemessen).
- **Pakete an jede IP:** Das Gerät beantwortet Pakete an jede IP-Adresse, die ein Rechner per
  ARP auf seine MAC abbildet (beobachtet über einen veralteten ARP-Eintrag nach dem
  IP-Wechsel). Darauf beruht der ARP-Trick.
- **ARP-Trick hin und zurück (2026-10-26):** `arp assign-ip` auf eine freie Adresse und wieder
  auf die alte dauert je etwa 21 s samt Neustart; danach hält das Gerät nur die neue Adresse
  (ARP-Antwort und SNMP dort, die alte schweigt). Netzmaske, Gateway und DHCP bleiben.
- **`SETIP`:** speichert die Adresse, unter der das Gerät gerade läuft, als statische IP: sofort,
  ohne Neustart. Gemessen 2026-10-26: `IP_ADDR` auf eine andere Adresse geschrieben, aber nicht
  angewendet, dann `SETIP` - danach stand wieder die laufende Adresse in CONFIG, sonst blieb
  CONFIG unverändert. Eine per ARP-Trick geliehene Adresse übernimmt es nicht.
- **LPD ohne Drucker:** Das Gerät nimmt den Auftrag an (Anschluss "Printing", "OCCUPIED BY:
  LPD"), bestätigt die Datendatei aber nicht, solange kein Drucker sie abnimmt; der Client
  wartet bis zu seinem Timeout. Ein Neustart räumt den Anschluss (2026-10-26).
- **LPD-Queue-Status** (`0x03`/`0x04` + Queue) antwortet mit dem Monitor-Block des Anschlusses,
  eingeleitet von `(LPD Server):`.
- **Telnet:** Begrüßung `IAC WILL ECHO, IAC DO SGA, IAC WILL SGA`, dann `Welcome to Print
  Server` und `PS>`. Nach `monitor` folgt kein neuer Prompt; nach `exit` schließt das Gerät die
  Verbindung (etwa 1 s nach dem Verbindungsaufbau).
- **Suche im Netz:** Während eines Sweeps mit vielen gleichzeitigen Verbindungsversuchen
  brauchte der TCP-Connect zu vorhandenen Geräten 1,1 bis 2,2 s.

Ein zweiter PS301 mit **Firmware 6A10** im selben Netz zeigte:

- `SYST` und `HELP` antworten mit Zufallsbytes statt der Versionsnummer; `PSINF` nennt die
  Version korrekt (`6A10`).
- CONFIG ohne `WINS_IP`, `DHCP_MODE`, `LPT2MODE` und `LPT3MODE` (siehe `device-dump/fw6a10/`).
- Nach mehreren Such-Sweeps und lesenden Abfragen nahm er FTP, Telnet und LPD nicht mehr an,
  bis er aus- und eingeschaltet wurde (Ping ging weiter). Die Ursache ist nicht isoliert;
  `discover` sendet seitdem außer `QUIT` nichts.

## Beobachtungen und offene Punkte

- Beim Auslesen standen alle drei Anschlüsse auf `STATE: Printing`, `OCCUPIED BY: Direct
  Socket` mit 0 Bytes, auch noch Minuten später. Möglicherweise hat ein Portscan auf
  9100-9102 das ausgelöst; ein anderer Client ist ebenso möglich. Nach einem Neustart des
  Geräts standen alle drei auf `STATE: Idle`; CONFIG war danach Zeile für Zeile unverändert.
- An keinem Anschluss hängt derzeit ein Drucker. `PRINTER STATUS: Offline` ist daher der
  erwartete Zustand (vor dem Neustart meldete SP einmal `On-Line`).
- Telnet ist ohne Passwort offen, FTP gab Dateien ohne Login heraus. Das Gerät sollte nur
  in einem vertrauenswürdigen Netz hängen.

## Dateien in diesem Verzeichnis

- `device-dump/`: CONFIG, PSINF und Telnet-Monitor dieses Geräts.

Die Herstellerhandbücher und Firmware-Images unter `oem-manuals/` sind urheberrechtlich
geschützt und liegen deshalb nur lokal, nicht im Repository. Bezugsquellen stehen unter
"Quellen" am Ende dieses Dokuments.

- `oem-manuals/trendnet/` (TE-310 = 2 par + 1 ser, TE-360 = 1 par):
  - `Spec_TE-310.pdf`, `Spec_TE-360.pdf`: Datenblätter.
  - `UG_TE-310.zip` und entpackt `UG_TE-310/`: Benutzerhandbuch 1997 (Word), dazu
    Rohtext-Auszüge `*.txt` zum Durchsuchen. TCP2 = TCP/IP und Unix, TCPIPAPP = Anhänge,
    NETWARE2 = NetWare, WNETBEUI = Windows/NetBEUI.
  - `UG_TE-350_TE-360_NetWare_ConfigFormat.pdf`: NetWare-Handbuch, Anhang B mit dem
    vollständigen CONFIG-Format, Anhang D Parallel-Pinbelegung.
  - `TE3x0_UNIX.pdf`, `TE3x0_Win2000_TCPIP.pdf`, `TE3x0_Win2000_NETBEUI.pdf`,
    `TE3x0_WinXP_TCPIP.pdf`: Kurzanleitungen.
  - `TE310360_utility.zip`: Utility-Disks (BiAdmin für Win9x/NT, WFW, DOS PSCONFIG/QUICKSET).
  - `TE100-P1P/` (1 par, 10/100): `FW_TE100-P1P_V1_v6034.zip` (Firmware 6034 mit
    Release Notes), `UG_`, `UnixUG_` (vollständige CONFIG-Tabelle, FTP-Dateien, Telnet, DSI),
    `QIG_`, `FAQ_`, `Spec_` sowie `Utility_TE100-P1P_P1U.zip` (Utility-CD, 19 MB). Dazu
    `QIG_TE100-P1U.pdf` und `Spec_TE100-P1U.pdf` für das USB-Modell.
  - `TEW-P1U1P/` (1 par + 1 USB, WLAN): Firmware 6035 (`FW_TEW-P1U1Pv6035.zip`,
    `Firmware_Upgrade_TEWP1U1P.zip`), `UG_`, `QIG_`, `FAQ_`, `Utility_TEW-P1U1P.zip`.
- `oem-manuals/linksys/`:
  - `efsp42_epsx3_ppsx1_ug_2000.pdf`: Handbuch 2000 für EFSP42, EPSX3, PPSX1.
  - `epsx3_ppsx1_ug_v2.pdf`: Handbuch EPSX3 v2 / PPSX1 v2 mit Bi-Admin-Kapitel.
  - `ppsx1_fw_6017.zip` (PPSX1, 1 par) und `epsx3_fw.zip` (EPSX3, 3 par): Firmware-Images
    mit Versionshistorie in `ver.txt`.
- `oem-manuals/perle/` (IOPRINT+):
  - `ioprint_config_inst.pdf`: Installations- und Konfigurationshandbuch der Familie, v1.3.
  - `ftp.pdf`, `unix.pdf`, `biadmin.pdf`, `ntserver.pdf`, `netware.pdf`, `nw_bind.pdf`,
    `psc_bind.pdf`, `psc_nds.pdf`, `wpconfig.pdf`, `webadmin.pdf`, `browser.pdf`, `snmp.pdf`,
    `int_prn.pdf`, `apple.pdf`: Einzeldokumente je Thema.
  - `ioprint_quick_install.pdf`: Kurzanleitung für IOPRINT+ Jr, IOPRINT+ und IOPRINT+ FAST.
  - `kb_q*.html`: Perle-Knowledge-Base: q404 FTP-Konfiguration, q403 Werkseinstellung per
    FTP, q171 Reset bei unbekannter IP per TFTP, q71 Reset allgemein, q163 FAQ (u.a. DSI
    4010/4020/4030, Firmware-Update mit Perle_dl), q456 DIP-Schalter des FAST.
- `oem-manuals/netgear/` (PS101/PS104/PS105/PS110/PS113):
  - `ps100_installref_M-PS100NA-4_2000.pdf`: Installation and Reference, Mai 2000.
  - `ps104105110refman_M-PS100NA-1_1999.pdf`: ältere Ausgabe, Mai 1999.
  - `ps104105110inst_eng.pdf`: Installationsanleitung.
  - `PS101_qcard_2002.pdf`, `PS101_datasheet_2003.pdf`, `PS105_and_PS110_datasheet.pdf`.
  - `Setup_Software_3.01_PS101-PS113.zip`: Setup-Software für PS101 bis PS113.
  - `firmware/PS110_FW_60xx.zip`: Firmware 6017, 6025, 6026, 6028, trotz Dateiname nur für
    PS110 (Seriennummern PS11A-C = 6017, PS11D-E = 6025, PS11F = 6026/6028).
  - `firmware/FW_Upgrade_Utility_2.0_PS104_PS105_PS110.zip`: Upgrade-Programm auf 6017,
    enthält eventuell PS104/PS105-Images (nicht entpackt).
- `oem-manuals/other/FAU_Printserver-PSE.pdf`: Inventarblatt der FAU zu einem baugleichen
  "PSE1S2P-FNU" (2 par + 1 ser), das unter mehreren Marken verkauft wurde.

Nicht heruntergeladen:

- Perle-Firmware (`ioprint-2p1s6017.zip`, BiAdmin 3.14 u.a.): nur über ein
  Download-Formular mit Lizenzbestätigung auf https://www.perle.com/downloads/print.shtml.
- Perle-Modelldokumente `PS1S2P.pdf` (2P1S mit LEDs, DIP-Schaltern, CONFIG-Tabelle) und
  `PS1P100.pdf`/`ps1p.pdf` (1-Port): offline (404), auch im Webarchiv nicht gefunden.
- Netgear PS101 Reference Manual und PS101-Firmware: keine direkte URL (ManualsLib hat das
  Handbuch nur im Online-Viewer).
- Firmware 6022 (die dieses Geräts) ist nirgends aufgetaucht.

## Quellen

- TRENDnet: https://download.trendnet.com/TE-310/ und https://download.trendnet.com/TE-360/
- Perle Dokumentation: https://www.perle.com/support_services/documentation_pdfs/
- Perle Knowledge Base IOPRINT+: https://help.perle.com/?c=51
- TRENDnet TE100-P1P / TEW-P1U1P: https://downloads.trendnet.com/TE100-P1P/ und
  https://downloads.trendnet.com/TEW-P1U1P/
- Linksys: https://downloads.linksys.com/downloads/userguide/epsx3_ppsx1_ug.pdf und
  https://downloads.linksys.com/downloads/firmware/1224638369093/ppsx1_fw.zip
- Netgear: https://www.downloads.netgear.com/files/ps100_installref.pdf sowie
  https://www.downloads.netgear.com/files/GDC/PS104/ (Firmware, Setup-Software)
- Netgear PS101 Reference Manual, FTP-Dateien:
  https://www.manualslib.com/manual/299000/Netgear-Ps101.html?page=75
- FAU Inventar: https://iser.wisski.data.fau.de/sites/default/files/2024-02/Printserver-PSE.pdf
- Sercomm Fast PrintMate 1P Datenblatt:
  https://www.yumpu.com/en/document/view/15516228/sercomm-fast-printmate-1p-deltaco
