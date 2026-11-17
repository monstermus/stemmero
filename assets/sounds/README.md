# Danske advarsler

De tre WAV-filer er genereret lokalt med Piper og den danske stemme `da_DK-talesyntese-medium`. De følger projektets MIT-licens. Appen indeholder de færdige lydfiler og bruger ingen talesyntese ved afspilning.

Tekster, kontrolsummer, modelkilde og lydbehandling står i `manifest.json`. Hver fil er mono, 22.050 Hz og 16-bit PCM. FFmpeg har normaliseret lydstyrken til -20 LUFS med en maksimal spids på -3 dBTP.

Stemmens [modelkort](https://huggingface.co/rhasspy/piper-voices/blob/main/da/da_DK/talesyntese/medium/MODEL_CARD) angiver det danske Talesyntese-datasæt og CC0. Modellen følger ikke med programmet.
