# Stemmero

Stemmero advarer dig, når du taler for højt i headsettet under spil. Et gult, orange eller rødt banner vises over spillet, og en dansk stemme minder dig om at skrue ned for stemmen.

[Hent Stemmero til Windows](https://github.com/monstermus/stemmero/releases/latest/download/Stemmero-Setup.exe) · [Se seneste udgivelse](https://github.com/monstermus/stemmero/releases/latest)

## Installation

1. Hent **Stemmero-Setup.exe** via linket ovenfor.
2. Kør filen og følg installeren. Du behøver hverken Python, en GitHub-konto eller administratorrettigheder.
3. Stemmero vælger automatisk Windows' standardmikrofon. En voksen åbner programmet fra Start-menuen og vælger **Opret PIN**. Gem gendannelseskoden privat.
4. Lås indstillingerne op, tal normalt, og sæt den gule grænse lidt over dit normale niveau.
5. Brug **Afspil** ved hvert lydniveau og **Test bannere** til visningen. Lås indstillingerne igen. Brug et spil i vindue eller borderless.

Kræver Windows 10 eller 11 med en x64-processor. Installeren er ikke kodesigneret, så Windows kan vise en SmartScreen-advarsel. Hent kun installeren fra dette repos Releases. Hver udgivelse har en SHA-256-kontrolsum i `SHA256SUMS.txt`.

## Hvad programmet gør

| Niveau | Banner |
| --- | --- |
| Gul | Lidt højt |
| Orange | Du taler for højt |
| Rød | ALT FOR HØJT! |

Du kan justere hver grænse, reaktionstiden, bannerets placering og lyden. Banneret tager ikke imod klik. Korte udbrud under reaktionstiden udløser ingen advarsel.

## Advarselslyde

Tre danske stemmeklip følger med programmet og virker uden internet eller ekstra stemmepakker:

| Niveau | Talt advarsel |
| --- | --- |
| Gul | Du taler lidt for højt. |
| Orange | Du taler for højt. Skru ned for stemmen. |
| Rød | Du taler alt for højt. Tal lavere nu. |

Under **Advarselslyde** kan du vælge en egen lyd til hvert niveau med **Vælg WAV...**. Brug **Afspil** til at høre den, **Stop lyd** til at afbryde og **Gendan** til at vælge standardstemmen igen. Afspil fungerer også, når automatiske advarselslyde er slået fra.

Egne filer skal være ukomprimeret WAV med 8- eller 16-bit PCM-lyd, mono eller stereo, højst 30 sekunder og 10 MB. Programmet gemmer en kopi sammen med dine indstillinger, så du bagefter kan flytte originalen. Hvis din lyd ikke kan afspilles, bruger programmet standardstemmen og viser en besked. Lydstyrken følger Stemmeros indstilling i Windows' lydstyrkemixer.

Advarsler afspilles uden overlap. En højere advarsel kan afbryde en lavere, og et langt klip starter ikke forfra, mens det spiller. **Afspil lyd** slår de automatiske lyde fra. **Test bannere** viser bannerne uden lyd.

Stemmero starter minimeret ved login. Lukknappen skjuler vinduet og låser indstillingerne, mens overvågningen fortsætter. Hvis appen afsluttes eller crasher, forsøger en supervisor at starte den igen efter to sekunder. En separat minutkontrol kan genstarte hele procestræet. Åbn vinduet igen fra Start-menuen. En voksen kan holde pause ved at låse op med PIN og fjerne markeringen **Aktiv**.

Lyd behandles i hukommelsen på din computer. Programmet gemmer eller sender ingen lydoptagelser og bruger ingen netværkstjenester. Det måler mikrofonens signalniveau i dBFS. Det genkender ikke stemmer og måler ikke lydtryk i rummet. Baggrundslyde kan derfor også udløse en advarsel.

## Automatisk mikrofon

**Vælg automatisk** er slået til som standard. Programmet følger Windows' standardinput. Hvis det ikke findes, prøver det et headset og derefter et andet gyldigt input. Et enhedstjek opdager standardskift og frakobling uden løbende at afbryde en rask lydstrøm. Mangler alle mikrofoner, viser programmet en besked og forsøger igen.

Ved flere headset eller flere indgange til samme headset bruger automatisk valg Windows' præcise standardenhed. Programmer som Discord kan have deres eget mikrofonvalg. Vælg samme mikrofon manuelt i Stemmero, hvis det valg skal følges.

En voksen kan slå automatisk valg fra og vælge en bestemt mikrofon. Hvis den mangler midlertidigt, bevarer programmet valget og bruger et midlertidigt input, indtil den valgte mikrofon vender tilbage.

## Forældre-PIN

Indstillingerne er låst ved hver start. PIN beskytter mikrofonvalg, grænser, reaktionstid, pause, lyde og konsekvensregler. Første gang vælger en voksen en PIN på 4 til 12 cifre. Der er ingen standard-PIN. En voksen skal afslutte opsætningen, før barnet overtager computeren.

Programmet gemmer kun saltede PIN-hashes. Fem forkerte forsøg giver 30 sekunders ventetid, også efter genstart. Indstillingerne låser ved minimering, fokus væk fra appen eller to minutters inaktivitet. **Skift PIN** kræver den gamle PIN. **Glemt PIN** bruger den separate gendannelseskode og viser en ny kode efter nulstilling. Gem koden privat. En beskadiget PIN-fil låser indstillingerne frem for at åbne dem.

PIN beskytter brugerfladen. Den stopper ikke en Windows-administrator eller en bruger med direkte skriveadgang til programmets data i at ændre eller fjerne beskyttelsen. Installér og konfigurér programmet, før barnet tager det i brug.

## Gentagne advarsler

Funktionen er slået fra som standard. En voksen kan under **Gentagne advarsler** vælge antal, tidsrum og enten **Lås skærmen** eller **Sluk computeren** og derefter trykke **Gem regel**. Startværdierne er fem advarsler på ti minutter. Du kan tælle alle farver eller kun orange og rød.

Et sammenhængende højt udbrud tæller én gang. Farveskift og gentagen afspilning tæller ikke ekstra. Stemmen skal være under den gule grænse i 1,2 sekunder, før et nyt udbrud kan tælle. Afprøvning af lyd og bannere, pause og manglende mikrofon tæller ikke. Historikken følger et rullende tidsvindue og overlever genstart.

Skærmlås anmodes straks, når grænsen nås. Nedlukning angives i sekunder fra 0 til 300. **0 betyder straks**, uden nedtælling. Standardværdien er fortsat 60 sekunder. Ved en positiv tid kan en voksen bruge **Annullér med PIN**, som kræver en ny PIN-godkendelse, også hvis indstillingerne allerede er låst op. Lukning eller genstart af appen nulstiller ikke en igangværende nedtælling.

Programmet anmoder om almindelig Windows-nedlukning og tvinger ikke åbne programmer til at lukke. Windows eller apps med ugemt arbejde kan derfor blokere nedlukningen. Efter en gennemført anmodning begynder optællingen forfra. En fejl fra Windows vises og gentages ikke automatisk. En voksen kan nulstille tæller eller fejl med PIN. Pause stopper ny optælling, men annullerer ikke en allerede udløst nedtælling.

## Afinstallation

Vælg **Indstillinger > Apps > Stemmero > Afinstallér**. Det fjerner programmet og autostart. Dine indstillinger bevares i `%APPDATA%\Stemmero`. Slet den mappe, hvis du også vil fjerne indstillingerne.

## Begrænsninger og teststatus

Banneret kan vises over vinduer og borderless-spil. Eksklusiv fuldskærm kan skjule det. Spil og anti-cheat kan også begrænse visningen.

GitHub Actions tester lydlogik, lydfiler, import og lydindstillinger, starter den pakkede app med dens medfølgende lydfiler og kontrollerer installation, autostartregistrering og afinstallation på Windows. Afspilning gennem et fysisk headset, almindelige brugerrettigheder og visning over et rigtigt spil er endnu ikke afprøvet manuelt.

## Byg selv

Brug Python 3.12 med tkinter samt [NSIS](https://nsis.sourceforge.io/Download) på Windows. Kør derefter `byg_installer.bat`. Den installerer de låste buildafhængigheder, kører testene og bygger `Stemmero-Setup.exe` med [PyInstaller](https://www.pyinstaller.org/en/stable/usage.html).

Kør kun testene med:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Opgaver

De fem ønskede ændringer og deres acceptkriterier står i [opgavebeskrivelsen](docs/tasks.md) og [GitHub Issues](https://github.com/monstermus/stemmero/issues).

## Udgivelser

Push og pull requests bygger og tester appen. Buildfiler kan hentes fra workflowet **Byg installer** under Actions. Færdige udgivelser ligger under **Releases**, hvor de kan hentes uden login.

For en ny udgivelse opdaterer vedligeholderen versionsnummeret i `stemmero.py` og `installer.nsi`, committer ændringen og pusher et tilsvarende tag, for eksempel `v1.0.1`. Workflowet tester og bygger, før det udgiver installeren og kontrolsummen. Det faste downloadlink øverst følger den seneste udgivelse.

## Licens

[MIT](LICENSE). Alle må hente, bruge, ændre og dele programmet, også kommercielt. Bevar licensens ophavsretsmeddelelse. Programmet bygger på det indsendte Stemmevagt-projekt af Daniel Prehn.

Installeren medtager bibliotekernes licenstekster i `THIRD-PARTY-LICENSES.txt` i programmappen.
