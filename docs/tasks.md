# Fem opgaver til Stemmero

Opgaverne følger brugerens fem punkter. Root samler ændringerne og udgiver først en ny installer, når de relevante Windows-tests består.

## 1. Danske advarsler og egne lydfiler

[GitHub-opgave 1](https://github.com/monstermus/stemmero/issues/1). Implementeret af subagent og integreret af root. Testresultat og release står i GitHub-opgavens kommentarer.

Programmet skal sige en dansk advarsel ved gul, orange og rød grænse. En voksen skal kunne vælge en egen WAV-fil pr. niveau, høre den, stoppe den og gendanne standardstemmen.

Krav:
- De tre standardstemmer følger med installeren og kræver intet internet.
- Egne filer valideres og kopieres til programmets indstillingsmappe.
- Advarsler overlapper ikke. En højere advarsel kan afbryde en lavere.
- Test af lyd eller bannere tæller ikke som rigtige advarsler i opgave 5.
- PIN fra opgave 4 beskytter valg af lyd og andre lydindstillinger.

Godkendelse kræver tests af alle niveauer, filvalg, ugyldige filer, gendannelse og de pakkede lydfiler. Funktionen er udgivet i v1.1.0. En subagent kontrollerer samspillet med de nye funktioner.

## 2. Genstart efter lukning

[GitHub-opgave 2](https://github.com/monstermus/stemmero/issues/2). Implementeret af subagent og integreret af root. Testresultat og release står i GitHub-opgavens kommentarer.

Overvågningen skal fortsætte, når vinduet lukkes, og programmet skal vende tilbage efter processtop eller nedbrud.

Krav:
- Vinduets lukkeknap skjuler indstillingerne og låser dem. Mikrofonovervågningen fortsætter.
- En separat supervisor genstarter en afsluttet app inden for få sekunder.
- En selvstændig planlagt minutopgave starter supervisoren igen, hvis hele procestræet bliver dræbt.
- Installationsdagen skal være dækket uden først at kræve nyt Windows-login.
- Opgradering og afinstallation stopper hele programmets procestræ før filer udskiftes eller fjernes.
- App, supervisor og autostart må kun køre én gang pr. Windows-bruger.

Godkendelse kræver reelle Windows-tests af processtop, ny proces-id, stop af hele procestræet, geninstallation og afinstallation. Lokal supervisor-test skal også kontrollere normal exit og crash.

## 3. Automatisk valg af mikrofon

[GitHub-opgave 3](https://github.com/monstermus/stemmero/issues/3). Implementeret af subagent og integreret af root. Testresultat og release står i GitHub-opgavens kommentarer.

Programmet skal begynde at lytte uden manuelt mikrofonvalg og følge Windows' standardinput.

Krav:
- Automatisk valg er standard, også ved opgradering fra en tidligere version.
- Brug Windows' gyldige standardmikrofon. Hvis den mangler, vælges headset og derefter et andet input.
- Windows' konkrete standardenhed skal have forrang, hvis lydbibliotekets standardindeks stadig peger på et andet headset.
- Enheder uden inputkanaler kan aldrig vælges.
- Skift af standardmikrofon og frakobling eller genindsættelse skal føre til nyt valg og genoptagelse af overvågning.
- En voksen kan bruge et manuelt valg. Et midlertidigt fallback overskriver ikke denne præference.
- Hvis ingen mikrofon er tilgængelig, viser programmet det og forsøger igen. Manglende input tæller ikke som en advarsel.

Godkendelse kræver deterministiske tests af valg, ingen enheder, standardskift og frakobling. Fysisk headset og Windows' enhedsændringer skal markeres som manuel kontrol, indtil de faktisk er afprøvet.

## 4. PIN-beskyttede indstillinger

[GitHub-opgave 4](https://github.com/monstermus/stemmero/issues/4). Implementeret af subagent og integreret af root. Testresultat og release står i GitHub-opgavens kommentarer.

Barnet skal kunne se programmets status uden at kunne ændre indstillingerne. En voksen vælger PIN ved første opsætning.

Krav:
- Mikrofonvalg, grænser, reaktionstid, pause, lydfiler og konsekvensregler kræver oplåsning med PIN.
- Programmet starter låst og låser igen ved lukning eller minimering og efter inaktivitet.
- PIN har 4 til 12 cifre og gemmes som saltet afledning. Klartekst-PIN må ikke stå i filer eller logs.
- Gentagne forkerte PIN-forsøg giver ventetid, som overlever genstart.
- Skift af PIN kræver eksisterende PIN. En beskadiget PIN-fil må ikke åbne indstillingerne.
- En separat gendannelseskode vises ved opsætning. Den roteres efter brug og gemmes kun som hash.
- PIN beskytter programmets brugerflade. En Windows-administrator eller en bruger med direkte skriveadgang til programmets data kan omgå denne beskyttelse.

Godkendelse kræver tests af låsning ved start, alle ændringsveje, forkert PIN, ventetid, PIN-skift, korrupt fil og gendannelse med en separat kode.

## 5. Låsning eller nedlukning efter gentagne advarsler

[GitHub-opgave 5](https://github.com/monstermus/stemmero/issues/5). Implementeret af subagent og integreret af root. Testresultat og release står i GitHub-opgavens kommentarer.

En voksen skal kunne vælge et antal advarsler i et tidsrum og få programmet til at låse Windows eller anmode om nedlukning, når grænsen nås.

Krav:
- Funktionen er slået fra, indtil en voksen aktiverer den med PIN.
- Antal, tidsrum og handling kan konfigureres. Startværdierne er 5 advarsler på 10 minutter og skærmlås.
- Tællereglen er ét sammenhængende udbrud pr. advarsel. Farveskift og gentagne lydafspilninger tæller ikke ekstra. En voksen kan vælge indstillingerne i programmet.
- Historik og en igangværende nedtælling overlever genstart.
- Nedlukning angives i sekunder fra 0 til 300. 0 betyder straks uden nedtælling. Standardværdien er 60 sekunder. Ved en positiv tid kræver annullering en frisk PIN-godkendelse.
- Nedlukning må ikke bruge tvungen lukning af åbne programmer.
- Test, lydafprøvning, pause og manglende mikrofon tæller ikke som advarsler.
- Ingen tests må faktisk låse eller slukke udviklingsmaskinen eller CI-maskinen.

Godkendelse kræver test af tidsvinduet, tælleregler, grænser, genstart, annullering, fejl fra Windows og én handling pr. udløst konsekvens. Root integrerer PIN og visning, og en subagent implementerer policy og Windows-kald med injicerede test-handlinger.

