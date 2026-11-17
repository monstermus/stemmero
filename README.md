# Stemmero

Stemmero advarer dig, når du taler for højt i headsettet under spil. Et gult, orange eller rødt banner vises over spillet, og en dansk stemme minder dig om at skrue ned for stemmen.

[Hent Stemmero til Windows](https://github.com/monstermus/stemmero/releases/latest/download/Stemmero-Setup.exe) · [Se seneste udgivelse](https://github.com/monstermus/stemmero/releases/latest)

## Installation

1. Hent **Stemmero-Setup.exe** via linket ovenfor.
2. Kør filen og følg installeren. Du behøver hverken Python, en GitHub-konto eller administratorrettigheder.
3. Åbn **Stemmero** fra Start-menuen, vælg mikrofonen, og tal normalt. Sæt den gule grænse lidt over dit normale niveau.
4. Brug **Afspil** ved hvert lydniveau og **Test bannere** til visningen. Brug et spil i vindue eller borderless.

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

Stemmero starter minimeret ved login. Windows Opgavestyring kontrollerer hvert minut, om programmet stadig kører, og genstarter det, hvis det lukkes. Fjern markeringen **Aktiv**, hvis du vil holde pause. Åbn indstillingerne igen fra Start-menuen. Hvis headsettet afbrydes, forsøger programmet at finde en mikrofon igen.

Lyd behandles i hukommelsen på din computer. Programmet gemmer eller sender ingen lydoptagelser og bruger ingen netværkstjenester. Det måler mikrofonens signalniveau i dBFS. Det genkender ikke stemmer og måler ikke lydtryk i rummet. Baggrundslyde kan derfor også udløse en advarsel.

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

## Udgivelser

Push og pull requests bygger og tester appen. Buildfiler kan hentes fra workflowet **Byg installer** under Actions. Færdige udgivelser ligger under **Releases**, hvor de kan hentes uden login.

For en ny udgivelse opdaterer vedligeholderen versionsnummeret i `stemmero.py` og `installer.nsi`, committer ændringen og pusher et tilsvarende tag, for eksempel `v1.0.1`. Workflowet tester og bygger, før det udgiver installeren og kontrolsummen. Det faste downloadlink øverst følger den seneste udgivelse.

## Licens

[MIT](LICENSE). Alle må hente, bruge, ændre og dele programmet, også kommercielt. Bevar licensens ophavsretsmeddelelse. Programmet bygger på det indsendte Stemmevagt-projekt af Daniel Prehn.

Installeren medtager bibliotekernes licenstekster i `THIRD-PARTY-LICENSES.txt` i programmappen.
