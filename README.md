# Stemmero

Stemmero advarer dig, når du taler for højt i headsettet under spil. Et gult, orange eller rødt banner vises over spillet, og en tone minder dig om at skrue ned for stemmen.

[Hent Stemmero til Windows](https://github.com/monstermus/stemmero/releases/latest/download/Stemmero-Setup.exe) · [Se seneste udgivelse](https://github.com/monstermus/stemmero/releases/latest)

## Installation

1. Hent **Stemmero-Setup.exe** via linket ovenfor.
2. Kør filen og følg installeren. Du behøver hverken Python, en GitHub-konto eller administratorrettigheder.
3. Åbn **Stemmero** fra Start-menuen, vælg mikrofonen, og tal normalt. Sæt den gule grænse lidt over dit normale niveau.
4. Tryk **Test advarsel**, og brug et spil i vindue eller borderless.

Kræver Windows 10 eller 11 med en x64-processor. Installeren er ikke kodesigneret, så Windows kan vise en SmartScreen-advarsel. Hent kun installeren fra dette repos Releases. Hver udgivelse har en SHA-256-kontrolsum i `SHA256SUMS.txt`.

## Hvad programmet gør

| Niveau | Banner |
| --- | --- |
| Gul | Lidt højt |
| Orange | Du taler for højt |
| Rød | ALT FOR HØJT! |

Du kan justere hver grænse, reaktionstiden, bannerets placering og lyden. Banneret tager ikke imod klik. Korte udbrud under reaktionstiden udløser ingen advarsel.

Stemmero starter minimeret ved login. Windows Opgavestyring kontrollerer hvert minut, om programmet stadig kører, og genstarter det, hvis det lukkes. Fjern markeringen **Aktiv**, hvis du vil holde pause. Åbn indstillingerne igen fra Start-menuen. Hvis headsettet afbrydes, forsøger programmet at finde en mikrofon igen.

Lyd behandles i hukommelsen på din computer. Programmet gemmer eller sender ingen lydoptagelser og bruger ingen netværkstjenester. Det måler mikrofonens signalniveau i dBFS. Det genkender ikke stemmer og måler ikke lydtryk i rummet. Baggrundslyde kan derfor også udløse en advarsel.

## Afinstallation

Vælg **Indstillinger > Apps > Stemmero > Afinstallér**. Det fjerner programmet og autostart. Dine indstillinger bevares i `%APPDATA%\Stemmero`. Slet den mappe, hvis du også vil fjerne indstillingerne.

## Begrænsninger og teststatus

Banneret kan vises over vinduer og borderless-spil. Eksklusiv fuldskærm kan skjule det. Spil og anti-cheat kan også begrænse visningen.

GitHub Actions tester lydlogik og indstillinger, starter den pakkede app og kontrollerer installation, autostartregistrering og afinstallation på Windows. Et fysisk headset, almindelige brugerrettigheder og visning over et rigtigt spil er endnu ikke afprøvet manuelt.

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
