# Oslo-skjerm

Skjerm for Rock 4C+ som viser avganger fra **Skøyen stasjon** og **Borgen T-bane**, pluss dagens vær i Oslo.
Data hentes fra Entur (avganger, sanntid) og MET Norway (vær). Serveren kjører lokalt på boksen,
så skjermen trenger ikke logge inn eller å ha tilgang til nettsiden din.

## Innhold

| Fil | Hva den gjør |
|---|---|
| `server.py` | Henter data hvert minutt (vær hvert 15. min), og serverer siden på `127.0.0.1:8080`. Bare standardbiblioteket i Python. |
| `config.json` | Stoppesteder, koordinater, portnummer og identifikasjon mot API-ene. |
| `web/index.html` | Skjermsiden. Oppdaterer seg selv. |
| `install.sh` | Installerer pakker, systemtjeneste og autostart for kiosk-vinduet. |

---

## 1. Før du pakker: fyll inn config

Åpne `config.json` og endre to ting:

- **`met_user_agent`**: MET krever at du identifiserer appen. Skriv f.eks. `oslo-skjerm/1.0 (kontakt: din e-post eller nettside)`.
- **`entur_client_name`**: Entur ber om et navn som identifiserer klienten. `oslo-skjerm` går fint, eller `dittnavn-oslo-skjerm`.

Stopp-IDene er allerede slått opp:

- Skøyen stasjon: `NSR:StopPlace:59651`
- Borgen T-bane: `NSR:StopPlace:58272`

---

## 2. Flash-image

Bruk det offisielle Radxa-imaget for ROCK 4C+ (OKDO-kortet er basert på samme design):

**`rock-4c-plus_bookworm_kde_r2.output_512.img.xz`** (Debian 12 med KDE-desktop, ca. 1,4 GB), fra den nyeste utgivelsen [rsdk-r2](https://github.com/radxa-build/rock-4c-plus/releases/tag/rsdk-r2). Filen må ha desktop, fordi kiosk-vinduet trenger en skjerm å vises på.

1. Last ned filen. Du trenger ikke pakke den ut, for balenaEtcher leser `.img.xz` direkte.
2. Skriv den til microSD eller eMMC med [balenaEtcher](https://etcher.balena.io/).
3. Sett kortet i boksen, koble til nettverk (kabel anbefales) og HDMI-skjerm, og start.

Standardkontoen i de offisielle imagene er **`radxa` / `radxa`**. Bytt passord med en gang (se steg 3).

---

## 3. Første oppstart: aktiver SSH (med HDMI-skjermen én gang)

Gjør dette én gang på skjermen, med tastatur. Etterpå kan alt gjøres fra Windows-PCen.

```bash
passwd                                  # bytt passord fra "radxa"
systemctl status ssh                    # sjekk om SSH kjører
```

Hvis SSH ikke er installert eller ikke kjører:

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
```

Finn IP-adressen til boksen:

```bash
hostname -I
```

Noter adressen (f.eks. `192.168.1.50`).

Sjekk også at **auto-innlogging** er slått på i innstillingene for innlogging, så kiosk-vinduet starter av seg selv etter strøm på.

---

## 4. Logg inn med SSH fra Windows

SSH og SCP finnes i Windows 10/11 (PowerShell).

```powershell
ssh radxa@192.168.1.50
```

Valgfritt, men anbefalt: logg inn uten passord med nøkkel. På Windows:

```powershell
ssh-keygen -t ed25519
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh radxa@192.168.1.50 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

Når nøkkelen fungerer, kan du slå av passordinnlogging på boksen (`/etc/ssh/sshd_config.d/`, sett `PasswordAuthentication no`, og `sudo systemctl restart ssh`).

---

## 5. Pakk og overfør

Pakken `oslo-skjerm.tar.gz` ligger ferdig bygget ved siden av denne mappen. Hvis du endrer filer selv, pakk på nytt med:

```powershell
tar -czf oslo-skjerm.tar.gz server.py config.json web install.sh README.md
```

Kopier pakken til boksen:

```powershell
scp oslo-skjerm.tar.gz radxa@192.168.1.50:~/
```

Installer på boksen:

```powershell
ssh -t radxa@192.168.1.50 "mkdir -p oslo-skjerm && tar -xzf oslo-skjerm.tar.gz -C oslo-skjerm && cd oslo-skjerm && sudo bash install.sh"
```

Passordet du blir spurt om er `sudo`-passordet (samme som kontopassordet).

Start boksen på nytt, eller kjør `sudo reboot`. Skjermen skal åpne seg av seg selv.

**Oppdatering senere:** kjør de to kommandoene på nytt (`scp` + `install.sh`). Installasjonen overskriver filene, og config-endringer tar effekt med en gang.

---

## 6. Feilsøking

```bash
curl http://127.0.0.1:8080/api/data     # gir JSON med avganger og vær
journalctl -u oslo-skjerm -f            # logg fra serveren
sudo systemctl restart oslo-skjerm      # etter endringer i config
```

- **Vær mangler**: sjekk at `ca-certificates` er installert (install.sh gjør dette), og at `met_user_agent` er fylt ut.
- **Skjermen åpnes ikke**: sjekk auto-innlogging, og at `~/.config/autostart/oslo-skjerm.desktop` finnes. Med KDE kan økten være Wayland. Velg da en X11-økt på innloggingsskjermen. Uten `xset` fungerer kiosken likevel, men skjermspareren slår seg ikke av.
- **Avganger mangler**: Entur svarer ikke, eller stoppested-ID er feil. Feilmeldingen vises øverst på skjermen.

## Sikkerhet

Serveren lytter kun på `127.0.0.1`, så den er ikke åpen for andre i nettverket. SSH er bare tilgjengelig på LAN. Ikke port-forward 22 i ruteren.
